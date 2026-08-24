"""Aufgabenplan und das Bearbeiten von Programmpunkten.

Prüfen und Umformen der Formularwerte – ohne Datenbank, ohne Web, damit sich
beides einzeln prüfen lässt.

Der Konfliktschutz lebt hier nur als Begriff: jedes Formular trägt den Stand
mit, den es geladen hat (`geaendert_am`). Weicht er beim Speichern ab, hat
jemand anderes dazwischen gespeichert. Dann wird nicht überschrieben, sondern
gefragt – siehe `KONFLIKT`.
"""

from __future__ import annotations

from datetime import date, timedelta

from . import normalisieren

PHASEN = {
    "aufbau": "Aufbau",
    "event": "Veranstaltung",
    "abbau": "Abbau",
    "sonstiges": "Sonstiges",
}

STATUS = {
    "offen": "offen",
    "arbeit": "in Arbeit",
    "erledigt": "erledigt",
}

KONFLIKT = "konflikt"


def _uhrzeit(roh: str) -> str | None:
    """'08:30' oder '8.30' -> '08:30'. None, wenn es keine Uhrzeit ist."""
    wert = normalisieren.text(roh).replace(".", ":")
    if not wert:
        return ""
    teile = wert.split(":")
    if len(teile) != 2:
        return None
    try:
        stunde, minute = int(teile[0]), int(teile[1])
    except ValueError:
        return None
    if not (0 <= stunde <= 23 and 0 <= minute <= 59):
        return None
    return "%02d:%02d" % (stunde, minute)


def pruefen(daten: dict) -> tuple[dict, dict]:
    """(Werte, Fehler). Fehler ist leer, wenn alles passt."""
    fehler: dict[str, str] = {}

    titel = normalisieren.text(daten.get("titel"))[:200]
    if not titel:
        fehler["titel"] = "Ohne Bezeichnung lässt sich die Aufgabe nicht wiederfinden."

    phase = normalisieren.text(daten.get("phase")) or "event"
    if phase not in PHASEN:
        phase = "event"

    status = normalisieren.text(daten.get("status")) or "offen"
    if status not in STATUS:
        status = "offen"

    datum = normalisieren.datum(daten.get("datum"))
    datum_roh = normalisieren.text(daten.get("datum"))
    if datum_roh and datum is None:
        fehler["datum"] = "Das Datum ist nicht lesbar (erwartet: 2026-08-29)."

    von = _uhrzeit(daten.get("beginn", ""))
    bis = _uhrzeit(daten.get("ende", ""))
    if von is None:
        fehler["beginn"] = "Keine Uhrzeit (erwartet: 08:30)."
        von = ""
    if bis is None:
        fehler["ende"] = "Keine Uhrzeit (erwartet: 17:00)."
        bis = ""

    # Eine Uhrzeit ohne Tag wäre ortlos: sie stünde nirgends im Ablauf.
    if von and datum is None:
        fehler.setdefault(
            "datum", "Mit einer Uhrzeit braucht die Aufgabe auch einen Tag.")
    if bis and not von:
        fehler.setdefault("beginn", "Ein Ende ohne Anfang ergibt keine Zeitspanne.")

    beginn = ende = None
    if datum is not None and von:
        beginn = datum.isoformat() + " " + von
        if bis:
            # Über Mitternacht wie bei den Schichten: endet die Aufgabe
            # früher, als sie beginnt, liegt das Ende am Folgetag.
            tag = datum if bis > von else datum + timedelta(days=1)
            ende = tag.isoformat() + " " + bis

    werte = {
        "titel": titel,
        "phase": phase,
        "status": status,
        "datum": datum.isoformat() if datum else None,
        "beginn": beginn,
        "ende": ende,
        "ort": normalisieren.text(daten.get("ort"))[:120],
        "verantwortlich": normalisieren.text(daten.get("verantwortlich"))[:120],
        "kontakt": normalisieren.text(daten.get("kontakt"))[:120],
        "notiz": (daten.get("notiz") or "").strip()[:2000],
    }
    return werte, fehler


def programm_pruefen(daten: dict, datum: str) -> tuple[dict, dict]:
    """Dasselbe für einen Programmpunkt. Der Tag steht fest – er kommt aus
    dem Abruf und wird hier nicht verschoben."""
    fehler: dict[str, str] = {}

    titel = normalisieren.text(daten.get("titel"))[:200]
    if not titel:
        fehler["titel"] = "Ohne Bezeichnung geht es nicht."

    von = _uhrzeit(daten.get("beginn", ""))
    bis = _uhrzeit(daten.get("ende", ""))
    if von is None:
        fehler["beginn"] = "Keine Uhrzeit (erwartet: 11:30)."
        von = ""
    if bis is None:
        fehler["ende"] = "Keine Uhrzeit (erwartet: 13:00)."
        bis = ""
    if bis and not von:
        fehler.setdefault("beginn", "Ein Ende ohne Anfang ergibt keine Zeitspanne.")

    beginn = (datum + " " + von) if von else None
    ende = None
    if beginn and bis:
        tag = date.fromisoformat(datum)
        if bis <= von:
            tag += timedelta(days=1)
        ende = tag.isoformat() + " " + bis

    # Was hier gespeichert wird, ersetzt die Zeitangabe der Website. Der
    # Wortlaut wird mitgeführt, damit im Bericht des nächsten Abrufs steht,
    # wogegen verglichen wurde.
    if von and bis:
        zeit_roh = von + " - " + bis + " Uhr"
    elif von:
        zeit_roh = "ab " + von + " Uhr"
    else:
        zeit_roh = normalisieren.text(daten.get("zeit_roh"))[:120]

    return {
        "titel": titel,
        "beginn": beginn,
        "ende": ende,
        "zeit_roh": zeit_roh,
        "notiz": (daten.get("notiz") or "").strip()[:2000],
    }, fehler


def uhr(zeitstempel: str | None) -> str:
    """Für die Formularfelder: '2026-08-29 08:30' -> '08:30'."""
    return zeitstempel[11:16] if zeitstempel else ""
