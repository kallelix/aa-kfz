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


# Welche Datei gilt. Im Betrieb zeigt HELFER_ENV auf /etc/abfahrt/…,
# lokal liegt sie neben der Anwendung.
_DATEI = Path(os.environ.get("HELFER_ENV", "") or (BASE_DIR / ".env"))
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


def _zahl(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)).strip())
    except ValueError:
        return default


# --- Betrieb ---------------------------------------------------------------

BIND = _env("BIND", "127.0.0.1:8082")

# Von welchen Adressen X-Forwarded-For und X-Forwarded-Proto geglaubt werden.
# Liegt der Reverse Proxy auf einem anderen Host, MUSS hier dessen IP stehen.
FORWARDED_ALLOW_IPS = _env("FORWARDED_ALLOW_IPS", "127.0.0.1").strip()

DB_PATH = Path(_env("DB_PATH", str(BASE_DIR / "data" / "helfer.db")))
if not DB_PATH.is_absolute():
    DB_PATH = BASE_DIR / DB_PATH

BASIS_PFAD = "/" + _env("BASIS_PFAD", "/").strip("/")

# Öffentliche Adresse, z. B. https://helfer.example.de. Wird für den
# Monitor-Link gebraucht; leer heißt: aus der Anfrage ableiten.
BASIS_URL = _env("BASIS_URL", "").strip().rstrip("/")


def bind_adresse() -> tuple[str, int]:
    """'127.0.0.1:8082' -> ('127.0.0.1', 8082). Auch '[::1]:8082' geht."""
    rest, _, hafen = BIND.rpartition(":")
    if not rest:
        return "127.0.0.1", int(hafen or 8082)
    return rest.strip("[]") or "127.0.0.1", int(hafen or 8082)


def nur_localhost() -> bool:
    return bind_adresse()[0] in ("127.0.0.1", "::1", "localhost")


# --- Veranstaltung ---------------------------------------------------------

VERANSTALTUNG = _env("VERANSTALTUNG", "Die absolute Abfahrt")
ORT = _env("ORT", "Ilmenau")

# Die drei Renntage. Der Zeitplan-Abruf braucht sie, um Wochentage ("Freitag")
# auf Daten abzubilden; Auf- und Abbauschichten liegen davor und danach.
TAGE_ROH = _env("TAGE", "2026-08-28,2026-08-29,2026-08-30")


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


# --- Zeitplan der Rennserien -----------------------------------------------

# Welche Serien abgerufen werden. Je Schlüssel gibt es drei weitere Variablen,
# siehe unten. Leer heißt: kein Abruf.
ZEITPLAN_SERIEN = [t.strip() for t in
                   _env("ZEITPLAN_SERIEN", "dhc,kids").split(",")
                   if t.strip()]

# Voreinstellungen für die beiden Serien, die 2026 in Ilmenau fahren. Alles
# davon lässt sich per Env überschreiben, ohne den Code anzufassen.
_ZEITPLAN_VORGABEN = {
    "dhc": {
        "titel": "iXS Downhill Cup",
        "url": "https://www.ixsdownhillcup.com/zeitplan/dhc-zeitplan",
        # Auf der Seite stehen zwei Tabellen: "allgemein" und "Willingen".
        # Ilmenau braucht die allgemeine.
        "abschnitt": "allgemein",
        "farbe": "#95bf0b",
    },
    "kids": {
        "titel": "iXS Kids Cup",
        "url": "https://www.kidscup.bike/zeitplan",
        "abschnitt": "allgemein",
        "farbe": "#4e690f",
    },
}


def serien() -> list[dict]:
    ergebnis = []
    for schluessel in ZEITPLAN_SERIEN:
        vorgabe = _ZEITPLAN_VORGABEN.get(schluessel, {})
        praefix = "ZEITPLAN_" + schluessel.upper() + "_"
        eintrag = {
            "schluessel": schluessel,
            "titel": _env(praefix + "TITEL",
                                    vorgabe.get("titel", schluessel)),
            "url": _env(praefix + "URL", vorgabe.get("url", "")).strip(),
            "abschnitt": _env(praefix + "ABSCHNITT",
                                        vorgabe.get("abschnitt", "allgemein")),
            "farbe": _env(praefix + "FARBE",
                                    vorgabe.get("farbe", "#95bf0b")),
        }
        if eintrag["url"]:
            ergebnis.append(eintrag)
    return ergebnis


def serie(schluessel: str) -> dict | None:
    for eintrag in serien():
        if eintrag["schluessel"] == schluessel:
            return eintrag
    return None


# Täglicher Abruf zu dieser vollen Stunde (0–23). Leer oder -1 schaltet ihn
# ab; von Hand geht er im Backoffice immer.
ZEITPLAN_STUNDE = _zahl("ZEITPLAN_STUNDE", 4)


# --- Abruf der Helferliste --------------------------------------------------

# Statt die beiden CSV-Dateien von Hand herunterzuladen und hochzuladen, holt
# sie der Abruf selbst.
#
# Alle drei Adressen enthalten persoenliche Zugangstoken und gehoeren
# ausschliesslich in die .env - das Repo ist oeffentlich. Der Login-Link ist
# der Sache nach ein Passwort: wer ihn hat, sieht die ganze Helferliste samt
# Adressen und Telefonnummern.
#
# Der Login-Link ist noetig, weil der Token in den CSV-Adressen allein nicht
# genuegt: ohne Sitzung liefert der Dienst die Anmeldeseite statt der Datei.
# Er laesst sich mehrfach verwenden, der Abruf meldet sich also jedes Mal neu
# an, statt eine Sitzung aufzubewahren, die ohnehin ablaufen wuerde.
IMPORT_LOGIN_URL = _env("IMPORT_LOGIN_URL", "").strip()
IMPORT_URL_VERGEBEN = _env("IMPORT_URL_VERGEBEN", "").strip()
IMPORT_URL_OFFEN = _env("IMPORT_URL_OFFEN", "").strip()

# Der Abruf steht nur bereit, wenn alle drei da sind. Zwei von dreien ergaeben
# einen halben Bedarf - denselben Grund hat der Import, beide Dateien zu
# verlangen.
IMPORT_ABRUF_MOEGLICH = bool(IMPORT_LOGIN_URL and IMPORT_URL_VERGEBEN
                             and IMPORT_URL_OFFEN)

# Abstand zwischen zwei selbsttaetigen Abgleichen, in Minuten. 0 oder weniger
# schaltet sie ab; von Hand geht es dann immer noch.
#
# Nicht zu knapp waehlen: jeder Lauf sind drei Aufrufe bei einem fremden
# Dienst - anmelden, vergebene Posten, offene Posten. Stuendlich sind das 72
# am Tag, das faellt dort nicht auf. Alle fuenf Minuten waeren es 864.
IMPORT_TAKT_MINUTEN = _zahl("IMPORT_TAKT_MINUTEN", 60)

# Untergrenze, damit ein Vertipper in der .env den fremden Dienst nicht
# ueberrennt.
if 0 < IMPORT_TAKT_MINUTEN < 5:
    IMPORT_TAKT_MINUTEN = 5


# --- Monitor ---------------------------------------------------------------

# Wie oft die Monitoransicht neu lädt (Sekunden).
MONITOR_INTERVALL = _zahl("MONITOR_INTERVALL", 60)

# Wie weit die Monitoransicht nach vorn schaut (Minuten). Was jetzt läuft und
# was in diesem Fenster beginnt, steht oben.
MONITOR_VORSCHAU = _zahl("MONITOR_VORSCHAU", 120)

# Ab wie vielen fehlenden Helfern eine Schicht auf dem Monitor als kritisch
# gilt. 0 schaltet die Hervorhebung ab.
MONITOR_WARNUNG = _zahl("MONITOR_WARNUNG", 1)

# Wie lange ein angetipptes Schicht-Overlay offen bleibt (Sekunden), bevor es
# sich von selbst schließt. Ohne das bliebe der Wandmonitor in der Ansicht
# hängen, sobald jemand sie öffnet und weggeht. 0 schaltet den Selbstschließer
# ab – dann muss von Hand geschlossen werden.
MONITOR_OVERLAY_SEKUNDEN = _zahl("MONITOR_OVERLAY_SEKUNDEN", 90)

# Wie lange der Tagesblick offen bleibt (Sekunden), bevor der Monitor von
# selbst auf "Jetzt" zurückspringt. Aus demselben Grund wie beim Overlay: wer
# einen Tag aufschlägt und weggeht, darf den Bildschirm nicht dort festsetzen.
# 0 schaltet den Rücksprung ab.
MONITOR_TAGESBLICK_SEKUNDEN = _zahl("MONITOR_TAGESBLICK_SEKUNDEN", 120)

# --- Unterschriften --------------------------------------------------------

# Wie lange eine Unterschriftsanforderung auf dem Tablet steht, bevor sie
# verfällt (Minuten). Das ist die Sicherheitsgrenze der Tablet-Adresse: sie
# nimmt Eingaben entgegen, anders als der Monitor. Verfällt der Eintrag, kann
# ein abhandengekommener Link nichts anrichten, solange niemand am Tisch steht.
UNTERSCHRIFT_MINUTEN = _zahl("UNTERSCHRIFT_MINUTEN", 5)

# Nachfrist für das Absenden. Wer beim Ablaufen gerade zeichnet, soll nicht
# von vorn anfangen müssen – angezeigt wird der Eintrag dann nicht mehr, aber
# eine schon begonnene Unterschrift wird noch angenommen (Minuten).
UNTERSCHRIFT_NACHFRIST = _zahl("UNTERSCHRIFT_NACHFRIST", 10)

# Wie oft das Tablet nachfragt, ob etwas ansteht (Sekunden).
UNTERSCHRIFT_TAKT = _zahl("UNTERSCHRIFT_TAKT", 2)

# Was den Helfern am Tablet über die Aufbewahrung gesagt wird. Eine
# Unterschrift ist ein personenbezogenes Datum – sie braucht einen Zweck und
# eine Frist, und beides gehört dorthin, wo unterschrieben wird.
UNTERSCHRIFT_AUFBEWAHRUNG = _env(
    "UNTERSCHRIFT_AUFBEWAHRUNG",
    "Die Unterschrift belegt nur die Übergabe und wird nach der "
    "Veranstaltung gelöscht.").strip()

# Wie oft das Backoffice nachfragt, ob eine Unterschrift eingegangen ist
# (Sekunden). 0 schaltet das Nachfragen ab; dann muss man neu laden, um zu
# sehen, ob jemand unterschrieben hat.
ADMIN_TAKT = _zahl("ADMIN_TAKT", 3)

# Feste Zeitzone – der Monitor steht in Ilmenau, egal wo der Server läuft.
ZEITZONE = _env("ZEITZONE", "Europe/Berlin").strip() or "Europe/Berlin"

# Erlaubt, die Uhr für Durchsichten zu verstellen: ISO-Zeitpunkt statt "jetzt".
# Leer heißt: echte Uhr. Im Betrieb bleibt das leer.
JETZT_FEST = _env("JETZT_FEST", "").strip()


# --- Ansprechpartner -------------------------------------------------------

KONTAKT_NAME = _env("KONTAKT_NAME", "Orga-Team Absolute Abfahrt")
KONTAKT_MAIL = _env("KONTAKT_MAIL", "")
KONTAKT_TELEFON = _env("KONTAKT_TELEFON", "")

# --- Backoffice / Anmeldung ------------------------------------------------

import secrets as _secrets  # noqa: E402  (bewusst erst hier, nur für den Fallback)

ADMIN_PASSWORD_HASH = _env("ADMIN_PASSWORD_HASH", "").strip()

APP_SECRET_KEY = _env("APP_SECRET_KEY", "").strip()
SECRET_KEY_FLUECHTIG = not APP_SECRET_KEY
if SECRET_KEY_FLUECHTIG:
    APP_SECRET_KEY = _secrets.token_urlsafe(32)

SESSION_STUNDEN = _zahl("SESSION_STUNDEN", 12)
COOKIE_SECURE = _env("COOKIE_SECURE", "auto").strip().lower()
LOGIN_VERSUCHE = _zahl("LOGIN_VERSUCHE", 5)
LOGIN_FENSTER_SEKUNDEN = _zahl("LOGIN_FENSTER_SEKUNDEN", 60)

KUERZEL_ABFRAGEN = _flag("KUERZEL_ABFRAGEN")

# --- Sonstiges -------------------------------------------------------------

CSV_TRENNER = _env("CSV_TRENNER", ";")[:1] or ";"

LOGO_DATEI = _env("LOGO_DATEI", "").strip()
if LOGO_DATEI and ("/" in LOGO_DATEI or "\\" in LOGO_DATEI):
    LOGO_DATEI = ""


def pfad(*teile: str) -> str:
    """Baut eine URL unterhalb von BASIS_PFAD, ohne doppelte Schrägstriche."""
    basis = "" if BASIS_PFAD == "/" else BASIS_PFAD
    return basis + "/" + "/".join(t.strip("/") for t in teile if t) if teile else BASIS_PFAD
