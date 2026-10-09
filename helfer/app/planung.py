"""Bereiche, Schichten und Goodies pflegen (Lastenheft V-03 bis V-07).

Prüfen und Umformen der Formularwerte – ohne Datenbank, ohne Web, wie in
eintraege.py. Jede Funktion gibt (Werte, Fehler) zurück; Fehler ist leer,
wenn alles passt, sonst steht je Feld ein Satz für den Menschen.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from . import normalisieren, selbstanmeldung
from .eintraege import _uhrzeit

# Welche Schwelle ein Goodie hat.
SCHWELLEN = {"schichten": "Schichten", "stunden": "Stunden"}


def _zahl(roh, feld: str, fehler: dict, kleinste: int = 0,
          groesste: int = 999, leer=None):
    """Eine ganze Zahl aus dem Formular. Leer gibt `leer` zurück."""
    text = normalisieren.text(roh)
    if not text:
        return leer
    try:
        wert = int(text)
    except ValueError:
        fehler[feld] = "Bitte eine ganze Zahl."
        return leer
    if not kleinste <= wert <= groesste:
        fehler[feld] = "Bitte eine Zahl von %d bis %d." % (kleinste, groesste)
        return leer
    return wert


def _haken(roh) -> int:
    return 1 if normalisieren.text(roh) in ("1", "on", "ja") else 0


def voraussetzungen(text: str) -> list[str]:
    """Eine je Zeile; Leerzeilen zählen nicht."""
    return [z for z in (normalisieren.text(z) for z in (text or "").splitlines()) if z]


def bereich_pruefen(daten: dict) -> tuple[dict, dict]:
    fehler: dict[str, str] = {}
    name = normalisieren.text(daten.get("name"))[:80]
    if not name:
        fehler["name"] = "Ohne Namen lässt sich der Bereich nicht wiederfinden."
    werte = {
        "name": name,
        "beschreibung": (daten.get("beschreibung") or "").strip()[:2000],
        "treffpunkt": normalisieren.text(daten.get("treffpunkt"))[:200],
        "mindestalter": _zahl(daten.get("mindestalter"), "mindestalter", fehler, 1, 99),
        "voraussetzungen": "\n".join(z[:200] for z in voraussetzungen(
            str(daten.get("voraussetzungen") or "")))[:2000],
        "intern": _haken(daten.get("intern")),
        # A-03: wozu der Bereich passt, für die Vorschläge des Assistenten.
        "vorlieben": [k for k, *_ in selbstanmeldung.VORLIEBEN
                      if _haken(daten.get("vorliebe-" + k))],
    }
    return werte, fehler


def schicht_pruefen(daten: dict) -> tuple[dict, dict]:
    """Tag und zwei Uhrzeiten werden zu vollen Zeitstempeln. Endet die
    Schicht früher, als sie beginnt, läuft sie über Mitternacht."""
    fehler: dict[str, str] = {}

    datum = normalisieren.datum(daten.get("datum"))
    if datum is None:
        fehler["datum"] = ("Das Datum ist nicht lesbar (erwartet: 2027-07-02)."
                           if normalisieren.text(daten.get("datum"))
                           else "Bitte den Tag angeben.")

    von = _uhrzeit(daten.get("beginn", ""))
    bis = _uhrzeit(daten.get("ende", ""))
    if not von:
        fehler["beginn"] = "Bitte eine Uhrzeit (z. B. 08:30)."
    if not bis:
        fehler["ende"] = "Bitte eine Uhrzeit (z. B. 13:00)."
    if von and bis and von == bis:
        fehler["ende"] = "Beginn und Ende sind gleich."

    beginn = ende = None
    if datum is not None and von and bis and von != bis:
        beginn = datum.isoformat() + " " + von
        tag = datum if bis > von else datum + timedelta(days=1)
        ende = tag.isoformat() + " " + bis

    soll = _zahl(daten.get("soll"), "soll", fehler, 1, 500)
    if soll is None and "soll" not in fehler:
        fehler["soll"] = "Wie viele Leute sind geplant?"
    # Ohne eigene Angabe ist das Minimum das Soll: alles Geplante wird
    # gebraucht. So rechnete auch das alte Tool.
    minimum = _zahl(daten.get("minimum"), "minimum", fehler, 0, 500, leer=soll)
    if soll is not None and minimum is not None and minimum > soll:
        fehler["minimum"] = "Das Minimum liegt über dem Soll."
    reserve = _zahl(daten.get("reserve"), "reserve", fehler, 0, 500, leer=0)

    werte = {
        "datum": datum.isoformat() if datum else None,
        "beginn": beginn,
        "ende": ende,
        "minimum": minimum if minimum is not None else 0,
        "soll": soll or 0,
        "reserve": reserve or 0,
        "mindestalter": _zahl(daten.get("mindestalter"), "mindestalter", fehler, 1, 99),
        "ort": normalisieren.text(daten.get("ort"))[:200],
        "hinweis": (daten.get("hinweis") or "").strip()[:1000],
        "intern": _haken(daten.get("intern")),
    }
    return werte, fehler


def goodie_pruefen(daten: dict) -> tuple[dict, dict]:
    fehler: dict[str, str] = {}
    name = normalisieren.text(daten.get("name"))[:120]
    if not name:
        fehler["name"] = "Was gibt es?"
    art = normalisieren.text(daten.get("schwelle_art"))
    if art not in SCHWELLEN:
        art = "schichten"
    schwelle = _zahl(daten.get("schwelle"), "schwelle", fehler, 1, 99)
    if schwelle is None and "schwelle" not in fehler:
        fehler["schwelle"] = "Ab wie vielen " + SCHWELLEN[art] + "?"
    mindestalter = _zahl(daten.get("mindestalter"), "mindestalter", fehler, 1, 99)
    alternative = normalisieren.text(daten.get("alternative"))[:120]
    if alternative and mindestalter is None:
        fehler["alternative"] = "Eine Alternative braucht ein Mindestalter – sonst bekommt sie niemand."
    werte = {
        "name": name,
        "ab_schichten": schwelle if art == "schichten" else None,
        "ab_stunden": schwelle if art == "stunden" else None,
        "mindestalter": mindestalter,
        "alternative": alternative,
    }
    return werte, fehler


def verschieben(zeitpunkt: str, tage: int) -> str:
    """'2026-08-29 08:00' um ganze Tage verschieben; ein reines Datum auch."""
    if len(zeitpunkt) == 10:
        return (date.fromisoformat(zeitpunkt) + timedelta(days=tage)).isoformat()
    return (datetime.fromisoformat(zeitpunkt)
            + timedelta(days=tage)).strftime("%Y-%m-%d %H:%M")
