"""Validierung des Akkreditierungsformulars.

Liefert immer (werte, fehler): bereinigte Werte zum Wiederanzeigen und ein
Dict feld -> Meldung. Ist `fehler` leer, darf gespeichert werden.
"""

from __future__ import annotations

import re

# Feld -> maximale Länge.
MAX_LAENGE = {
    "vorname": 80,
    "nachname": 80,
    "firma": 120,
    "email": 254,
    "telefon": 40,
    "bemerkung": 1000,
}

# Bewusst großzügig: die endgültige Prüfung ist, ob die Mail ankommt.
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")
TELEFON_RE = re.compile(r"^[0-9+()/.\s-]{5,}$")

GEGENLEISTUNGEN = ("gebuehr", "bilderspende")

# Verstecktes Feld gegen einfache Bots.
HONEYPOT = "webseite"


def _saeubern(roh: str | None) -> str:
    return re.sub(r"\s+", " ", (roh or "").replace("\r\n", "\n")).strip()


def _saeubern_mehrzeilig(roh: str | None) -> str:
    zeilen = [z.strip() for z in (roh or "").replace("\r\n", "\n").split("\n")]
    return "\n".join(zeilen).strip()


def _angehakt(formular, feld: str) -> bool:
    """Ein Häkchen kommt nur mit, wenn es gesetzt ist – der Wert ist egal."""
    return (formular.get(feld) or "").strip() != ""


def ist_bot(formular) -> bool:
    return bool((formular.get(HONEYPOT) or "").strip())


def pruefen(formular) -> tuple[dict, dict]:
    werte = {feld: _saeubern(formular.get(feld)) for feld in MAX_LAENGE}
    werte["bemerkung"] = _saeubern_mehrzeilig(formular.get("bemerkung"))
    werte["email"] = werte["email"].lower()

    kommerziell_roh = _saeubern(formular.get("kommerziell"))
    werte["kommerziell"] = kommerziell_roh == "ja"
    werte["gegenleistung"] = _saeubern(formular.get("gegenleistung"))
    werte["sicherheit"] = _angehakt(formular, "sicherheit")
    werte["bildrechte"] = _angehakt(formular, "bildrechte")

    fehler: dict[str, str] = {}

    for feld, beschriftung in (
        ("vorname", "Vorname"),
        ("nachname", "Name"),
        ("firma", "Firma"),
    ):
        if not werte[feld]:
            fehler[feld] = f"{beschriftung} bitte ausfüllen."

    # E-Mail ist hier Pflicht, anders als bei den Kennzeichen: an ihr hängen
    # die bestätigten Bedingungen, sie muss also ankommen.
    if not werte["email"]:
        fehler["email"] = "Bitte eine E-Mail-Adresse angeben – dorthin geht die Bestätigung."
    elif not EMAIL_RE.match(werte["email"]):
        fehler["email"] = "Das sieht nicht nach einer E-Mail-Adresse aus."

    if werte["telefon"] and not TELEFON_RE.match(werte["telefon"]):
        fehler["telefon"] = "Bitte nur Ziffern und die Zeichen + ( ) / - verwenden."

    if kommerziell_roh not in ("ja", "nein"):
        fehler["kommerziell"] = "Bitte angeben, ob die Aufnahmen kommerziell verwertet werden."

    if werte["kommerziell"]:
        if not werte["gegenleistung"]:
            fehler["gegenleistung"] = "Bitte eine der beiden Möglichkeiten wählen."
        elif werte["gegenleistung"] not in GEGENLEISTUNGEN:
            fehler["gegenleistung"] = "Unbekannte Auswahl."
    else:
        # Wer nicht kommerziell verwertet, zahlt nichts und spendet nichts.
        # Eine mitgeschickte Auswahl wird verworfen statt bemängelt – sie kann
        # schlicht aus einem vorherigen Versuch stehengeblieben sein.
        werte["gegenleistung"] = ""
        werte["bildrechte"] = False

    if not werte["sicherheit"]:
        fehler["sicherheit"] = "Ohne Bestätigung des Sicherheitshinweises geht es nicht."

    if werte["gegenleistung"] == "bilderspende" and not werte["bildrechte"]:
        fehler["bildrechte"] = "Für die Bilderspende brauchen wir deine Zustimmung zur Nutzung."

    for feld, grenze in MAX_LAENGE.items():
        if len(werte[feld]) > grenze:
            fehler[feld] = f"Bitte auf {grenze} Zeichen kürzen."

    return werte, fehler
