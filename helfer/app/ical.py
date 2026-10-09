"""Das Kalender-Abo (Lastenheft 2.4, A-10).

Ein Abo statt einer einmaligen Datei: das Kalenderprogramm fragt den Link
regelmäßig ab und sieht so jede Änderung – eine stornierte Schicht
verschwindet, eine neue kommt dazu. Zeiten in UTC, dann rechnet jedes
Programm richtig, ohne dass eine Zeitzonenbeschreibung mitgeliefert werden
muss.

Bewusst ohne den Link zu Mein Helferplatz: der Kalenderlink darf nur lesen,
und wer ihn hat – etwa, weil ein Kalender geteilt ist –, soll nicht mehr
können.
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from . import config


def _text(roh: str) -> str:
    return (roh.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r\n", "\\n").replace("\n", "\\n"))


def _falten(zeile: str) -> str:
    """Zeilen über 75 Byte werden umbrochen, die Fortsetzung beginnt mit
    einem Leerzeichen (RFC 5545, 3.1)."""
    teile, rest, grenze = [], zeile, 75
    while len(rest.encode("utf-8")) > grenze:
        schnitt = grenze
        while len(rest[:schnitt].encode("utf-8")) > grenze:
            schnitt -= 1
        teile.append(rest[:schnitt])
        rest = rest[schnitt:]
        grenze = 74
    teile.append(rest)
    return "\r\n ".join(teile)


def _utc(lokal: str) -> str:
    zeitpunkt = datetime.fromisoformat(lokal).replace(tzinfo=ZoneInfo(config.ZEITZONE))
    return zeitpunkt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def kalender(eintraege, person) -> str:
    """eintraege wie db.kalender(); person ist, wem das Abo gehört – die
    Schichten der Mitangemeldeten tragen deren Vornamen."""
    jetzt = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    zeilen = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//ILRC//Helferplanung//DE",
              "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
              "X-WR-CALNAME:" + _text("Meine Helferschichten"),
              "REFRESH-INTERVAL;VALUE=DURATION:PT6H", "X-PUBLISHED-TTL:PT6H"]
    for e in eintraege:
        try:
            beginn, ende = _utc(e["beginn"]), _utc(e["ende"])
        except ValueError:
            continue
        titel = f"{e['bereich']} – {e['kurz']}"
        if e["helfer_id"] != person["id"]:
            titel += f" ({e['vorname'] or e['name']})"
        if e["art"] == "reserve":
            titel += " (Reserve)"
        zeilen += ["BEGIN:VEVENT", f"UID:helfer-{e['uid']}@abfahrt", f"DTSTAMP:{jetzt}",
                   f"DTSTART:{beginn}", f"DTEND:{ende}", "SUMMARY:" + _text(titel)]
        if e["ort"]:
            zeilen.append("LOCATION:" + _text(e["ort"]))
        zeilen += ["DESCRIPTION:" + _text("Bitte sei 15 Minuten vor Beginn am Treffpunkt."),
                   "END:VEVENT"]
    zeilen.append("END:VCALENDAR")
    return "\r\n".join(_falten(z) for z in zeilen) + "\r\n"
