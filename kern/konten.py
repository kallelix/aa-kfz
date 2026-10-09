"""Persönliche Backoffice-Konten (Lastenheft B-01 bis B-04).

Ersetzen das gemeinsame Passwort. Ein Konto hat eine Mailadresse, einen
Namen, ein Kürzel – das landet als „bearbeitet von“ in den Daten –, eine
Rolle und die Bereiche, die es sehen darf.

Hier steht nur, was mit der Datenbank zu tun hat. Keks, CSRF und Weiterleitung
bleiben in kern/auth.py, die Seiten in kern/konten_app.py.

Alle Zufallswerte – Sitzung im Keks, Link in der Einladung – stehen in der
Datenbank nur als sha256. Wer die Tabellen liest, kann sich damit weder
anmelden noch ein Passwort setzen.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from datetime import timedelta
from pathlib import Path
from typing import Callable

import bcrypt

from kern.db import Datenbank, IntegrityError, Zeile

BEREICHE = {"kennzeichen": "Kennzeichen", "presse": "Presse", "helfer": "Helfer"}
ROLLEN = {
    "admin": "Admin",
    "orga": "Orga",
    "bereichsleitung": "Bereichsleitung",
    "lesend": "Lesend",
}
ROLLEN_TEXT = {
    "admin": "alle Bereiche, dazu die Konten",
    "orga": "darf in seinen Bereichen alles bearbeiten",
    "bereichsleitung": "sieht im Helferbereich nur die Bereiche, die es leitet, "
                       "mit ihren Schichten und Leuten",
    "lesend": "sieht seine Bereiche, ändert nichts",
}

EINLADUNG_GILT = timedelta(days=7)
ZURUECKSETZEN_GILT = timedelta(hours=24)
PASSWORT_MINDESTENS = 10

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_KUERZEL = re.compile(r"^[A-ZÄÖÜ0-9-]{1,10}$")


class Fehler(ValueError):
    """Eine Eingabe, die nicht geht – mit einem Satz für den Menschen."""


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def email_normal(roh: str) -> str:
    return (roh or "").strip().lower()


def passwort_regeln(passwort: str) -> str:
    """Leer, wenn das Passwort taugt, sonst der Grund."""
    if len(passwort) < PASSWORT_MINDESTENS:
        return f"Bitte mindestens {PASSWORT_MINDESTENS} Zeichen."
    # bcrypt liest nur die ersten 72 Byte; was darüber hinausgeht, zählte
    # nicht mit, und neuere Fassungen weisen es ab.
    if len(passwort.encode("utf-8")) > 72:
        return "Höchstens 72 Zeichen – Umlaute zählen doppelt."
    return ""


_attrappe: bytes | None = None


def _attrappe_pruefen(passwort: str) -> None:
    """Eine Prüfung gegen einen Hash, den es nicht gibt.

    Damit dauert die Anmeldung mit einer unbekannten Adresse so lange wie mit
    einer bekannten – sonst verriete die Antwortzeit, wer ein Konto hat.
    """
    global _attrappe
    if _attrappe is None:
        _attrappe = bcrypt.hashpw(secrets.token_bytes(16), bcrypt.gensalt())
    bcrypt.checkpw(passwort.encode("utf-8")[:72], _attrappe)


class Konten:
    """Zugriff aufs Schema kern. ``url`` liefert die Verbindungsangabe, wie
    bei den Bereichen – leer heißt: der Entwicklungs-Container."""

    def __init__(self, url: Callable[[], str]) -> None:
        self._db = Datenbank(url, "kern", Path(__file__).resolve().parent / "migrationen")

    def init(self) -> list[str]:
        return self._db.init()

    # --- Lesen ----------------------------------------------------------------

    def gibt_es_admin(self) -> bool:
        """Ob sich ein Admin mit eigenem Passwort anmelden kann. Erst dann ist
        das gemeinsame Passwort abgeschaltet – vorher sperrte es alle aus."""
        with self._db.transaktion() as con:
            return bool(con.execute(
                "SELECT EXISTS (SELECT 1 FROM konto WHERE rolle = 'admin'"
                " AND aktiv = 1 AND passwort_hash IS NOT NULL)").fetchone()[0])

    def liste(self) -> list[Zeile]:
        with self._db.transaktion() as con:
            return con.execute(
                "SELECT k.*, (k.passwort_hash IS NOT NULL) AS hat_passwort,"
                " (SELECT max(laeuft_ab_am) FROM einladung e WHERE e.konto_id = k.id"
                "   AND e.eingeloest_am IS NULL AND e.laeuft_ab_am > now()) AS link_bis"
                " FROM konto k ORDER BY k.aktiv DESC, lower(k.name)").fetchall()

    def laden(self, konto_id: int) -> Zeile | None:
        with self._db.transaktion() as con:
            return con.execute(
                "SELECT k.*, (k.passwort_hash IS NOT NULL) AS hat_passwort"
                " FROM konto k WHERE k.id = ?", (konto_id,)).fetchone()

    def nach_email(self, email: str) -> Zeile | None:
        with self._db.transaktion() as con:
            return con.execute("SELECT * FROM konto WHERE email = ?",
                               (email_normal(email),)).fetchone()

    # --- Anlegen und ändern ---------------------------------------------------

    def _werte(self, email, name, kuerzel, rolle, bereiche, telefon="") -> dict:
        werte = {
            "email": email_normal(email),
            "name": " ".join((name or "").split()),
            "kuerzel": (kuerzel or "").strip().upper(),
            "rolle": rolle,
            # Eine Bereichsleitung gibt es nur im Helferbereich.
            "bereiche": (["helfer"] if rolle == "bereichsleitung"
                         else [b for b in BEREICHE if b in (bereiche or ())]),
            "telefon": " ".join((telefon or "").split())[:40],
        }
        if not _EMAIL.match(werte["email"]):
            raise Fehler("Bitte eine gültige Mailadresse angeben.")
        if not werte["name"]:
            raise Fehler("Bitte einen Namen angeben.")
        if not _KUERZEL.match(werte["kuerzel"]):
            raise Fehler("Das Kürzel besteht aus 1 bis 10 Buchstaben oder Ziffern, z. B. KK.")
        if rolle not in ROLLEN:
            raise Fehler("Unbekannte Rolle.")
        if rolle != "admin" and not werte["bereiche"]:
            raise Fehler("Bitte mindestens einen Bereich wählen – sonst sieht das Konto nichts.")
        return werte

    @staticmethod
    def _doppelt(con, werte, ohne_id) -> None:
        for spalte, text in (("email", "Diese Mailadresse"), ("kuerzel", "Dieses Kürzel")):
            gibt_es = con.execute(
                f"SELECT 1 FROM konto WHERE {spalte} = ? AND id <> ?",
                (werte[spalte], ohne_id or 0)).fetchone()
            if gibt_es:
                raise Fehler(f"{text} hat schon ein anderes Konto.")

    def anlegen(self, *, email: str, name: str, kuerzel: str, rolle: str,
                bereiche=(), telefon: str = "", von: str = "",
                passwort: str | None = None) -> int:
        werte = self._werte(email, name, kuerzel, rolle, bereiche, telefon)
        passwort_hash = None
        if passwort is not None:
            grund = passwort_regeln(passwort)
            if grund:
                raise Fehler(grund)
            passwort_hash = bcrypt.hashpw(passwort.encode("utf-8"), bcrypt.gensalt()).decode()
        try:
            with self._db.transaktion() as con:
                self._doppelt(con, werte, None)
                return int(con.execute(
                    "INSERT INTO konto (email, name, kuerzel, rolle, bereiche, telefon,"
                    " passwort_hash, angelegt_von) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
                    " RETURNING id",
                    (werte["email"], werte["name"], werte["kuerzel"], werte["rolle"],
                     werte["bereiche"], werte["telefon"], passwort_hash,
                     von)).fetchone()[0])
        except IntegrityError:
            # Zwei gleichzeitig angelegt - die Prüfung oben sah beide nicht.
            raise Fehler("Mailadresse oder Kürzel hat schon ein anderes Konto.")

    def _letzter_admin(self, con, konto_id: int) -> bool:
        """Ob dieses Konto der einzige Admin ist, der sich anmelden kann."""
        return not con.execute(
            "SELECT EXISTS (SELECT 1 FROM konto WHERE rolle = 'admin' AND aktiv = 1"
            " AND passwort_hash IS NOT NULL AND id <> ?)", (konto_id,)).fetchone()[0]

    def aendern(self, konto_id: int, *, email: str, name: str, kuerzel: str,
                rolle: str, bereiche=(), telefon: str = "", aktiv: bool = True) -> None:
        werte = self._werte(email, name, kuerzel, rolle, bereiche, telefon)
        try:
            with self._db.transaktion() as con:
                alt = con.execute("SELECT * FROM konto WHERE id = ? FOR UPDATE",
                                  (konto_id,)).fetchone()
                if alt is None:
                    raise Fehler("Dieses Konto gibt es nicht mehr.")
                self._doppelt(con, werte, konto_id)
                war_admin = (alt["rolle"] == "admin" and alt["aktiv"]
                             and alt["passwort_hash"] is not None)
                bleibt_admin = rolle == "admin" and aktiv
                if war_admin and not bleibt_admin and self._letzter_admin(con, konto_id):
                    raise Fehler("Das ist das letzte Admin-Konto. Erst ein anderes "
                                 "zum Admin machen – sonst kommt niemand mehr an die Konten.")
                con.execute(
                    "UPDATE konto SET email = ?, name = ?, kuerzel = ?, rolle = ?,"
                    " bereiche = ?, telefon = ?, aktiv = ?, geaendert_am = now()"
                    " WHERE id = ?",
                    (werte["email"], werte["name"], werte["kuerzel"], werte["rolle"],
                     werte["bereiche"], werte["telefon"], 1 if aktiv else 0, konto_id))
                if not aktiv:
                    # Gesperrt heißt: sofort draußen, nicht erst, wenn der
                    # Keks abläuft.
                    con.execute("DELETE FROM sitzung WHERE konto_id = ?", (konto_id,))
                    con.execute("UPDATE einladung SET eingeloest_am = now()"
                                " WHERE konto_id = ? AND eingeloest_am IS NULL", (konto_id,))
        except IntegrityError:
            raise Fehler("Mailadresse oder Kürzel hat schon ein anderes Konto.")

    # --- Anmelden -------------------------------------------------------------

    def anmelden(self, email: str, passwort: str) -> Zeile | None:
        konto = self.nach_email(email)
        if konto is None or not konto["aktiv"] or not konto["passwort_hash"]:
            _attrappe_pruefen(passwort)
            return None
        try:
            richtig = bcrypt.checkpw(passwort.encode("utf-8"),
                                     konto["passwort_hash"].encode("ascii"))
        except ValueError:
            # Über 72 Byte oder ein Nullbyte - so ein Passwort gibt es nicht.
            richtig = False
        if not richtig:
            return None
        with self._db.transaktion() as con:
            con.execute("UPDATE konto SET zuletzt_angemeldet_am = now() WHERE id = ?",
                        (konto["id"],))
        return konto

    def telefon_setzen(self, konto_id: int, telefon: str) -> None:
        """Die eigene Nummer – jeder pflegt sie selbst unter Mein Konto."""
        with self._db.transaktion() as con:
            con.execute("UPDATE konto SET telefon = ?, geaendert_am = now() WHERE id = ?",
                        (" ".join((telefon or "").split())[:40], konto_id))

    def passwort_setzen(self, konto_id: int, passwort: str,
                        ausser_sitzung: str | None = None) -> None:
        """Setzt ein neues Passwort und beendet alle anderen Sitzungen."""
        grund = passwort_regeln(passwort)
        if grund:
            raise Fehler(grund)
        neu = bcrypt.hashpw(passwort.encode("utf-8"), bcrypt.gensalt()).decode()
        with self._db.transaktion() as con:
            con.execute("UPDATE konto SET passwort_hash = ?, geaendert_am = now()"
                        " WHERE id = ?", (neu, konto_id))
            con.execute("DELETE FROM sitzung WHERE konto_id = ? AND token_hash <> ?",
                        (konto_id, _hash(ausser_sitzung) if ausser_sitzung else ""))
            con.execute("UPDATE einladung SET eingeloest_am = now()"
                        " WHERE konto_id = ? AND eingeloest_am IS NULL", (konto_id,))

    def passwort_stimmt(self, konto_id: int, passwort: str) -> bool:
        konto = self.laden(konto_id)
        if konto is None or not konto["passwort_hash"]:
            return False
        try:
            return bcrypt.checkpw(passwort.encode("utf-8"),
                                  konto["passwort_hash"].encode("ascii"))
        except ValueError:
            return False

    # --- Sitzungen ------------------------------------------------------------

    def sitzung_anlegen(self, konto_id: int, dauer: timedelta) -> str:
        token = secrets.token_urlsafe(32)
        with self._db.transaktion() as con:
            # Bei der Gelegenheit die abgelaufenen wegräumen. Ein eigener
            # Aufräumlauf lohnt bei einer Handvoll Konten nicht.
            con.execute("DELETE FROM sitzung WHERE laeuft_ab_am < now()")
            con.execute("INSERT INTO sitzung (token_hash, konto_id, laeuft_ab_am)"
                        " VALUES (?, ?, now() + ?)", (_hash(token), konto_id, dauer))
        return token

    def sitzung_lesen(self, token: str) -> Zeile | None:
        """Das Konto zur Sitzung – nur, solange beide gültig sind."""
        if not token:
            return None
        with self._db.transaktion() as con:
            return con.execute(
                "SELECT k.*, s.laeuft_ab_am AS sitzung_bis FROM sitzung s"
                " JOIN konto k ON k.id = s.konto_id"
                " WHERE s.token_hash = ? AND s.laeuft_ab_am > now()"
                "   AND k.aktiv = 1 AND k.passwort_hash IS NOT NULL",
                (_hash(token),)).fetchone()

    def sitzung_beenden(self, token: str) -> None:
        with self._db.transaktion() as con:
            con.execute("DELETE FROM sitzung WHERE token_hash = ?", (_hash(token),))

    def sitzungen_beenden(self, konto_id: int) -> int:
        with self._db.transaktion() as con:
            return con.execute("DELETE FROM sitzung WHERE konto_id = ?",
                               (konto_id,)).rowcount

    # --- Links zum Setzen des Passworts -----------------------------------------

    def link_anlegen(self, konto_id: int, zweck: str) -> str:
        """Ein neuer Link macht ältere desselben Kontos ungültig – es gilt
        immer nur der zuletzt verschickte."""
        if zweck not in ("einladung", "zuruecksetzen"):
            raise ValueError(zweck)
        dauer = EINLADUNG_GILT if zweck == "einladung" else ZURUECKSETZEN_GILT
        token = secrets.token_urlsafe(32)
        with self._db.transaktion() as con:
            con.execute("UPDATE einladung SET eingeloest_am = now()"
                        " WHERE konto_id = ? AND eingeloest_am IS NULL", (konto_id,))
            con.execute("INSERT INTO einladung (token_hash, konto_id, zweck, laeuft_ab_am)"
                        " VALUES (?, ?, ?, now() + ?)", (_hash(token), konto_id, zweck, dauer))
        return token

    def link_lesen(self, token: str) -> Zeile | None:
        if not token:
            return None
        with self._db.transaktion() as con:
            return con.execute(
                "SELECT k.*, e.zweck FROM einladung e JOIN konto k ON k.id = e.konto_id"
                " WHERE e.token_hash = ? AND e.eingeloest_am IS NULL"
                "   AND e.laeuft_ab_am > now() AND k.aktiv = 1",
                (_hash(token),)).fetchone()

    def link_einloesen(self, token: str, passwort: str) -> Zeile | None:
        """Setzt das Passwort über den Link. Gibt das Konto zurück, oder None,
        wenn der Link nicht (mehr) gilt. Wirft Fehler bei einem untauglichen
        Passwort – dann bleibt der Link gültig."""
        grund = passwort_regeln(passwort)
        if grund:
            raise Fehler(grund)
        neu = bcrypt.hashpw(passwort.encode("utf-8"), bcrypt.gensalt()).decode()
        with self._db.transaktion() as con:
            # FOR UPDATE: zweimal abgeschickt löst nur einer ein.
            zeile = con.execute(
                "SELECT e.konto_id FROM einladung e JOIN konto k ON k.id = e.konto_id"
                " WHERE e.token_hash = ? AND e.eingeloest_am IS NULL"
                "   AND e.laeuft_ab_am > now() AND k.aktiv = 1 FOR UPDATE OF e",
                (_hash(token),)).fetchone()
            if zeile is None:
                return None
            konto_id = zeile["konto_id"]
            con.execute("UPDATE konto SET passwort_hash = ?, geaendert_am = now()"
                        " WHERE id = ?", (neu, konto_id))
            con.execute("UPDATE einladung SET eingeloest_am = now()"
                        " WHERE konto_id = ? AND eingeloest_am IS NULL", (konto_id,))
            con.execute("DELETE FROM sitzung WHERE konto_id = ?", (konto_id,))
            return con.execute("SELECT * FROM konto WHERE id = ?", (konto_id,)).fetchone()
