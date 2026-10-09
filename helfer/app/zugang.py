"""Persönliche Links ohne Passwort (Lastenheft 7.4).

Ein Link ist ``<id>.<siegel>``: die Person und ein HMAC über Person, Zweck
und ``zugang_version`` mit dem Schlüssel der App. Gespeichert wird davon
nichts – jede Mail kann denselben Link enthalten, „Link anfordern“ schickt
ihn einfach noch einmal, und eine Kopie der Datenbank verrät keinen.
Zählt man ``zugang_version`` hoch, gilt keiner der alten mehr; wechselt
APP_SECRET_KEY, ebenso.

Drei Zwecke, damit ein Link nicht mehr kann, als er soll: Mein Helferplatz,
das Bestätigen der Adresse (gebunden an genau diese Adresse) und das
Kalender-Abo, das ein Kalenderprogramm jahrelang abfragt und deshalb nur
lesen darf.
"""

from __future__ import annotations

import hashlib
import hmac

from . import config

PLATZ = "platz"
BESTAETIGEN = "bestaetigen"
KALENDER = "kalender"

# Ab so vielen falschen Codes gilt nur noch der Link aus der Mail.
CODE_VERSUCHE = 5


def _siegel(*teile) -> str:
    nachricht = "|".join(str(t) for t in teile).encode("utf-8")
    return hmac.new(config.APP_SECRET_KEY.encode("utf-8"), nachricht,
                    hashlib.sha256).hexdigest()


def _bindung(zweck: str, person) -> tuple:
    # Der Bestätigungslink gilt nur für die Adresse, an die er ging.
    extra = person["email"] if zweck == BESTAETIGEN else ""
    return (zweck, person["id"], person["zugang_version"], extra)


def token(zweck: str, person) -> str:
    return f"{person['id']}.{_siegel(*_bindung(zweck, person))[:32]}"


def nummer(roh: str) -> int | None:
    """Die Person aus einem Link – geprüft wird danach mit ``stimmt``."""
    kopf, punkt, _ = (roh or "").partition(".")
    return int(kopf) if punkt and kopf.isdigit() else None


def stimmt(zweck: str, roh: str, person) -> bool:
    return hmac.compare_digest(token(zweck, person), roh or "")


def code(person) -> str:
    """Der sechsstellige Code für die, deren Mail auf dem PC ankommt, während
    die Anmeldung auf dem Handy läuft."""
    zahl = int(_siegel("code", *_bindung(BESTAETIGEN, person))[:12], 16)
    return f"{zahl % 1_000_000:06d}"


def code_stimmt(person, eingabe: str) -> bool:
    ziffern = "".join(z for z in (eingabe or "") if z.isdigit())
    return hmac.compare_digest(code(person), ziffern)
