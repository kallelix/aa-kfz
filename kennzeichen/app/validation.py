"""Validierung des öffentlichen Formulars.

Liefert immer (werte, fehler): bereinigte Werte zum Wiederanzeigen und ein
Dict feld -> Meldung. Ist `fehler` leer, darf gespeichert werden.
"""

from __future__ import annotations

import re

from . import config

# Feld -> maximale Länge. Schützt die DB vor Müll und das Formular vor Romanen.
MAX_LAENGE = {
    "vorname": 80,
    "nachname": 80,
    "funktion": 120,
    "email": 254,
    "telefon": 40,
    "kennzeichen": 15,
    "bemerkung": 1000,
}

FELDER = tuple(MAX_LAENGE) + ("kategorie",)

# Bewusst großzügig: die endgültige Prüfung ist, ob die Mail ankommt.
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")
TELEFON_RE = re.compile(r"^[0-9+()/.\s-]{5,}$")

# Kuerzestes realistisches Kennzeichen liegt bei etwa "B-A 1". Die Pruefung
# bleibt bewusst grob: Saison-, Wechsel- und auslaendische Kennzeichen weichen
# stark ab, und ein zu strenges Muster wuerde echte Antraege abweisen.
MIN_KENNZEICHEN = 4

# Verstecktes Feld gegen einfache Bots. Name klingt absichtlich plausibel.
HONEYPOT = "webseite"


def _saeubern(roh: str | None) -> str:
    """Trimmen und Whitespace-Ketten zusammenfassen."""
    return re.sub(r"\s+", " ", (roh or "").replace("\r\n", "\n")).strip()


def _saeubern_mehrzeilig(roh: str | None) -> str:
    zeilen = [z.strip() for z in (roh or "").replace("\r\n", "\n").split("\n")]
    return "\n".join(zeilen).strip()


def ist_bot(formular) -> bool:
    """True, wenn das Honeypot-Feld befüllt wurde."""
    return bool((formular.get(HONEYPOT) or "").strip())


# Womit mehrere Kennzeichen in einem Feld getrennt werden. Das Leerzeichen
# ist ABSICHTLICH nicht dabei: "IL-A 123" enthaelt selbst eines, und aus einer
# Eingabe wuerden zwei unbrauchbare Bruchstuecke.
KFZ_TRENNER = (",", ";", chr(10), chr(13), chr(9))


def kennzeichen_liste(roh) -> tuple[list, str]:
    """Zerlegt ein Feld mit mehreren Kennzeichen. Gibt (Liste, Fehler).

    Nur im Backoffice: wer am Tisch drei Fahrzeuge derselben Person erfasst,
    soll das Formular einmal ausfuellen. Das oeffentliche Formular bleibt bei
    einem Kennzeichen - dort kommt jeder Antrag von einem Menschen.

    Doppelte fallen weg, und zwar nach der Normalisierung: "IL-A 123" und
    "ila123" sind derselbe Wagen. Die erste Schreibweise gewinnt, weil sie
    gedruckt wird.
    """
    if not isinstance(roh, str):
        roh = "" if roh is None else str(roh)

    stuecke = [roh]
    for zeichen in KFZ_TRENNER:
        zerlegt = []
        for stueck in stuecke:
            zerlegt.extend(stueck.split(zeichen))
        stuecke = zerlegt

    liste: list = []
    gesehen: set = set()
    for stueck in stuecke:
        # Mehrfache Leerzeichen einebnen, aber eines darf bleiben.
        eines = " ".join(stueck.split()).upper()
        if not eines:
            continue
        if len(eines) < MIN_KENNZEICHEN:
            return [], "„" + eines + "“ sieht nicht nach einem Kennzeichen aus."
        if len(eines) > MAX_LAENGE["kennzeichen"]:
            return [], "„" + eines + "“ ist zu lang."
        merkmal = "".join(z for z in eines if z.isalnum())
        if merkmal in gesehen:
            continue
        gesehen.add(merkmal)
        liste.append(eines)
    return liste, ""


def pruefen(formular, kontakt_pflicht: bool = True) -> tuple[dict, dict]:
    """Prueft die Formularwerte. Gibt (Werte, Fehler) zurueck.

    `kontakt_pflicht=False` nur fuer den Fall, in dem es nichts zu beantworten
    gibt: die Orga erfasst jemanden am Tisch und genehmigt sofort. Die Person
    steht davor und bekommt ihre Karte in die Hand - eine Adresse zu verlangen,
    nur damit das Formular durchgeht, brachte niemandem etwas.

    Ueberall sonst bleibt es Pflicht, und das aus dem Grund, der unten steht:
    ohne Kontaktweg erreicht die Entscheidung den Antragsteller nie.
    """
    werte = {feld: _saeubern(formular.get(feld)) for feld in FELDER}
    werte["bemerkung"] = _saeubern_mehrzeilig(formular.get("bemerkung"))
    werte["email"] = werte["email"].lower()
    werte["kennzeichen"] = werte["kennzeichen"].upper()
    if not config.KENNZEICHEN_ERFASSEN:
        werte["kennzeichen"] = ""

    fehler: dict[str, str] = {}

    for feld, beschriftung in (
        ("vorname", "Vorname"),
        ("nachname", "Name"),
        ("funktion", "Funktion"),
    ):
        if not werte[feld]:
            fehler[feld] = f"{beschriftung} bitte ausfüllen."

    # Pflicht, sobald es erhoben wird: an der Straßensperre werden die Aufkleber
    # anhand dieser Liste ausgegeben. Ohne Kennzeichen ist der Eintrag dort
    # wertlos.
    if config.KENNZEICHEN_ERFASSEN:
        if not werte["kennzeichen"]:
            fehler["kennzeichen"] = "Bitte das amtliche Kennzeichen angeben."
        elif len(werte["kennzeichen"]) < MIN_KENNZEICHEN:
            fehler["kennzeichen"] = "Das sieht nicht nach einem Kennzeichen aus."

    if not werte["kategorie"]:
        fehler["kategorie"] = "Bitte eine Kategorie auswählen."
    elif werte["kategorie"] not in config.KATEGORIE_KEYS:
        fehler["kategorie"] = "Unbekannte Kategorie."

    if werte["email"] and not EMAIL_RE.match(werte["email"]):
        fehler["email"] = "Das sieht nicht nach einer E-Mail-Adresse aus."

    if werte["telefon"] and not TELEFON_RE.match(werte["telefon"]):
        fehler["telefon"] = "Bitte nur Ziffern und die Zeichen + ( ) / - verwenden."

    # Kernregel: ohne Kontaktweg ist der Antrag nicht bearbeitbar.
    if kontakt_pflicht and not werte["email"] and not werte["telefon"]:
        meldung = "Bitte mindestens E-Mail oder Telefon angeben – sonst können wir nicht antworten."
        fehler.setdefault("email", meldung)
        fehler.setdefault("telefon", meldung)

    for feld, grenze in MAX_LAENGE.items():
        if len(werte[feld]) > grenze:
            fehler[feld] = f"Bitte auf {grenze} Zeichen kürzen."

    return werte, fehler
