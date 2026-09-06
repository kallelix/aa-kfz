"""Anmeldung fürs Backoffice: gemeinsames Passwort, signiertes Session-Cookie.

Gemeinsam für alle Anwendungen im Repo. Vorher lag diese Datei dreimal Wort
für Wort gleich da; ausgerechnet die sicherheitskritische Schicht dreifach zu
pflegen hieß, jede Korrektur dreimal machen zu müssen – oder sie zweimal zu
vergessen.

Warum eine Klasse und kein Modul: die drei Anwendungen laufen jetzt in EINEM
Prozess und haben verschiedene Schlüssel, Passwörter und Sitzungsdauern. Ein
Modul hat davon nur einen Satz. Jede Anwendung hält sich deshalb eine eigene
Instanz – heißt sie ``auth``, bleibt jede Aufrufstelle so, wie sie war:
``auth.sitzung_erforderlich``, ``auth.Sitzung``, ``auth.csrf_pruefen``.

Absichtlich eine eigene Schicht: der Plan hält sich einen Magic Link offen.
Auszutauschen wäre dann nur ``passwort_pruefen`` und die Login-Route – Token,
Cookie und CSRF bleiben, wie sie sind.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass

import bcrypt
from fastapi import Request, Response


class NichtAngemeldet(Exception):
    """Löst die Umleitung zur Anmeldeseite aus (siehe Handler in main.py)."""

    def __init__(self, ziel: str = "/admin") -> None:
        self.ziel = ziel


class NichtEingerichtet(Exception):
    """ADMIN_PASSWORD_HASH fehlt – das Backoffice ist nicht benutzbar."""


@dataclass(frozen=True)
class Sitzung:
    kuerzel: str
    laeuft_ab: int
    token: str


def hash_erzeugen(klartext: str) -> str:
    """Ohne Konfiguration und deshalb hier: ``python -m kern.passwort`` ruft es."""
    return bcrypt.hashpw(klartext.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def _b64(rohdaten: bytes) -> str:
    return base64.urlsafe_b64encode(rohdaten).decode("ascii").rstrip("=")


def _entb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class Auth:
    """Alles, was am Schlüssel und am Passwort einer Anwendung hängt.

    ``config`` ist das Konfigurationsmodul der jeweiligen Anwendung. Gelesen
    werden ADMIN_PASSWORD_HASH, APP_SECRET_KEY, SESSION_STUNDEN,
    COOKIE_SECURE, LOGIN_VERSUCHE und LOGIN_FENSTER_SEKUNDEN.
    """

    # Damit auth.Sitzung und auth.NichtAngemeldet weiter am Objekt hängen und
    # keine Aufrufstelle etwas davon merkt.
    Sitzung = Sitzung
    NichtAngemeldet = NichtAngemeldet
    NichtEingerichtet = NichtEingerichtet
    hash_erzeugen = staticmethod(hash_erzeugen)

    def __init__(self, config, cookie_name: str | None = None,
                 cookie_pfad: str = "/admin") -> None:
        self.config = config
        # Je Anwendung ein eigener Name waere noetig, sobald sie sich eine
        # Adresse teilen - bei getrennten Hostnamen trennt der Browser die
        # Kekse schon selbst.
        self.COOKIE_NAME = cookie_name or getattr(
            config, "COOKIE_NAME", "abfahrt_sitzung")
        self.COOKIE_PFAD = cookie_pfad
        # Im Speicher, je Anwendung eigen.
        self._fehlversuche: dict[str, list[float]] = {}

    # --- Passwort -----------------------------------------------------------

    def eingerichtet(self) -> bool:
        return bool(self.config.ADMIN_PASSWORD_HASH)

    def passwort_pruefen(self, klartext: str) -> bool:
        if not self.eingerichtet():
            return False
        try:
            return bcrypt.checkpw(
                klartext.encode("utf-8"),
                self.config.ADMIN_PASSWORD_HASH.encode("utf-8"),
            )
        except ValueError:
            # Unbrauchbarer Hash in der Env oder Nullbyte im Passwort.
            return False

    # --- Token --------------------------------------------------------------

    def _signieren(self, nutzlast: str) -> str:
        signatur = hmac.new(
            self.config.APP_SECRET_KEY.encode("utf-8"),
            nutzlast.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        return _b64(signatur)

    def token_erzeugen(self, kuerzel: str) -> str:
        daten = {
            "k": kuerzel,
            "exp": int(time.time()) + self.config.SESSION_STUNDEN * 3600,
        }
        nutzlast = _b64(json.dumps(daten, separators=(",", ":")).encode("utf-8"))
        return f"{nutzlast}.{self._signieren(nutzlast)}"

    def token_pruefen(self, token: str | None) -> Sitzung | None:
        if not token or token.count(".") != 1:
            return None
        nutzlast, signatur = token.split(".")
        if not hmac.compare_digest(self._signieren(nutzlast), signatur):
            return None
        try:
            daten = json.loads(_entb64(nutzlast))
            laeuft_ab = int(daten["exp"])
        except (ValueError, KeyError, TypeError):
            return None
        if laeuft_ab <= int(time.time()):
            return None
        return Sitzung(kuerzel=str(daten.get("k", "")), laeuft_ab=laeuft_ab,
                       token=token)

    # --- CSRF ---------------------------------------------------------------

    def csrf_token(self, sitzungstoken: str) -> str:
        """An die Sitzung gebunden – ohne gültiges Cookie ist er wertlos."""
        return self._signieren("csrf:" + sitzungstoken)

    def csrf_pruefen(self, sitzung: Sitzung, uebermittelt: str | None) -> bool:
        return hmac.compare_digest(self.csrf_token(sitzung.token),
                                   uebermittelt or "")

    # --- Cookie -------------------------------------------------------------

    def _secure(self, request: Request) -> bool:
        if self.config.COOKIE_SECURE in ("1", "true", "ja"):
            return True
        if self.config.COOKIE_SECURE in ("0", "false", "nein"):
            return False
        # auto: der Proxy meldet über X-Forwarded-Proto, was der Browser sieht.
        return request.url.scheme == "https"

    def cookie_setzen(self, antwort: Response, request: Request,
                      token: str) -> None:
        antwort.set_cookie(
            self.COOKIE_NAME,
            token,
            max_age=self.config.SESSION_STUNDEN * 3600,
            httponly=True,
            samesite="lax",
            secure=self._secure(request),
            path=self.COOKIE_PFAD,
        )

    def cookie_loeschen(self, antwort: Response) -> None:
        antwort.delete_cookie(self.COOKIE_NAME, path=self.COOKIE_PFAD)

    # --- Zugriffsschutz -----------------------------------------------------

    def sitzung_lesen(self, request: Request) -> Sitzung | None:
        return self.token_pruefen(request.cookies.get(self.COOKIE_NAME))

    def sitzung_erforderlich(self, request: Request) -> Sitzung:
        if not self.eingerichtet():
            raise NichtEingerichtet()
        sitzung = self.sitzung_lesen(request)
        if sitzung is None:
            ziel = request.url.path
            if request.url.query:
                ziel = f"{ziel}?{request.url.query}"
            raise NichtAngemeldet(ziel)
        return sitzung

    # --- Rate Limit für den Login ------------------------------------------

    def _aufraeumen(self, ip: str, jetzt: float) -> list[float]:
        grenze = jetzt - self.config.LOGIN_FENSTER_SEKUNDEN
        uebrig = [t for t in self._fehlversuche.get(ip, []) if t > grenze]
        if uebrig:
            self._fehlversuche[ip] = uebrig
        else:
            self._fehlversuche.pop(ip, None)
        return uebrig

    def login_gesperrt(self, ip: str) -> bool:
        """Zählt nur Fehlversuche. Im Speicher, pro Prozess – reicht hier."""
        return (len(self._aufraeumen(ip, time.monotonic()))
                >= self.config.LOGIN_VERSUCHE)

    def login_fehlversuch(self, ip: str) -> None:
        jetzt = time.monotonic()
        self._aufraeumen(ip, jetzt)
        self._fehlversuche.setdefault(ip, []).append(jetzt)

    def login_zuruecksetzen(self, ip: str) -> None:
        self._fehlversuche.pop(ip, None)
