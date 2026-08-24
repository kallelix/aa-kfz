"""Konfiguration – ausschließlich über Env-Variablen (siehe .env.example).

Schwesteranwendung zur Kennzeichen-App: Betriebs-, Anmelde- und Mailwerte
tragen bewusst dieselben Namen, damit Deployment und Betrieb sich gleich
anfühlen. Fachlich ist alles andere.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(pfad: Path) -> None:
    """Minimaler .env-Loader für die lokale Entwicklung. Im Betrieb setzt
    systemd bzw. Docker die Variablen selbst; bereits gesetzte gewinnen."""
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


# --- Betrieb ---------------------------------------------------------------

BIND = os.environ.get("BIND", "127.0.0.1:8081")

# Von welchen Adressen X-Forwarded-For und X-Forwarded-Proto geglaubt werden.
# Liegt der Reverse Proxy auf einem anderen Host, MUSS hier dessen IP stehen.
FORWARDED_ALLOW_IPS = os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1").strip()

DB_PATH = Path(os.environ.get("DB_PATH", str(BASE_DIR / "data" / "presse.db")))
if not DB_PATH.is_absolute():
    DB_PATH = BASE_DIR / DB_PATH

FORM_PATH = "/" + os.environ.get("FORM_PATH", "/").strip("/")

# Öffentliche Adresse der Anwendung, z. B. https://presse.example.de. Wird für
# absolute Verweise gebraucht; leer heißt: aus der Anfrage ableiten.
BASIS_URL = os.environ.get("BASIS_URL", "").strip().rstrip("/")


def bind_adresse() -> tuple[str, int]:
    """'127.0.0.1:8081' -> ('127.0.0.1', 8081). Auch '[::1]:8081' geht."""
    rest, _, hafen = BIND.rpartition(":")
    if not rest:
        return "127.0.0.1", int(hafen or 8081)
    return rest.strip("[]") or "127.0.0.1", int(hafen or 8081)


def nur_localhost() -> bool:
    return bind_adresse()[0] in ("127.0.0.1", "::1", "localhost")


# --- Fachlich --------------------------------------------------------------

VERANSTALTUNG = os.environ.get("VERANSTALTUNG", "Die absolute Abfahrt")
ORT = os.environ.get("ORT", "Ilmenau")

# Akkreditierungsgebühr für kommerzielle Nutzung.
GEBUEHR_BETRAG = os.environ.get("GEBUEHR_BETRAG", "20").strip()
GEBUEHR_WAEHRUNG = os.environ.get("GEBUEHR_WAEHRUNG", "EUR").strip()

# Umfang der Bilderspende als Alternative zur Gebühr.
BILDER_ANZAHL = os.environ.get("BILDER_ANZAHL", "10").strip()

# Wohin die gespendeten Bilder sollen. Steht in der Erinnerungsmail; solange
# leer, bleibt der Text dort allgemein.
BILDER_ABGABE = os.environ.get("BILDER_ABGABE", "").strip()

ABHOLORT = os.environ.get("ABHOLORT", "Orga-Büro")

# Die Badges sind vorproduziert, also endlich. 0 heißt: keine Obergrenze und
# keine Warnung. Abgeriegelt wird nicht – siehe Plan, Abschnitt 9.
try:
    BADGES_GESAMT = int(os.environ.get("BADGES_GESAMT", "0"))
except ValueError:
    BADGES_GESAMT = 0


def gebuehr() -> str:
    """'20 EUR' – so, wie es im Formular und in der Mail steht."""
    return f"{GEBUEHR_BETRAG} {GEBUEHR_WAEHRUNG}".strip()


# --- Ansprechpartner -------------------------------------------------------

KONTAKT_NAME = os.environ.get("KONTAKT_NAME", "Orga-Team Absolute Abfahrt")
KONTAKT_MAIL = os.environ.get("KONTAKT_MAIL", "")
KONTAKT_TELEFON = os.environ.get("KONTAKT_TELEFON", "")

# --- Datenschutz -----------------------------------------------------------

IP_SPEICHERN = _flag("IP_SPEICHERN")

# Kein AUFBEWAHRUNG_HINWEIS wie in der Kennzeichen-App: dort werden die Daten
# kurz nach der Veranstaltung geloescht, hier haengt die Frist an der weiteren
# Nutzung der gespendeten Bilder. Der Text steht deshalb in der Vorlage - wie
# Sicherheitshinweis und Bildrechte, aus demselben Grund: es muss belegbar
# bleiben, welchem Wortlaut jemand zugestimmt hat.

# --- Backoffice / Anmeldung ------------------------------------------------

import secrets as _secrets  # noqa: E402  (bewusst erst hier, nur für den Fallback)

ADMIN_PASSWORD_HASH = os.environ.get("ADMIN_PASSWORD_HASH", "").strip()

APP_SECRET_KEY = os.environ.get("APP_SECRET_KEY", "").strip()
SECRET_KEY_FLUECHTIG = not APP_SECRET_KEY
if SECRET_KEY_FLUECHTIG:
    APP_SECRET_KEY = _secrets.token_urlsafe(32)

SESSION_STUNDEN = int(os.environ.get("SESSION_STUNDEN", "12"))
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "auto").strip().lower()
LOGIN_VERSUCHE = int(os.environ.get("LOGIN_VERSUCHE", "5"))
LOGIN_FENSTER_SEKUNDEN = int(os.environ.get("LOGIN_FENSTER_SEKUNDEN", "60"))

# Kürzel bei der Anmeldung abfragen – wird beim Ausgeben des Badges vermerkt.
KUERZEL_ABFRAGEN = _flag("KUERZEL_ABFRAGEN")

# --- Mailversand -----------------------------------------------------------

SMTP_HOST = os.environ.get("SMTP_HOST", "").strip()
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "").strip()
SMTP_PASS = os.environ.get("SMTP_PASS", "")
SMTP_TLS = os.environ.get("SMTP_TLS", "starttls").strip().lower()
SMTP_TIMEOUT = int(os.environ.get("SMTP_TIMEOUT", "20"))

MAIL_FROM = os.environ.get("MAIL_FROM", "").strip()
MAIL_REPLY_TO = os.environ.get("MAIL_REPLY_TO", "").strip()

MAIL_INTERVALL = int(os.environ.get("MAIL_INTERVALL", "30"))
MAIL_MAX_VERSUCHE = int(os.environ.get("MAIL_MAX_VERSUCHE", "5"))

MAIL_AKTIV = bool(SMTP_HOST and MAIL_FROM)

# --- Sonstiges -------------------------------------------------------------

CSV_TRENNER = os.environ.get("CSV_TRENNER", ";")[:1] or ";"


def pfad(*teile: str) -> str:
    """Baut eine URL unterhalb von FORM_PATH, ohne doppelte Schrägstriche."""
    basis = "" if FORM_PATH == "/" else FORM_PATH
    return basis + "/" + "/".join(t.strip("/") for t in teile if t) if teile else FORM_PATH
