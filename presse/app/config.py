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


def _werte_lesen(pfad: Path) -> dict[str, str]:
    """Minimaler .env-Leser. Gibt die Werte zurück, statt sie in os.environ
    zu schieben.

    Der Unterschied ist der Kern der Zusammenführung: die drei Anwendungen
    laufen jetzt in EINEM Prozess und benutzen mit Absicht dieselben Namen –
    DB_PATH, APP_SECRET_KEY, ADMIN_PASSWORD_HASH. In os.environ gäbe es davon
    nur einen Satz, und es gewänne, wer zuerst lädt. Jede Anwendung hält ihre
    Werte deshalb für sich.
    """
    werte: dict[str, str] = {}
    if not pfad.exists():
        return werte
    for zeile in pfad.read_text(encoding="utf-8").splitlines():
        zeile = zeile.strip()
        if not zeile or zeile.startswith("#") or "=" not in zeile:
            continue
        name, _, wert = zeile.partition("=")
        werte[name.strip()] = wert.strip().strip('"').strip("'")
    return werte


# Welche Datei gilt. Im Betrieb zeigt PRESSE_ENV auf /etc/abfahrt/…,
# lokal liegt sie neben der Anwendung.
_DATEI = Path(os.environ.get("PRESSE_ENV", "") or (BASE_DIR / ".env"))
_WERTE = _werte_lesen(_DATEI)


def _env(name: str, vorgabe=None):
    """Erst die Prozessumgebung, dann die eigene Datei.

    Dieselbe Reihenfolge wie vorher, als der Lader os.environ.setdefault
    benutzte: ein ausdrücklich gesetzter Wert gewinnt. Daran hängen die
    Tests, die ihre Wegwerf-Datenbank über die Umgebung setzen – gäbe die
    Datei den Ausschlag, liefen sie gegen die echte.

    Der Preis: eine global gesetzte Variable gilt für alle drei Anwendungen.
    Deshalb setzt die Unit im Betrieb nur BIND und die drei Zeiger
    KENNZEICHEN_ENV, PRESSE_ENV und HELFER_ENV – alles andere steht in den
    Dateien, auf die sie zeigen.
    """
    aus_umgebung = os.environ.get(name)
    if aus_umgebung is not None:
        return aus_umgebung
    return _WERTE.get(name, vorgabe)


def _flag(name: str, default: str = "1") -> bool:
    return _env(name, default).strip().lower() not in ("0", "false", "nein", "")


# --- Betrieb ---------------------------------------------------------------

BIND = _env("BIND", "127.0.0.1:8081")

# Von welchen Adressen X-Forwarded-For und X-Forwarded-Proto geglaubt werden.
# Liegt der Reverse Proxy auf einem anderen Host, MUSS hier dessen IP stehen.
FORWARDED_ALLOW_IPS = _env("FORWARDED_ALLOW_IPS", "127.0.0.1").strip()

DB_PATH = Path(_env("DB_PATH", str(BASE_DIR / "data" / "presse.db")))
if not DB_PATH.is_absolute():
    DB_PATH = BASE_DIR / DB_PATH

FORM_PATH = "/" + _env("FORM_PATH", "/").strip("/")

# Öffentliche Adresse der Anwendung, z. B. https://presse.example.de. Wird für
# absolute Verweise gebraucht; leer heißt: aus der Anfrage ableiten.
BASIS_URL = _env("BASIS_URL", "").strip().rstrip("/")


def bind_adresse() -> tuple[str, int]:
    """'127.0.0.1:8081' -> ('127.0.0.1', 8081). Auch '[::1]:8081' geht."""
    rest, _, hafen = BIND.rpartition(":")
    if not rest:
        return "127.0.0.1", int(hafen or 8081)
    return rest.strip("[]") or "127.0.0.1", int(hafen or 8081)


def nur_localhost() -> bool:
    return bind_adresse()[0] in ("127.0.0.1", "::1", "localhost")


# --- Fachlich --------------------------------------------------------------

VERANSTALTUNG = _env("VERANSTALTUNG", "Die absolute Abfahrt")
ORT = _env("ORT", "Ilmenau")

# Akkreditierungsgebühr für kommerzielle Nutzung.
GEBUEHR_BETRAG = _env("GEBUEHR_BETRAG", "20").strip()
GEBUEHR_WAEHRUNG = _env("GEBUEHR_WAEHRUNG", "EUR").strip()

# Umfang der Bilderspende als Alternative zur Gebühr.
BILDER_ANZAHL = _env("BILDER_ANZAHL", "10").strip()

# Wohin die gespendeten Bilder sollen. Steht in der Erinnerungsmail; solange
# leer, bleibt der Text dort allgemein.
BILDER_ABGABE = _env("BILDER_ABGABE", "").strip()

ABHOLORT = _env("ABHOLORT", "Orga-Büro")

# Die Badges sind vorproduziert, also endlich. 0 heißt: keine Obergrenze und
# keine Warnung. Abgeriegelt wird nicht – siehe Plan, Abschnitt 9.
try:
    BADGES_GESAMT = int(_env("BADGES_GESAMT", "0"))
except ValueError:
    BADGES_GESAMT = 0


def gebuehr() -> str:
    """'20 EUR' – so, wie es im Formular und in der Mail steht."""
    return f"{GEBUEHR_BETRAG} {GEBUEHR_WAEHRUNG}".strip()


# --- Ansprechpartner -------------------------------------------------------

KONTAKT_NAME = _env("KONTAKT_NAME", "Orga-Team Absolute Abfahrt")
KONTAKT_MAIL = _env("KONTAKT_MAIL", "")
KONTAKT_TELEFON = _env("KONTAKT_TELEFON", "")

# --- Datenschutz -----------------------------------------------------------

IP_SPEICHERN = _flag("IP_SPEICHERN")

# Kein AUFBEWAHRUNG_HINWEIS wie in der Kennzeichen-App: dort werden die Daten
# kurz nach der Veranstaltung geloescht, hier haengt die Frist an der weiteren
# Nutzung der gespendeten Bilder. Der Text steht deshalb in der Vorlage - wie
# Sicherheitshinweis und Bildrechte, aus demselben Grund: es muss belegbar
# bleiben, welchem Wortlaut jemand zugestimmt hat.

# --- Backoffice / Anmeldung ------------------------------------------------

import secrets as _secrets  # noqa: E402  (bewusst erst hier, nur für den Fallback)

ADMIN_PASSWORD_HASH = _env("ADMIN_PASSWORD_HASH", "").strip()

APP_SECRET_KEY = _env("APP_SECRET_KEY", "").strip()
SECRET_KEY_FLUECHTIG = not APP_SECRET_KEY
if SECRET_KEY_FLUECHTIG:
    APP_SECRET_KEY = _secrets.token_urlsafe(32)

SESSION_STUNDEN = int(_env("SESSION_STUNDEN", "12"))
COOKIE_SECURE = _env("COOKIE_SECURE", "auto").strip().lower()
LOGIN_VERSUCHE = int(_env("LOGIN_VERSUCHE", "5"))
LOGIN_FENSTER_SEKUNDEN = int(_env("LOGIN_FENSTER_SEKUNDEN", "60"))

# Kürzel bei der Anmeldung abfragen – wird beim Ausgeben des Badges vermerkt.
KUERZEL_ABFRAGEN = _flag("KUERZEL_ABFRAGEN")

# --- Mailversand -----------------------------------------------------------

SMTP_HOST = _env("SMTP_HOST", "").strip()
SMTP_PORT = int(_env("SMTP_PORT", "587"))
SMTP_USER = _env("SMTP_USER", "").strip()
SMTP_PASS = _env("SMTP_PASS", "")
SMTP_TLS = _env("SMTP_TLS", "starttls").strip().lower()
SMTP_TIMEOUT = int(_env("SMTP_TIMEOUT", "20"))

MAIL_FROM = _env("MAIL_FROM", "").strip()
MAIL_REPLY_TO = _env("MAIL_REPLY_TO", "").strip()

MAIL_INTERVALL = int(_env("MAIL_INTERVALL", "30"))
MAIL_MAX_VERSUCHE = int(_env("MAIL_MAX_VERSUCHE", "5"))

MAIL_AKTIV = bool(SMTP_HOST and MAIL_FROM)

# --- Sonstiges -------------------------------------------------------------

CSV_TRENNER = _env("CSV_TRENNER", ";")[:1] or ";"


def pfad(*teile: str) -> str:
    """Baut eine URL unterhalb von FORM_PATH, ohne doppelte Schrägstriche."""
    basis = "" if FORM_PATH == "/" else FORM_PATH
    return basis + "/" + "/".join(t.strip("/") for t in teile if t) if teile else FORM_PATH
