"""Mailvorlagen und Versand.

Alles reiner Text – kein HTML, keine Bilder. Das kommt durch Spamfilter besser
durch.

Verschickt wird nie im Request: die Route reiht in `mail_out` ein, der Worker
holt es ab. Wenn der SMTP hängt, hängt sonst das Formular.

Der Versandteil unten ist wörtlich derselbe wie in der Kennzeichen-App – er ist
der erste Kandidat für den gemeinsamen Kern, sobald beide Anwendungen stehen.
"""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr

from . import config


class NichtEingerichtet(Exception):
    """SMTP_HOST oder MAIL_FROM fehlen – es wird nichts verschickt."""


# --- Vorlagen ---------------------------------------------------------------
#
# Wortlaut nach der bisherigen Infomail der Orga, nur auf die getroffene Wahl
# zugeschnitten. Der Sicherheitshinweis steht bewusst doppelt: im Formular zum
# Anhaken und hier zum Nachlesen.


def _fuss() -> str:
    zeilen = ["", "Sportliche Grüße", config.KONTAKT_NAME]
    kontakt = [teil for teil in (config.KONTAKT_MAIL, config.KONTAKT_TELEFON) if teil]
    if kontakt:
        zeilen.append(" · ".join(kontakt))
    return "\n".join(zeilen)


def _daten(anmeldung) -> str:
    zeilen = [
        f"  Anmeldenummer: {anmeldung['id']}",
        f"  Name:          {anmeldung['vorname']} {anmeldung['nachname']}",
        f"  Firma:         {anmeldung['firma']}",
    ]
    if anmeldung["telefon"]:
        zeilen.append(f"  Telefon:       {anmeldung['telefon']}")
    return "\n".join(zeilen)


def _akkreditierung(anmeldung) -> list:
    """Der Absatz, der sich je nach Wahl unterscheidet."""
    if anmeldung["gegenleistung"] == "gebuehr":
        return [
            f"  Nutzung:       kommerziell",
            f"  Akkreditierung: {config.gebuehr()} Gebühr",
            "",
            f"Die Gebühr wird bar bei der Abholung am {config.ABHOLORT} bezahlt –"
            " bitte passend mitbringen.",
        ]
    if anmeldung["gegenleistung"] == "bilderspende":
        return [
            f"  Nutzung:       kommerziell",
            f"  Akkreditierung: ca. {config.BILDER_ANZAHL} Bilder als Spende",
            "",
            "Interessiert sind wir dabei vor allem an emotionalen"
            " Stimmungsbildern, aber auch an Aufnahmen von 1–2 Fahrern unserer"
            " Wahl, die wir im Nachgang auf eurer Vertriebsplattform auswählen"
            " können.",
            "",
            "Die gespendeten Bilder nutzen wir für die zukünftige Promotion der"
            " Veranstaltung – vor allem für Social Media, Print und Merch. Eine"
            " Verlinkung auf Social Media ist dabei, wenn gewünscht,"
            " selbstverständlich möglich.",
        ]
    return [
        "  Nutzung:       nicht kommerziell",
        "  Akkreditierung: keine Gebühr",
    ]


SICHERHEIT = (
    "Wichtiger Hinweis\n"
    "\n"
    "Durch das Presse-Badge hast du keine Sonderrechte, was das Betreten der"
    " abgesperrten Bereiche betrifft. Dies gilt insbesondere für die Strecke"
    " und die ausgewiesenen Sturzzonen. Bitte halte dich aus Sicherheitsgründen"
    " unbedingt an die Absperrungen und die Anweisungen des"
    " Veranstaltungspersonals."
)


def vorlage_eingang(anmeldung) -> tuple:
    betreff = f"Presse-Akkreditierung {anmeldung['id']} – {config.VERANSTALTUNG}"
    ort = f" in {config.ORT}" if config.ORT else ""

    zeilen = [
        f"Hallo {anmeldung['vorname']},",
        "",
        f"vielen Dank für dein Interesse, {config.VERANSTALTUNG}{ort} mit Fotos"
        " und Videos zu begleiten – wir freuen uns über deine Anfrage!",
        "",
        "Deine Anmeldung ist bei uns angekommen:",
        "",
        _daten(anmeldung),
    ]
    zeilen.extend(_akkreditierung(anmeldung))
    zeilen.extend([
        "",
        "Ablauf vor Ort",
        "",
        f"Melde dich bitte am {config.ABHOLORT} mit deinen Kontaktdaten – dort"
        " erhältst du dein Presse-Badge. Das Presse-Badge ist für die"
        " kommerzielle Verwertung deines Contents obligatorisch.",
        "",
        SICHERHEIT,
        "",
        "Bei Fragen melde dich gerne jederzeit.",
        "",
        "Wir freuen uns auf euch und eure Bilder!",
        _fuss(),
    ])
    return ("eingang", anmeldung["email"], betreff, "\n".join(zeilen))


def vorlage_erinnerung(anmeldung) -> tuple:
    betreff = f"Deine Bilder von {config.VERANSTALTUNG}"

    if config.BILDER_ABGABE:
        abgabe = f"Schick sie uns bitte hierhin: {config.BILDER_ABGABE}"
    else:
        # Solange BILDER_ABGABE nicht gesetzt ist, wird kein Weg erfunden.
        abgabe = "Antworte einfach auf diese Mail, dann klären wir den Weg."

    zeilen = [
        f"Hallo {anmeldung['vorname']},",
        "",
        f"danke, dass du {config.VERANSTALTUNG} begleitet hast!",
        "",
        f"Du hattest dich für die Bilderspende entschieden – ca."
        f" {config.BILDER_ANZAHL} Bilder statt der Akkreditierungsgebühr."
        " Die stehen noch aus.",
        "",
        abgabe,
        "",
        "Am liebsten emotionale Stimmungsbilder, dazu gern Aufnahmen von 1–2"
        " Fahrern unserer Wahl.",
        "",
        f"  Anmeldenummer: {anmeldung['id']}",
        "",
        "Falls du sie schon geschickt hast: danke, dann hat sich diese Mail"
        " überschnitten.",
        _fuss(),
    ]
    return ("erinnerung", anmeldung["email"], betreff, "\n".join(zeilen))


def fuer(anmeldung, typ: str) -> tuple | None:
    """Vorlage nach Typ – oder None, wenn sie nicht passt."""
    if not (anmeldung["email"] or "").strip():
        return None
    if typ == "eingang":
        return vorlage_eingang(anmeldung)
    if typ == "erinnerung" and anmeldung["gegenleistung"] == "bilderspende":
        return vorlage_erinnerung(anmeldung)
    return None



# --- Versand ----------------------------------------------------------------


def _verbindung():
    if config.SMTP_TLS == "ssl":
        return smtplib.SMTP_SSL(
            config.SMTP_HOST,
            config.SMTP_PORT,
            timeout=config.SMTP_TIMEOUT,
            context=ssl.create_default_context(),
        )
    return smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=config.SMTP_TIMEOUT)


def senden(empfaenger: str, betreff: str, body: str) -> None:
    """Verschickt eine Mail. Wirft bei jedem Fehler – der Worker zählt hoch."""
    if not config.MAIL_AKTIV:
        raise NichtEingerichtet("SMTP_HOST oder MAIL_FROM fehlt")

    nachricht = EmailMessage()
    nachricht["From"] = config.MAIL_FROM
    nachricht["To"] = empfaenger
    nachricht["Subject"] = betreff
    nachricht["Date"] = formatdate(localtime=True)
    _, absenderadresse = parseaddr(config.MAIL_FROM)
    bereich = absenderadresse.partition("@")[2] or None
    nachricht["Message-ID"] = make_msgid(domain=bereich)
    if config.MAIL_REPLY_TO:
        nachricht["Reply-To"] = config.MAIL_REPLY_TO
    # Automatische Antworten und Abwesenheitsnotizen unterbinden.
    nachricht["Auto-Submitted"] = "auto-generated"
    nachricht.set_content(body)

    with _verbindung() as smtp:
        if config.SMTP_TLS == "starttls":
            smtp.starttls(context=ssl.create_default_context())
        if config.SMTP_USER:
            smtp.login(config.SMTP_USER, config.SMTP_PASS)
        smtp.send_message(nachricht)
