"""Der Hilferuf (Lastenheft 3.4: C-03, C-04, A-12).

Ohne Datenbank und ohne Web, wie planung.py und selbstanmeldung.py: wer zu
welcher knappen Schicht passt, der Text für die Ankündigungsgruppe und der
kurze Link auf eine Schicht. Geholt und gespeichert wird in db.py,
gerufen in main.py.

Passend heißt (C-03, K-06): die Person ist zu der Zeit noch frei, steht
nicht schon auf der Schicht oder ihrer Warteliste, ihre Zeiten und
Vorlieben passen – soweit sie welche angegeben hat –, sie ist alt genug,
und keine Einsatzgrenze steht dagegen.
"""

from __future__ import annotations

from datetime import date, datetime
from urllib.parse import quote

from . import config, selbstanmeldung

# C-04: so lange nach einem Hilferuf gibt es für dieselbe Schicht keinen
# zweiten per Mail.
SPERRE_STUNDEN = 24

_ZEICHEN = "0123456789abcdefghijklmnopqrstuvwxyz"


def kurz(schicht_id: int) -> str:
    """A-12: die Nummer einer Schicht, kurz für WhatsApp – 7 wird '7',
    1000 wird 'rs'."""
    zeichen = ""
    while True:
        schicht_id, rest = divmod(schicht_id, 36)
        zeichen = _ZEICHEN[rest] + zeichen
        if not schicht_id:
            return zeichen


def nummer(roh: str) -> int | None:
    roh = (roh or "").lower()
    if not roh or len(roh) > 8 or any(z not in _ZEICHEN for z in roh):
        return None
    return int(roh, 36)


def _alter(person, stichtag: date) -> int | None:
    """Wie alt die Person mindestens ist – None, wenn wir es nicht wissen."""
    if person["geburtsdatum"]:
        return selbstanmeldung.alter_am(date.fromisoformat(person["geburtsdatum"]), stichtag)
    return {1: 18, 0: 17}.get(person["volljaehrig"])


def passend(kandidat: dict, schichten: list[dict], stichtag: date) -> list[dict]:
    """Die Schichten, die zu dieser Person passen. `kandidat` kommt aus
    db.hilferuf_kandidaten: die Person, ihre Einteilungen und Wartelisten in
    dieser Veranstaltung, ihre Zeiten, Vorlieben und Grenzen."""
    spannen = selbstanmeldung.vereinen(kandidat["fenster"])
    alter = _alter(kandidat["person"], stichtag)
    treffer = []
    for s in schichten:
        if s["id"] in kandidat["gesperrt"] or s["id"] in kandidat["warteliste"]:
            continue
        if any(b_id == s["id"] or selbstanmeldung.ueberschneiden(b, e, s["beginn"], s["ende"])
               for b, e, b_id in kandidat["belegt"]):
            continue
        if spannen and not selbstanmeldung.passt_zur_zeit(s["beginn"], s["ende"], spannen):
            continue
        if not selbstanmeldung.passt_zu_vorlieben(s.get("vorlieben") or [], kandidat["vorlieben"]):
            continue
        if s.get("alter_ab") and alter is not None and alter < s["alter_ab"]:
            continue
        treffer.append(s)
    return treffer


def zeit(s) -> str:
    """'Fr 02.07. 08:00–13:00'."""
    tag = datetime.fromisoformat(s["beginn"])
    return (config.WOCHENTAGE[tag.weekday()][:2] + tag.strftime(" %d.%m. %H:%M")
            + "–" + s["ende"][11:16])


def frei_text(s) -> str:
    if s["lage"] == "frei":
        return f"noch {s['frei']} frei"
    return "als Reserve"


def whatsapp_text(va_name: str, schichten: list[dict], link) -> str:
    """C-03 (b): der Text für die Ankündigungsgruppe der Community, je
    Schicht mit ihrem kurzen Link (A-12). `link(schicht_id)` baut ihn."""
    zeilen = [f"Wir brauchen Hilfe bei {va_name}!", ""]
    for s in schichten:
        zeilen += [f"{zeit(s)} · {s['bereich']} · {frei_text(s)}", link(s["id"]), ""]
    zeilen.append("Ein Klick auf den Link, und du bist dabei. Danke!")
    return "\n".join(zeilen)


def whatsapp_link(text: str) -> str:
    """C-06: ein gewöhnlicher Link, der WhatsApp mit dem Text öffnet – kein
    Skript von WhatsApp oder Meta."""
    return "https://wa.me/?text=" + quote(text)
