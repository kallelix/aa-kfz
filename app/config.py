"""Konfiguration – ausschließlich über Env-Variablen (siehe .env.example)."""

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


# Welche Datei gilt. Im Betrieb zeigt KENNZEICHEN_ENV auf /etc/abfahrt/…,
# lokal liegt sie neben der Anwendung.
_DATEI = Path(os.environ.get("KENNZEICHEN_ENV", "") or (BASE_DIR / ".env"))
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


def _parse_kategorien(roh: str) -> list[tuple[str, str]]:
    """'key:Label,key2:Label 2' -> [(key, Label), ...]"""
    kategorien: list[tuple[str, str]] = []
    for eintrag in roh.split(","):
        eintrag = eintrag.strip()
        if not eintrag:
            continue
        schluessel, _, label = eintrag.partition(":")
        schluessel = schluessel.strip()
        if schluessel:
            kategorien.append((schluessel, (label.strip() or schluessel)))
    return kategorien


# --- Betrieb ---
BIND = _env("BIND", "127.0.0.1:8080")

# Von welchen Adressen X-Forwarded-For und X-Forwarded-Proto geglaubt werden.
# Liegt der Reverse Proxy auf einem anderen Host, MUSS hier dessen IP stehen –
# sonst protokolliert die App die Proxy-IP als Absender und das Login-Rate-Limit
# sperrt bei einem Fehlversuch gleich alle aus.
FORWARDED_ALLOW_IPS = _env("FORWARDED_ALLOW_IPS", "127.0.0.1").strip()


def bind_adresse() -> tuple[str, int]:
    """'127.0.0.1:8080' -> ('127.0.0.1', 8080). Auch '[::1]:8080' geht."""
    rest, _, hafen = BIND.rpartition(":")
    if not rest:
        return "127.0.0.1", int(hafen or 8080)
    return rest.strip("[]") or "127.0.0.1", int(hafen or 8080)


def nur_localhost() -> bool:
    return bind_adresse()[0] in ("127.0.0.1", "::1", "localhost")
DB_PATH = Path(_env("DB_PATH", str(BASE_DIR / "data" / "antraege.db")))
if not DB_PATH.is_absolute():
    DB_PATH = BASE_DIR / DB_PATH

FORM_PATH = "/" + _env("FORM_PATH", "/").strip("/")

# --- Fachlich ---
VERANSTALTUNG = _env("VERANSTALTUNG", "Die absolute Abfahrt")
KATEGORIEN = _parse_kategorien(
    _env(
        "KATEGORIEN", "camping:Camping,expo:Expo,local:Local/Durchfahrt,parken:Parken,vip:VIP"
    )
)
KATEGORIE_KEYS = [k for k, _ in KATEGORIEN]
KATEGORIE_LABELS = dict(KATEGORIEN)

# Ein Satz je Kategorie, der im Formular unter der Auswahl steht. Damit muss
# niemand raten, welche Kategorie die eigene ist.
#
# Bewusst eine Variable je Kategorie statt eines weiteren Feldes in KATEGORIEN:
# dort trennen Komma und Doppelpunkt, und beides kommt in einem deutschen Satz
# vor. KATEGORIE_TEXT_CAMPING=... ueberschreibt den Text fuer "camping".
_STANDARD_TEXTE = {
    "camping": "Du bist Helfer und möchtest auf dem Campingplatz übernachten.",
    "expo": "Du bist Aussteller und hast einen EXPO-Platz gebucht.",
    "local": "Du musst als Anlieger die Straßensperre passieren.",
    "parken": "Du musst auf dem Parkplatz der Veranstaltung parken.",
    "vip": "Du musst auf dem Veranstaltungsgelände parken.",
}


def _kategorie_text(schluessel: str) -> str:
    name = "KATEGORIE_TEXT_" + re.sub(r"[^A-Za-z0-9]", "_", schluessel).upper()
    return _env(name, _STANDARD_TEXTE.get(schluessel, "")).strip()


KATEGORIE_TEXTE = {schluessel: _kategorie_text(schluessel) for schluessel in KATEGORIE_KEYS}
KENNZEICHEN_ERFASSEN = _flag("KENNZEICHEN_ERFASSEN")

# --- Ansprechpartner ---
KONTAKT_NAME = _env("KONTAKT_NAME", "Orga Absolute Abfahrt")
KONTAKT_MAIL = _env("KONTAKT_MAIL", "")
KONTAKT_TELEFON = _env("KONTAKT_TELEFON", "")

# --- Datenschutz ---
IP_SPEICHERN = _flag("IP_SPEICHERN")
AUFBEWAHRUNG_HINWEIS = _env(
    "AUFBEWAHRUNG_HINWEIS",
    "Die Daten werden spätestens vier Wochen nach der Veranstaltung gelöscht.",
)


def pfad(*teile: str) -> str:
    """Baut eine URL unterhalb von FORM_PATH, ohne doppelte Schrägstriche."""
    basis = "" if FORM_PATH == "/" else FORM_PATH
    return basis + "/" + "/".join(t.strip("/") for t in teile if t) if teile else FORM_PATH


# --- Backoffice / Anmeldung (Schritt 3) ---
import secrets as _secrets  # noqa: E402  (bewusst erst hier, nur für den Fallback)

ADMIN_PASSWORD_HASH = _env("ADMIN_PASSWORD_HASH", "").strip()

# Ohne gesetzten Schlüssel wird beim Start einer erzeugt: die App läuft, aber
# alle Sitzungen enden mit dem nächsten Neustart. Für den Betrieb setzen.
APP_SECRET_KEY = _env("APP_SECRET_KEY", "").strip()
SECRET_KEY_FLUECHTIG = not APP_SECRET_KEY
if SECRET_KEY_FLUECHTIG:
    APP_SECRET_KEY = _secrets.token_urlsafe(32)

SESSION_STUNDEN = int(_env("SESSION_STUNDEN", "12"))

# "auto" = Secure-Flag setzen, wenn der Browser über HTTPS kam (Proxy-Header).
# Lokal über http bliebe das Cookie sonst ungesendet und die Anmeldung kaputt.
COOKIE_SECURE = _env("COOKIE_SECURE", "auto").strip().lower()

LOGIN_VERSUCHE = int(_env("LOGIN_VERSUCHE", "5"))
LOGIN_FENSTER_SEKUNDEN = int(_env("LOGIN_FENSTER_SEKUNDEN", "60"))

# Optionales Bearbeiter-Kürzel bei der Anmeldung (offene Frage 5 im Plan).
KUERZEL_ABFRAGEN = _flag("KUERZEL_ABFRAGEN")


# --- Kontingente (Schritt 5) ------------------------------------------------


def _parse_kontingente(roh: str) -> dict[str, int]:
    """'camping:120,vip:40' -> {'camping': 120, ...}

    Leer heißt: keine Obergrenze, keine Warnung (offene Frage 1 im Plan).
    """
    kontingente: dict[str, int] = {}
    for eintrag in roh.split(","):
        eintrag = eintrag.strip()
        if not eintrag or ":" not in eintrag:
            continue
        schluessel, _, zahl = eintrag.partition(":")
        try:
            kontingente[schluessel.strip()] = int(zahl.strip())
        except ValueError:
            continue
    return kontingente


KONTINGENTE = _parse_kontingente(_env("KONTINGENTE", ""))


# --- Mailversand (Schritt 6) ------------------------------------------------

SMTP_HOST = _env("SMTP_HOST", "").strip()
SMTP_PORT = int(_env("SMTP_PORT", "587"))
SMTP_USER = _env("SMTP_USER", "").strip()
SMTP_PASS = _env("SMTP_PASS", "")
# starttls (Vorgabe, Port 587) | ssl (Port 465) | keine
SMTP_TLS = _env("SMTP_TLS", "starttls").strip().lower()
SMTP_TIMEOUT = int(_env("SMTP_TIMEOUT", "20"))

MAIL_FROM = _env("MAIL_FROM", "").strip()
MAIL_REPLY_TO = _env("MAIL_REPLY_TO", "").strip()

MAIL_INTERVALL = int(_env("MAIL_INTERVALL", "30"))
MAIL_MAX_VERSUCHE = int(_env("MAIL_MAX_VERSUCHE", "5"))

# Ohne SMTP_HOST oder MAIL_FROM wird nichts verschickt. Die Mails sammeln sich
# dann in mail_out an – nichts geht verloren, es geht nur nichts raus.
MAIL_AKTIV = bool(SMTP_HOST and MAIL_FROM)

# Wo und wann die Karten übergeben werden (offene Frage 4 im Plan). Solange das
# leer ist, verspricht die Genehmigungsmail keinen Ort und keine Uhrzeit.
ABHOLUNG = _env("ABHOLUNG", "").strip()


# --- CSV-Export (Schritt 8) -------------------------------------------------

# Excel richtet sich nach dem Listentrennzeichen der Systemsprache; im deutschen
# Windows ist das das Semikolon. Wer die Datei maschinell weiterverarbeitet,
# stellt hier auf "," um.
CSV_TRENNER = _env("CSV_TRENNER", ";")[:1] or ";"


# --- Druckansicht der Karten (Schritt 11) -----------------------------------

# Basis fuer den QR-Code, z. B. https://kennzeichen.example.de – gescannt fuehrt
# er dann in die Detailansicht des Antrags. Die verlangt eine Anmeldung, taugt
# also fuer die Orga und gibt Fremden nichts preis. Leer = der QR-Code traegt
# nur die Antragsnummer als Text.
KARTEN_URL_BASIS = _env("KARTEN_URL_BASIS", "").strip().rstrip("/")

# Dateiname eines Logos unterhalb von app/static, z. B. "logo.svg". Fehlt die
# Datei, steht auf der Karte nur der Veranstaltungsname.
LOGO_DATEI = _env("LOGO_DATEI", "").strip()


def logo_vorhanden() -> bool:
    """Nur ein blosser Dateiname direkt in app/static.

    Ein Pfad mit .. oder Schraegstrich wuerde ein <img src="/static/../..">
    erzeugen, das die Auslieferung ohnehin abweist – dann lieber gleich kein
    Logo anzeigen als ein kaputtes Bild.
    """
    if not LOGO_DATEI or LOGO_DATEI != Path(LOGO_DATEI).name:
        return False
    return (BASE_DIR / "app" / "static" / LOGO_DATEI).is_file()
