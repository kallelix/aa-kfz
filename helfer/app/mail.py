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
        for s in eintrag.get("warteliste", []):
            zeilen.append(f"  {_zeit(s['beginn'], s['ende'])}  {s['bereich']} (Warteliste)")
        if not eintrag["schichten"] and not eintrag["fenster"] and not eintrag.get("warteliste"):
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


# --- Anmeldestart (Lastenheft 3.3: C-08) ------------------------------------

def anmeldung_offen(email: str, vorname: str, va_text: str, anmeldung: str) -> tuple:
    """An alle, die Interesse vorgemerkt haben (V-02) – einmal."""
    text = "\n".join([
        f"Hallo {vorname}," if vorname else "Hallo,",
        "",
        f"die Anmeldung für {va_text} ist offen. Du wolltest Bescheid",
        "bekommen – hier geht es los:",
        "",
        f"  {anmeldung}",
        "",
        "Deine Adresse haben wir damit wieder gelöscht.",
        _fuss(),
    ])
    return ("anmeldestart", email, "Die Anmeldung ist offen", text)


def einladung(person, va_text: str, schichten: str, platz: str) -> tuple:
    """An den Helferstamm (D-03): die Angaben sind schon da, es fehlen nur
    die Schichten."""
    text = "\n".join([
        f"Hallo {_vorname(person)},",
        "",
        f"die Anmeldung für {va_text} ist offen – und wir würden uns",
        "freuen, wenn du wieder dabei bist!",
        "",
        "Deine Angaben haben wir noch. Such dir einfach Schichten aus:",
        "",
        f"  {schichten}",
        "",
        "Keine Zeit diesmal? Dann ignoriere diese Mail einfach.",
        "Keine Einladungen mehr? Das stellst du in Mein Helferplatz ab:",
        "",
        f"  {platz}",
        _fuss(),
    ])
    return ("einladung", person["email"], "Die Anmeldung ist offen – bist du wieder dabei?", text)


# --- Selbstbedienung (Lastenheft 2.5) ---------------------------------------

def abgesagt(person, va_text: str, zeilen: list[str], platz: str) -> tuple:
    """S-01: die Seite bedankt sich für die Absage, die Mail auch."""
    text = "\n".join([
        f"Hallo {_vorname(person)},",
        "",
        f"danke, dass du Bescheid sagst! Für {va_text} ist abgesagt:",
        "",
        *[f"  {z}" for z in zeilen],
        "",
        "Wer absagt, statt einfach nicht zu kommen, hilft uns sehr.",
        "Deine übrigen Schichten und alles Weitere:",
        f"  {platz}",
        _fuss(),
    ])
    return ("abgesagt", person["email"], "Abgesagt – danke für Bescheid", text)


def getauscht(person, va_text: str, alt: str, neu: str, platz: str) -> tuple:
    text = "\n".join([
        f"Hallo {_vorname(person)},",
        "",
        f"getauscht für {va_text}:",
        "",
        f"  statt {alt}",
        f"  jetzt {neu}",
        "",
        "Alles auf einen Blick:",
        f"  {platz}",
        _fuss(),
    ])
    return ("getauscht", person["email"], "Schicht getauscht", text)


def abgemeldet(person, va_text: str, namen: list[str]) -> tuple:
    wer = "dich" if namen == [_vorname(person)] else ", ".join(namen)
    text = "\n".join([
        f"Hallo {_vorname(person)},",
        "",
        f"wir haben {wer} von {va_text} abgemeldet. Danke, dass du Bescheid sagst –",
        "vielleicht klappt es beim nächsten Mal!",
        _fuss(),
    ])
    return ("abgemeldet", person["email"], "Abgemeldet", text)


def angebot(person, fuer: str, schicht_text: str, bis: str, platz: str) -> tuple:
    """R-04: ein Platz von der Warteliste, mit Frist."""
    wer = "dich" if fuer == _vorname(person) else fuer
    text = "\n".join([
        f"Hallo {_vorname(person)},",
        "",
        f"gute Nachricht: In {schicht_text} ist ein Platz frei geworden – wir halten",
        f"ihn für {wer} bis {bis}. Bitte sag in Mein Helferplatz Ja oder Nein:",
        "",
        f"  {platz}",
        "",
        "Ohne Antwort geben wir ihn an die Nächste auf der Warteliste weiter.",
        _fuss(),
    ])
    return ("angebot", person["email"], "Ein Platz ist frei geworden", text)


def neue_adresse(person, link: str) -> tuple:
    """S-04/S-06: die neue Adresse bestätigen – die Mail geht an sie."""
    text = "\n".join([
        f"Hallo {_vorname(person)},",
        "",
        "bitte bestätige, dass dies deine Adresse ist – dann schreiben wir dir",
        "künftig hierhin:",
        "",
        f"  {link}",
        "",
        "Warst du das nicht? Dann ignoriere diese Mail einfach.",
        _fuss(),
    ])
    return ("neue_adresse", person["email_neu"], "Bitte bestätige deine Adresse", text)


def geloescht(person, wartet: bool) -> tuple:
    """S-05: zum Abschied, oder warum es noch dauert."""
    if wartet:
        absatz = ["deine künftigen Schichten sind abgesagt. Löschen können wir deine",
                  "Daten erst, wenn alles zurück ist, was du ausgeliehen hast (etwa ein",
                  "Funkgerät) – danach geschieht es von selbst, samt der Unterschrift",
                  "bei der Ausgabe."]
    else:
        absatz = ["deine Daten sind gelöscht, künftige Schichten abgesagt. Danke, dass",
                  "du dabei warst – du bist jederzeit wieder willkommen!"]
    text = "\n".join([f"Hallo {_vorname(person)},", "", *absatz, _fuss()])
    return ("geloescht", person["email"], "Deine Daten", text)


def leitung_absage(empfaenger: str, abgabe: dict) -> tuple:
    """S-07: an die Bereichsleitung, sofort – bei kurzfristigen Absagen und
    wenn die Schicht unter ihr Minimum fällt."""
    s = abgabe["schicht"]
    zeilen = [
        "Hallo,",
        "",
        f"{abgabe['person']['name']} hat abgesagt: {s['text']}.",
    ]
    if abgabe.get("grund"):
        zeilen.append(f"Grund: {abgabe['grund']}")
    zeilen += ["", f"Jetzt fest eingeplant: {abgabe['fest']} – Minimum {s['minimum']}, Soll {s['soll']}."]
    if abgabe["unter_minimum"]:
        zeilen.append("Damit ist die Schicht unter ihrem Minimum.")
    if abgabe["kurzfristig"]:
        zeilen.append("Die Absage ist kurzfristig – sie steht auch oben in der Übersicht.")
    if abgabe["angebote"]:
        zeilen.append("Der Platz ist der Warteliste angeboten.")
    zeilen += ["", "Die Helferplanung"]
    betreff = ("Kurzfristige Absage: " if abgabe["kurzfristig"] else "Absage: ") + s["text"]
    return ("leitung", empfaenger, betreff, "\n".join(zeilen))


# --- Einverständnis der Eltern (Lastenheft 2.9, D-06) ----------------------

def _eltern_gruss(kind) -> str:
    return f"Hallo {kind['eltern_name']}," if kind["eltern_name"] else "Hallo,"


def eltern(kind, va_text: str, eintraege, link: str, angemeldet_von: str = "") -> tuple:
    """An die erziehungsberechtigte Person – erst mit ihrem Klick gilt die
    Anmeldung."""
    wer = _vorname(kind)
    text = "\n".join([
        _eltern_gruss(kind),
        "",
        f"{kind['name']} möchte bei {va_text} mithelfen"
        + (f" – angemeldet von {angemeldet_von}" if angemeldet_von else "")
        + " – und hat dich als erziehungsberechtigte Person angegeben.",
        "",
        "Eingetragen ist:",
        schichten_text(eintraege),
        "",
        f"Bist du einverstanden, dass {wer} mithilft? Dann bestätige es bitte hier:",
        "",
        f"  {link}",
        "",
        f"Ohne dein Einverständnis geben wir die Plätze nach {config.BESTAETIGEN_FRIST_STUNDEN}"
        " Stunden wieder frei und löschen die Angaben.",
        "Fragen zum Einsatz beantworten wir gern – die Kontaktdaten stehen unten.",
        _fuss(),
    ])
    return ("eltern", kind["eltern_email"], f"Einverständnis: {wer} hilft mit", text)


def eltern_verfallen(empfaenger, kind_name: str, va_text: str, anmeldung: str) -> tuple:
    """An die Person, die angemeldet hat: ohne Einverständnis keine Plätze."""
    text = "\n".join([
        f"Hallo {_vorname(empfaenger)},",
        "",
        f"für {kind_name} ist das Einverständnis der Eltern zu {va_text} nicht",
        "gekommen. Die Plätze sind deshalb wieder frei.",
        "",
        "Klappt es doch? Dann einfach neu anmelden:",
        f"  {anmeldung}",
        _fuss(),
    ])
    return ("eltern_verfallen", empfaenger["email"], "Ohne Einverständnis keine Anmeldung", text)
