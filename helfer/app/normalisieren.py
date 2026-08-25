"""Rohdaten aus dem alten Registrierungstool in saubere Werte überführen.

Reine Funktionen ohne Datenbank und ohne Web – damit sie sich einzeln prüfen
lassen (tests/test_normalisieren.py). Grundregel überall: was sich nicht
zweifelsfrei zuordnen lässt, wird NICHT geraten. Der Rohwert bleibt erhalten,
und der Importbericht nennt den Fall.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timedelta

# --- Text ------------------------------------------------------------------


def text(roh: str | None) -> str:
    """Führende/folgende Leerzeichen weg, innen auf je eines eindampfen.
    'Straßensperrung  Aufbau    Größe M' hat drei verschiedene Abstände."""
    if not roh:
        return ""
    return re.sub(r"\s+", " ", str(roh).replace("\u00a0", " ")).strip()


def schluessel(name: str, email: str) -> str:
    """Erkennungsmerkmal einer Person: Name und Mailadresse, klein geschrieben.

    Die Mailadresse allein taugt nicht – im Bestand hängen bis zu acht
    verschiedene Namen an einer Adresse, weil eine Person ihre Leute
    gesammelt angemeldet hat. Der Name allein taugt auch nicht. Beides
    zusammen trennt die Personen und fasst zugleich 'Thomas' und 'thomas'
    zusammen, die sonst zweimal entstünden.
    """
    return text(name).casefold() + "|" + text(email).casefold()


# --- Verpflegung -----------------------------------------------------------

_FLEISCH = {"fleisch", "nein", "n", "omnivor", "alles", "egal"}
_VEGGIE = {"vegetarisch", "vegetarier", "veggie", "ja", "j", "vegan", "veg"}


def veggie(roh: str | None) -> tuple[bool | None, bool]:
    """(Wert, verstanden). None heißt 'nicht erhoben'.

    Rückgabe verstanden=False bei einem Wert, der weder nach Fleisch noch nach
    vegetarisch aussieht – im Bestand steht dort einmal 'L', also eine
    T-Shirt-Größe in der falschen Spalte.
    """
    wert = text(roh).casefold()
    if not wert:
        return None, True
    if wert in _VEGGIE:
        return True, True
    if wert in _FLEISCH:
        return False, True
    return None, False


# --- T-Shirt ---------------------------------------------------------------

GROESSEN = ("XS", "S", "M", "L", "XL", "XXL", "3XL", "4XL", "5XL")

_SCHREIBWEISEN = {
    "XS": "XS", "S": "S", "M": "M", "L": "L", "XL": "XL",
    "XXL": "XXL", "2XL": "XXL",
    "XXXL": "3XL", "3XL": "3XL",
    "XXXXL": "4XL", "4XL": "4XL",
    "XXXXXL": "5XL", "5XL": "5XL",
}


def tshirt(roh: str | None) -> tuple[str | None, bool]:
    """(normalisierte Größe, eindeutig).

    'Damen L' -> 'L', '4xl' -> '4XL', 'Shirt Gr.M' -> 'M', 'L.' -> 'L'.
    Der Rohwert wird daneben aufbewahrt: 'Damen L' ist beim Bestellen eine
    Information, die 'L' allein nicht mehr hergibt.

    eindeutig=False, wenn im Text mehrere verschiedene Größen stehen – dann
    wird nichts gesetzt, weil jede Wahl geraten wäre.
    """
    wert = text(roh)
    if not wert:
        return None, True

    gefunden = []
    for stueck in re.split(r"[^0-9A-Za-zÄÖÜäöüß]+", wert.upper()):
        if stueck in _SCHREIBWEISEN:
            gefunden.append(_SCHREIBWEISEN[stueck])

    verschieden = set(gefunden)
    if len(verschieden) == 1:
        return gefunden[0], True
    if not verschieden:
        return None, False
    return None, False


# --- Datum und Zeit --------------------------------------------------------

_DATUM = re.compile(r"^(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})$")
_ZEITSPANNE = re.compile(
    r"^(\d{1,2})[:.](\d{2})\s*(?:-|–|—|bis)\s*(\d{1,2})[:.](\d{2})$")


def datum(roh: str | None) -> date | None:
    """'28.08.2026' oder '2026-08-28' -> date. Sonst None."""
    wert = text(roh)
    if not wert:
        return None
    treffer = _DATUM.match(wert)
    if treffer:
        tag, monat, jahr = (int(t) for t in treffer.groups())
        try:
            return date(jahr, monat, tag)
        except ValueError:
            return None
    try:
        return date.fromisoformat(wert)
    except ValueError:
        return None


def zeitspanne(datum_roh: str | None,
               zeit_roh: str | None) -> tuple[str, str, str] | None:
    """('28.08.2026', '20:00 - 08:00') -> Beginn, Ende, Kalendertag.

    Beginn und Ende sind volle Zeitstempel 'YYYY-MM-DD HH:MM'. Endet die
    Schicht früher, als sie beginnt, läuft sie über Mitternacht und das Ende
    fällt auf den Folgetag – im Bestand betrifft das '20:00 - 01:00' und
    '20:00 - 08:00'. Der Kalendertag bleibt der des Beginns, damit die
    Nachtschicht beim Abend steht und nicht am nächsten Morgen auftaucht.
    """
    tag = datum(datum_roh)
    treffer = _ZEITSPANNE.match(text(zeit_roh))
    if tag is None or treffer is None:
        return None

    von_h, von_m, bis_h, bis_m = (int(t) for t in treffer.groups())
    if not (0 <= von_h <= 23 and 0 <= von_m <= 59 and 0 <= bis_m <= 59) or bis_h > 24:
        return None

    beginn = datetime(tag.year, tag.month, tag.day, von_h, von_m)
    ende = datetime(tag.year, tag.month, tag.day, 0, 0) + timedelta(
        hours=bis_h, minutes=bis_m)
    if ende <= beginn:
        ende += timedelta(days=1)

    marke = "%Y-%m-%d %H:%M"
    return beginn.strftime(marke), ende.strftime(marke), tag.isoformat()


# --- Suche -----------------------------------------------------------------


def suchtext(*teile: str) -> str:
    """Alles klein, Umlaute aufgelöst – für die clientseitige Suche im
    data-Attribut. 'Öztürk' findet man dann auch als 'oztuerk'."""
    roh = " ".join(text(t) for t in teile if t).casefold()
    ersetzt = (roh.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
                  .replace("ß", "ss"))
    zerlegt = unicodedata.normalize("NFKD", ersetzt)
    return re.sub(r"\s+", " ",
                  "".join(z for z in zerlegt if not unicodedata.combining(z))).strip()


# --- Kennzeichen -----------------------------------------------------------

def kennzeichen(roh: str | None) -> str:
    """Kennzeichen auf Buchstaben und Ziffern eindampfen, in Großschrift.

    "il-a 123", "IL A 123" und "ila123" ergeben alle "ILA123". Dieselbe Regel
    wie in der Kennzeichen-App: bei der Schlüsselausgabe tippt niemand
    Bindestriche mit, und derselbe Wagen soll nicht zweimal im Stamm landen,
    weil einmal ein Leerzeichen mehr drin war.
    """
    return "".join(z for z in text(roh) if z.isalnum()).upper()


def kennzeichen_anzeige(roh: str | None) -> str:
    """Was der Mensch getippt hat, nur aufgeräumt – Trennzeichen bleiben."""
    return text(roh).upper()
