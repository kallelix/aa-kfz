"""Anmeldung fürs Backoffice: gemeinsames Passwort, signiertes Session-Cookie.

Absichtlich als eigene Schicht: der Plan hält sich einen Magic Link offen.
Auszutauschen wäre dann nur `passwort_pruefen` und die Login-Route – Token,
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

from . import config

COOKIE_NAME = "abfahrt_sitzung"
COOKIE_PFAD = "/admin"


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


# --- Passwort ---------------------------------------------------------------


def hash_erzeugen(klartext: str) -> str:
    return bcrypt.hashpw(klartext.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def eingerichtet() -> bool:
    return bool(config.ADMIN_PASSWORD_HASH)


def passwort_pruefen(klartext: str) -> bool:
    if not eingerichtet():
        return False
    try:
        return bcrypt.checkpw(
            klartext.encode("utf-8"), config.ADMIN_PASSWORD_HASH.encode("utf-8")
        )
    except ValueError:
        # Unbrauchbarer Hash in der Env oder Nullbyte im Passwort.
        return False


# --- Token ------------------------------------------------------------------


def _b64(rohdaten: bytes) -> str:
    return base64.urlsafe_b64encode(rohdaten).decode("ascii").rstrip("=")


def _entb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _signieren(nutzlast: str) -> str:
    signatur = hmac.new(
        config.APP_SECRET_KEY.encode("utf-8"), nutzlast.encode("utf-8"), hashlib.sha256
    ).digest()
    return _b64(signatur)


def token_erzeugen(kuerzel: str) -> str:
    daten = {
        "k": kuerzel,
        "exp": int(time.time()) + config.SESSION_STUNDEN * 3600,
    }
    nutzlast = _b64(json.dumps(daten, separators=(",", ":")).encode("utf-8"))
    return f"{nutzlast}.{_signieren(nutzlast)}"


def token_pruefen(token: str | None) -> Sitzung | None:
    if not token or token.count(".") != 1:
        return None
    nutzlast, signatur = token.split(".")
    if not hmac.compare_digest(_signieren(nutzlast), signatur):
        return None
    try:
        daten = json.loads(_entb64(nutzlast))
        laeuft_ab = int(daten["exp"])
    except (ValueError, KeyError, TypeError):
        return None
    if laeuft_ab <= int(time.time()):
        return None
    return Sitzung(kuerzel=str(daten.get("k", "")), laeuft_ab=laeuft_ab, token=token)


# --- CSRF -------------------------------------------------------------------


def csrf_token(sitzungstoken: str) -> str:
    """An die Sitzung gebunden – ohne gültiges Cookie ist er wertlos."""
    return _signieren("csrf:" + sitzungstoken)


def csrf_pruefen(sitzung: Sitzung, uebermittelt: str | None) -> bool:
    return hmac.compare_digest(csrf_token(sitzung.token), uebermittelt or "")


# --- Cookie -----------------------------------------------------------------


def _secure(request: Request) -> bool:
    if config.COOKIE_SECURE in ("1", "true", "ja"):
        return True
    if config.COOKIE_SECURE in ("0", "false", "nein"):
        return False
    # auto: der Proxy meldet über X-Forwarded-Proto, was der Browser sieht.
    return request.url.scheme == "https"


def cookie_setzen(antwort: Response, request: Request, token: str) -> None:
    antwort.set_cookie(
        COOKIE_NAME,
        token,
        max_age=config.SESSION_STUNDEN * 3600,
        httponly=True,
        samesite="lax",
        secure=_secure(request),
        path=COOKIE_PFAD,
    )


def cookie_loeschen(antwort: Response) -> None:
    antwort.delete_cookie(COOKIE_NAME, path=COOKIE_PFAD)


# --- Zugriffsschutz ---------------------------------------------------------


def sitzung_lesen(request: Request) -> Sitzung | None:
    return token_pruefen(request.cookies.get(COOKIE_NAME))


def sitzung_erforderlich(request: Request) -> Sitzung:
    if not eingerichtet():
        raise NichtEingerichtet()
    sitzung = sitzung_lesen(request)
    if sitzung is None:
        ziel = request.url.path
        if request.url.query:
            ziel = f"{ziel}?{request.url.query}"
        raise NichtAngemeldet(ziel)
    return sitzung


# --- Rate Limit für den Login ----------------------------------------------

_fehlversuche: dict[str, list[float]] = {}


def _aufraeumen(ip: str, jetzt: float) -> list[float]:
    grenze = jetzt - config.LOGIN_FENSTER_SEKUNDEN
    uebrig = [t for t in _fehlversuche.get(ip, []) if t > grenze]
    if uebrig:
        _fehlversuche[ip] = uebrig
    else:
        _fehlversuche.pop(ip, None)
    return uebrig


def login_gesperrt(ip: str) -> bool:
    """Zählt nur Fehlversuche. Im Speicher, pro Prozess – reicht hier."""
    return len(_aufraeumen(ip, time.monotonic())) >= config.LOGIN_VERSUCHE


def login_fehlversuch(ip: str) -> None:
    jetzt = time.monotonic()
    _aufraeumen(ip, jetzt)
    _fehlversuche.setdefault(ip, []).append(jetzt)


def login_zuruecksetzen(ip: str) -> None:
    _fehlversuche.pop(ip, None)
