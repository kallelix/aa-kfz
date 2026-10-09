"""Veranstaltungen (Lastenheft V-01, V-02).

Eine Veranstaltung hat Name, Kurzname, Tage, Ort, Beschreibung, einen
Anmeldezeitraum und einen Status. Die Bereiche hängen ihre Daten daran – bis
jetzt der Helferbereich: Schichten, Programm, Aufgaben, Ausleihen, Schlüssel.

Mit welcher Veranstaltung jemand im Backoffice arbeitet, wählt er selbst;
gemerkt wird das im Browser. Ohne Wahl gilt die Vorgabe: die nächste, die
noch nicht vorbei ist.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Callable

from kern.db import Datenbank, IntegrityError, Zeile

STATUS = {
    "planung": "in Planung",
    "angekuendigt": "angekündigt",
    "offen": "Anmeldung offen",
    "geschlossen": "geschlossen",
    "archiviert": "archiviert",
}
STATUS_TEXT = {
    "planung": "nur im Backoffice zu sehen",
    "angekuendigt": "öffentlich zu sehen, Interesse lässt sich vormerken",
    "offen": "Helfer können sich anmelden",
    "geschlossen": "keine neuen Anmeldungen mehr",
    "archiviert": "vorbei; bleibt als Vorlage für die nächste",
}

# Wie der Browser sich die Wahl merkt.
KEKS = "abfahrt_veranstaltung"


class Fehler(ValueError):
    """Eine Eingabe, die nicht geht – mit einem Satz für den Menschen."""


def tage(veranstaltung) -> list[date]:
    """Die Tage der Veranstaltung, von beginn bis ende."""
    beginn, ende = veranstaltung["beginn"], veranstaltung["ende"]
    return [beginn + timedelta(days=i) for i in range((ende - beginn).days + 1)]


def _datum(roh, feld: str, pflicht: bool) -> date | None:
    if isinstance(roh, date):
        return roh
    roh = (roh or "").strip()
    if not roh:
        if pflicht:
            raise Fehler(f"Bitte {feld} angeben.")
        return None
    try:
        return date.fromisoformat(roh)
    except ValueError:
        raise Fehler(f"{feld[0].upper() + feld[1:]} ist kein Datum.")


class Veranstaltungen:
    def __init__(self, url: Callable[[], str]) -> None:
        self._db = Datenbank(url, "kern", Path(__file__).resolve().parent / "migrationen")

    def init(self) -> list[str]:
        return self._db.init()

    # --- Lesen ------------------------------------------------------------------

    def liste(self) -> list[Zeile]:
        """Neueste zuerst; archivierte ans Ende."""
        with self._db.transaktion() as con:
            return con.execute(
                "SELECT * FROM veranstaltung"
                " ORDER BY status = 'archiviert', beginn DESC").fetchall()

    def laden(self, veranstaltung_id) -> Zeile | None:
        try:
            nummer = int(veranstaltung_id)
        except (TypeError, ValueError):
            return None
        with self._db.transaktion() as con:
            return con.execute("SELECT * FROM veranstaltung WHERE id = ?",
                               (nummer,)).fetchone()

    def vorgabe(self, heute: date | None = None) -> Zeile | None:
        """Die Veranstaltung, mit der man ohne eigene Wahl arbeitet: die
        nächste, die noch nicht vorbei ist. Gibt es keine mehr, die zuletzt
        gewesene – archiviert oder nicht."""
        heute = heute or date.today()
        with self._db.transaktion() as con:
            return (con.execute(
                "SELECT * FROM veranstaltung WHERE ende >= ? AND status <> 'archiviert'"
                " ORDER BY beginn LIMIT 1", (heute,)).fetchone()
                or con.execute(
                    "SELECT * FROM veranstaltung ORDER BY ende DESC LIMIT 1").fetchone())

    def gewaehlt(self, roh, heute: date | None = None) -> Zeile | None:
        """Die im Browser gewählte, sonst die Vorgabe."""
        return self.laden(roh) or self.vorgabe(heute)

    # --- Anlegen, ändern, löschen ---------------------------------------------------

    def _werte(self, werte: dict) -> dict:
        sauber = {
            "name": " ".join(str(werte.get("name") or "").split()),
            "kurz": " ".join(str(werte.get("kurz") or "").split()),
            "ort": " ".join(str(werte.get("ort") or "").split()),
            "beschreibung": str(werte.get("beschreibung") or "").strip(),
            "status": str(werte.get("status") or "planung"),
            "beginn": _datum(werte.get("beginn"), "den ersten Tag", True),
            "ende": _datum(werte.get("ende"), "den letzten Tag", True),
            "anmeldung_ab": _datum(werte.get("anmeldung_ab"), "den Anmeldestart", False),
            "anmeldung_bis": _datum(werte.get("anmeldung_bis"), "das Anmeldeende", False),
        }
        if not sauber["name"]:
            raise Fehler("Bitte einen Namen angeben.")
        if not sauber["kurz"] or len(sauber["kurz"]) > 20:
            raise Fehler("Der Kurzname hat 1 bis 20 Zeichen, z. B. „AA 2027“.")
        if sauber["status"] not in STATUS:
            raise Fehler("Unbekannter Status.")
        if sauber["ende"] < sauber["beginn"]:
            raise Fehler("Der letzte Tag liegt vor dem ersten.")
        if (sauber["anmeldung_ab"] and sauber["anmeldung_bis"]
                and sauber["anmeldung_bis"] < sauber["anmeldung_ab"]):
            raise Fehler("Die Anmeldung endet, bevor sie beginnt.")
        return sauber

    def anlegen(self, werte: dict) -> int:
        w = self._werte(werte)
        try:
            with self._db.transaktion() as con:
                return int(con.execute(
                    "INSERT INTO veranstaltung (name, kurz, beginn, ende, ort, beschreibung,"
                    " status, anmeldung_ab, anmeldung_bis)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
                    (w["name"], w["kurz"], w["beginn"], w["ende"], w["ort"],
                     w["beschreibung"], w["status"], w["anmeldung_ab"],
                     w["anmeldung_bis"])).fetchone()[0])
        except IntegrityError:
            raise Fehler("Diesen Kurznamen hat schon eine andere Veranstaltung.")

    def aendern(self, veranstaltung_id: int, werte: dict) -> None:
        w = self._werte(werte)
        try:
            with self._db.transaktion() as con:
                geaendert = con.execute(
                    "UPDATE veranstaltung SET name = ?, kurz = ?, beginn = ?, ende = ?,"
                    " ort = ?, beschreibung = ?, status = ?, anmeldung_ab = ?,"
                    " anmeldung_bis = ?, geaendert_am = now() WHERE id = ?",
                    (w["name"], w["kurz"], w["beginn"], w["ende"], w["ort"],
                     w["beschreibung"], w["status"], w["anmeldung_ab"],
                     w["anmeldung_bis"], veranstaltung_id)).rowcount
        except IntegrityError:
            raise Fehler("Diesen Kurznamen hat schon eine andere Veranstaltung.")
        if not geaendert:
            raise Fehler("Diese Veranstaltung gibt es nicht mehr.")

    def loeschen(self, veranstaltung_id: int) -> None:
        """Nur, solange nichts daran hängt. Schichten, Aufgaben und der Rest
        zeigen mit einem Fremdschlüssel hierher; die Datenbank weist das
        Löschen dann ab, statt sie mitzunehmen."""
        try:
            with self._db.transaktion() as con:
                con.execute("DELETE FROM veranstaltung WHERE id = ?", (veranstaltung_id,))
        except IntegrityError:
            raise Fehler("An dieser Veranstaltung hängen schon Schichten, Aufgaben "
                         "oder Ausgaben. Archivieren statt löschen.")
