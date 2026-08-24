"""Konfiguration – ausschließlich über Env-Variablen (siehe .env.example).

Dritte App im Repo, nach Kennzeichen und Presse. Betriebs- und Anmeldewerte
tragen bewusst dieselben Namen wie dort, damit Deployment und Betrieb sich
gleich anfühlen. Mailversand gibt es hier nicht.
"""

from __future__ import annotations

import os
import re
from datetime import date, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(pfad: Path) -> None:
    """Minimaler .env-Loader für die lokale Entwicklung. Im Betrieb setzt
    systemd die Variablen selbst; bereits gesetzte gewinnen."""
    if not pfad.exists():
        return
    for zeile in pfad.read_text(encoding="utf-8").splitlines():
        zeile = zeile.strip()
        if not zeile or zeile.startswith("#") or "=" not in zeile:
            continue
        name, _, wert = zeile.partition("=")
        os.environ.setdefault(name.strip(), wert.strip().strip('"').strip("'"))


_load_dotenv(BASE_DIR / ".env")


def _flag(name: str, default: str = "1") -> bool:
    return os.environ.get(name, default).strip().lower() not in ("0", "false", "nein", "")


def _zahl(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)).strip())
    except ValueError:
        return default


# --- Betrieb ---------------------------------------------------------------

BIND = os.environ.get("BIND", "127.0.0.1:8082")

# Von welchen Adressen X-Forwarded-For und X-Forwarded-Proto geglaubt werden.
# Liegt der Reverse Proxy auf einem anderen Host, MUSS hier dessen IP stehen.
FORWARDED_ALLOW_IPS = os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1").strip()

DB_PATH = Path(os.environ.get("DB_PATH", str(BASE_DIR / "data" / "helfer.db")))
if not DB_PATH.is_absolute():
    DB_PATH = BASE_DIR / DB_PATH

BASIS_PFAD = "/" + os.environ.get("BASIS_PFAD", "/").strip("/")

# Öffentliche Adresse, z. B. https://helfer.example.de. Wird für den
# Monitor-Link gebraucht; leer heißt: aus der Anfrage ableiten.
BASIS_URL = os.environ.get("BASIS_URL", "").strip().rstrip("/")


def bind_adresse() -> tuple[str, int]:
    """'127.0.0.1:8082' -> ('127.0.0.1', 8082). Auch '[::1]:8082' geht."""
    rest, _, hafen = BIND.rpartition(":")
    if not rest:
        return "127.0.0.1", int(hafen or 8082)
    return rest.strip("[]") or "127.0.0.1", int(hafen or 8082)


def nur_localhost() -> bool:
    return bind_adresse()[0] in ("127.0.0.1", "::1", "localhost")


# --- Veranstaltung ---------------------------------------------------------

VERANSTALTUNG = os.environ.get("VERANSTALTUNG", "Die absolute Abfahrt")
ORT = os.environ.get("ORT", "Ilmenau")

# Die drei Renntage. Der Zeitplan-Abruf braucht sie, um Wochentage ("Freitag")
# auf Daten abzubilden; Auf- und Abbauschichten liegen davor und danach.
TAGE_ROH = os.environ.get("TAGE", "2026-08-28,2026-08-29,2026-08-30")


def _tage() -> list[date]:
    ergebnis = []
    for teil in TAGE_ROH.split(","):
        teil = teil.strip()
        if not teil:
            continue
        try:
            ergebnis.append(date.fromisoformat(teil))
        except ValueError:
            continue
    return sorted(set(ergebnis))


TAGE = _tage() or [date(2026, 8, 28), date(2026, 8, 29), date(2026, 8, 30)]

WOCHENTAGE = ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag",
              "Samstag", "Sonntag")


def tag_zu_datum(wochentag: str) -> date | None:
    """'Samstag' -> das Datum des Renntags. Nur innerhalb von TAGE; kommt ein
    Wochentag zweimal vor, ist die Zuordnung mehrdeutig und wir geben nichts
    zurück, statt zu raten."""
    name = wochentag.strip().casefold()
    treffer = [t for t in TAGE if WOCHENTAGE[t.weekday()].casefold() == name]
    return treffer[0] if len(treffer) == 1 else None


# --- Monitor ---------------------------------------------------------------

# Wie oft die Monitoransicht neu lädt (Sekunden).
MONITOR_INTERVALL = _zahl("MONITOR_INTERVALL", 60)

# Wie weit die Monitoransicht nach vorn schaut (Minuten). Was jetzt läuft und
# was in diesem Fenster beginnt, steht oben.
MONITOR_VORSCHAU = _zahl("MONITOR_VORSCHAU", 120)

# Ab wie vielen fehlenden Helfern eine Schicht auf dem Monitor als kritisch
# gilt. 0 schaltet die Hervorhebung ab.
MONITOR_WARNUNG = _zahl("MONITOR_WARNUNG", 1)

# Feste Zeitzone – der Monitor steht in Ilmenau, egal wo der Server läuft.
ZEITZONE = os.environ.get("ZEITZONE", "Europe/Berlin").strip() or "Europe/Berlin"

# Erlaubt, die Uhr für Durchsichten zu verstellen: ISO-Zeitpunkt statt "jetzt".
# Leer heißt: echte Uhr. Im Betrieb bleibt das leer.
JETZT_FEST = os.environ.get("JETZT_FEST", "").strip()


# --- Ansprechpartner -------------------------------------------------------

KONTAKT_NAME = os.environ.get("KONTAKT_NAME", "Orga-Team Absolute Abfahrt")
KONTAKT_MAIL = os.environ.get("KONTAKT_MAIL", "")
KONTAKT_TELEFON = os.environ.get("KONTAKT_TELEFON", "")

# --- Backoffice / Anmeldung ------------------------------------------------

import secrets as _secrets  # noqa: E402  (bewusst erst hier, nur für den Fallback)

ADMIN_PASSWORD_HASH = os.environ.get("ADMIN_PASSWORD_HASH", "").strip()

APP_SECRET_KEY = os.environ.get("APP_SECRET_KEY", "").strip()
SECRET_KEY_FLUECHTIG = not APP_SECRET_KEY
if SECRET_KEY_FLUECHTIG:
    APP_SECRET_KEY = _secrets.token_urlsafe(32)

SESSION_STUNDEN = _zahl("SESSION_STUNDEN", 12)
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "auto").strip().lower()
LOGIN_VERSUCHE = _zahl("LOGIN_VERSUCHE", 5)
LOGIN_FENSTER_SEKUNDEN = _zahl("LOGIN_FENSTER_SEKUNDEN", 60)

KUERZEL_ABFRAGEN = _flag("KUERZEL_ABFRAGEN")

# --- Sonstiges -------------------------------------------------------------

CSV_TRENNER = os.environ.get("CSV_TRENNER", ";")[:1] or ";"

LOGO_DATEI = os.environ.get("LOGO_DATEI", "").strip()
if LOGO_DATEI and ("/" in LOGO_DATEI or "\\" in LOGO_DATEI):
    LOGO_DATEI = ""


def pfad(*teile: str) -> str:
    """Baut eine URL unterhalb von BASIS_PFAD, ohne doppelte Schrägstriche."""
    basis = "" if BASIS_PFAD == "/" else BASIS_PFAD
    return basis + "/" + "/".join(t.strip("/") for t in teile if t) if teile else BASIS_PFAD
