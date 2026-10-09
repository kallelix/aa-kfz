"""Mails an Helfer (Lastenheft 2.4, C-01: E-Mail ist der Pflichtkanal).

Reiner Text wie in Kennzeichen und Presse – das kommt durch Spamfilter
besser durch. Jede Vorlage gibt (typ, empfänger, betreff, text) zurück; die
Route reiht das in mail_out ein, verschickt wird vom Worker (versand.py).

Die Links kommen fertig herein, absolut – gebaut werden sie in main.py aus
BASIS_URL. Der Ton ist der der Seiten: du, kurz, danke.
"""

from __future__ import annotations

from datetime import datetime

from kern import mail as kern_mail

from . import config

NichtEingerichtet = kern_mail.NichtEingerichtet


def senden(empfaenger: str, betreff: str, text: str) -> None:
    kern_mail.senden(config, empfaenger, betreff, text)


def _vorname(person) -> str:
    return person["vorname"] or person["name"]


def _fuss() -> str:
    zeilen = ["", "Danke, dass du mithilfst!", config.KONTAKT_NAME]
    kontakt = [teil for teil in (config.KONTAKT_MAIL, config.KONTAKT_TELEFON) if teil]
    if kontakt:
        zeilen.append(" · ".join(kontakt))
    return "\n".join(zeilen)


def _zeit(beginn: str, ende: str) -> str:
    """'Fr 02.07. 07:00–12:00'."""
    try:
        tag = datetime.fromisoformat(beginn)
    except ValueError:
        return f"{beginn}–{ende[11:16]}"
    return (config.WOCHENTAGE[tag.weekday()][:2] + tag.strftime(" %d.%m. %H:%M")
            + "–" + ende[11:16])


def schichten_text(eintraege) -> str:
    """Die Schichten je Person, wie anmeldung_laden sie liefert. Mehr als eine
    Person: mit Namen darüber."""
    zeilen = []
    mehrere = len(eintraege) > 1
    for eintrag in eintraege:
        if mehrere:
            zeilen.append(("Du" if not zeilen else _vorname(eintrag["person"])) + ":")
        for s in eintrag["schichten"]:
            ort = s["ort"] or s["treffpunkt"]
            zeile = f"  {_zeit(s['beginn'], s['ende'])}  {s['bereich']}"
            if ort:
                zeile += f", Treffpunkt: {ort}"
            if s["art"] == "reserve":
                zeile += " (Reserve)"
            zeilen.append(zeile)
        for f in eintrag["fenster"]:
            zeilen.append(f"  {_zeit(f['beginn'], f['ende'])}  Springer")
        if not eintrag["schichten"] and not eintrag["fenster"]:
            zeilen.append("  (noch keine Schicht)")
    return "\n".join(zeilen)


def bestaetigen(person, va_text: str, eintraege, link: str, code: str) -> tuple:
    """Gleich nach der Anmeldung (I-03): Link und Code."""
    text = "\n".join([
        f"Hallo {_vorname(person)},",
        "",
        f"danke für deine Anmeldung zu {va_text}!",
        "",
        "Bitte bestätige noch kurz deine Mailadresse – dann steht alles fest:",
        "",
        f"  {link}",
        "",
        f"Oder gib auf der Seite nach der Anmeldung diesen Code ein: {code}",
        "",
        f"Bis dahin halten wir deine Plätze {config.BESTAETIGEN_FRIST_STUNDEN} Stunden frei.",
        "",
        "Deine Auswahl:",
        schichten_text(eintraege),
        "",
        "Warst du das nicht? Dann ignoriere diese Mail einfach – ohne Bestätigung",
        "geben wir die Plätze wieder frei und löschen die Angaben.",
        _fuss(),
    ])
    return ("bestaetigen", person["email"], "Bitte bestätige deine Anmeldung", text)


def erinnerung(person, va_text: str, link: str, code: str, stunden: int) -> tuple:
    text = "\n".join([
        f"Hallo {_vorname(person)},",
        "",
        f"deine Anmeldung zu {va_text} ist noch nicht bestätigt.",
        f"Ein Klick genügt – sonst geben wir deine Plätze in etwa {stunden} Stunden",
        "wieder frei:",
        "",
        f"  {link}",
        "",
        f"Oder der Code: {code}",
        _fuss(),
    ])
    return ("erinnerung", person["email"], "Erinnerung: Bitte bestätige deine Anmeldung", text)


def verfallen(person, va_text: str, anmeldung: str) -> tuple:
    text = "\n".join([
        f"Hallo {_vorname(person)},",
        "",
        f"deine Anmeldung zu {va_text} wurde nicht bestätigt. Wir haben die",
        "Plätze deshalb wieder freigegeben und deine Angaben gelöscht.",
        "",
        "Möchtest du doch mithelfen? Hier geht es zur Anmeldung:",
        "",
        f"  {anmeldung}",
        _fuss(),
    ])
    return ("verfallen", person["email"], "Deine Anmeldung ist verfallen", text)


def bestaetigt(person, va_text: str, eintraege, platz: str, kalender: str) -> tuple:
    """A-10: die Bestätigung mit dem persönlichen Link und dem Kalender-Abo."""
    text = "\n".join([
        f"Hallo {_vorname(person)},",
        "",
        f"du bist dabei – {va_text}. Das hast du eingetragen:",
        "",
        schichten_text(eintraege),
        "",
        "Bitte sei 15 Minuten vor Beginn am Treffpunkt.",
        "",
        "Dein Helferplatz – dort siehst du alles und nimmst Schichten dazu:",
        f"  {platz}",
        "",
        "Kalender abonnieren (aktualisiert sich selbst, wenn sich etwas ändert):",
        f"  {kalender}",
        "",
        "Bewahre diese Mail auf – der Link ist dein Zugang, ein Passwort gibt es nicht.",
        _fuss(),
    ])
    return ("bestaetigt", person["email"], "Du bist dabei!", text)


def link(person, platz: str, dazu: str = "") -> tuple:
    """A-11: wer schon da ist, bekommt seinen Link statt einer zweiten
    Anmeldung – oder hat ihn angefordert."""
    zeilen = [
        f"Hallo {_vorname(person)},",
        "",
        "hier ist dein persönlicher Link zu Mein Helferplatz:",
        "",
        f"  {platz}",
    ]
    if dazu:
        zeilen += [
            "",
            "Die Schichten, die du gerade ausgesucht hast, sind hier schon vorgemerkt –",
            "ein Klick, und sie sind eingetragen:",
            "",
            f"  {dazu}",
        ]
    zeilen += [
        "",
        "Hast du keinen Link angefordert? Dann ignoriere diese Mail einfach.",
        _fuss(),
    ]
    return ("link", person["email"], "Dein Link zu Mein Helferplatz", "\n".join(zeilen))


def dazu(person, va_text: str, eintraege, platz: str) -> tuple:
    """Nach dem Dazunehmen in Mein Helferplatz (C-01: Änderungen)."""
    text = "\n".join([
        f"Hallo {_vorname(person)},",
        "",
        f"neu eingetragen für {va_text}:",
        "",
        schichten_text(eintraege),
        "",
        "Alles auf einen Blick:",
        f"  {platz}",
        _fuss(),
    ])
    return ("dazu", person["email"], "Neue Schicht eingetragen", text)
