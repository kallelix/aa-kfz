"""Mailvorlagen und Versand.

Alles reiner Text – kein HTML, keine Bilder. Das kommt durch Spamfilter besser
durch und ist bei drei Vorlagen auch schlicht weniger Arbeit.

Verschickt wird nie im Request: die Route reiht in `mail_out` ein, der Worker
holt es ab. Wenn der SMTP hängt, hängt sonst das Formular.
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


def _anrede(antrag) -> str:
    return f"Hallo {antrag['vorname']} {antrag['nachname']},"


def _kategorie(antrag) -> str:
    return config.KATEGORIE_LABELS.get(antrag["kategorie"], antrag["kategorie"])


def _fuss() -> str:
    zeilen = ["", "Viele Grüße", config.KONTAKT_NAME]
    kontakt = [teil for teil in (config.KONTAKT_MAIL, config.KONTAKT_TELEFON) if teil]
    if kontakt:
        zeilen.append(" · ".join(kontakt))
    return "\n".join(zeilen)


def _daten(antrag) -> str:
    zeilen = [
        f"  Antragsnummer: {antrag['id']}",
        f"  Name:          {antrag['vorname']} {antrag['nachname']}",
        f"  Funktion:      {antrag['funktion']}",
        f"  Kategorie:     {_kategorie(antrag)}",
    ]
    if antrag["kennzeichen"]:
        zeilen.append(f"  Kennzeichen:   {antrag['kennzeichen']}")
    if antrag["telefon"]:
        zeilen.append(f"  Telefon:       {antrag['telefon']}")
    return "\n".join(zeilen)


def vorlage_eingang(antrag) -> tuple:
    betreff = f"Antrag {antrag['id']} eingegangen – {config.VERANSTALTUNG}"
    body = "\n".join([
        _anrede(antrag),
        "",
        f"dein Antrag auf eine Durchfahrtsberechtigung für {config.VERANSTALTUNG}"
        " ist bei uns angekommen. Wir haben folgendes notiert:",
        "",
        _daten(antrag),
        "",
        "Wir prüfen den Antrag und melden uns mit der Entscheidung."
        " Stimmt etwas nicht, antworte einfach auf diese Mail.",
        _fuss(),
    ])
    return ("eingang", antrag["email"], betreff, body)


def vorlage_genehmigt(antrag) -> tuple:
    betreff = f"Antrag {antrag['id']} genehmigt – {config.VERANSTALTUNG}"
    zeilen = [
        _anrede(antrag),
        "",
        "deine Durchfahrtsberechtigung ist genehmigt:",
        "",
        _daten(antrag),
        "",
    ]
    if config.ABHOLUNG:
        zeilen.append(config.ABHOLUNG)
    else:
        # Offene Frage 4 im Plan. Ohne ABHOLUNG wird hier nichts erfunden.
        zeilen.append(
            "Wo und wann du die Karte bekommst, sagen wir dir rechtzeitig vorher."
        )
    zeilen.append("")
    zeilen.append("Bitte leg die Karte im Fahrzeug gut sichtbar aus.")
    zeilen.append(_fuss())
    return ("genehmigt", antrag["email"], betreff, "\n".join(zeilen))


def vorlage_abgelehnt(antrag, begruendung: str) -> tuple:
    betreff = f"Antrag {antrag['id']} – Rückmeldung {config.VERANSTALTUNG}"
    body = "\n".join([
        _anrede(antrag),
        "",
        "wir können deinem Antrag auf eine Durchfahrtsberechtigung leider nicht"
        " entsprechen.",
        "",
        "Begründung:",
        begruendung,
        "",
        "Wenn du das für einen Irrtum hältst, melde dich gern – dann schauen wir"
        " noch einmal drauf.",
        _fuss(),
    ])
    return ("abgelehnt", antrag["email"], betreff, body)


def vorlage_orga(antrag, empfaenger: str, basis_url: str = "") -> tuple:
    """Kurze Meldung an die Orga, dass ein Antrag eingegangen ist.

    Geht an die im Backoffice gepflegte Adresse, nicht an den Antragsteller –
    deshalb steht hier auch der Kontakt des Antragstellers mit drin.
    """
    betreff = f"Neuer Antrag {antrag['id']}: {antrag['vorname']} {antrag['nachname']}"
    zeilen = [
        f"Es ist ein neuer Antrag für {config.VERANSTALTUNG} eingegangen.",
        "",
        _daten(antrag),
    ]
    if antrag["email"]:
        zeilen.append(f"  E-Mail:        {antrag['email']}")
    if antrag["bemerkung"]:
        zeilen.append("")
        zeilen.append("Bemerkung:")
        zeilen.append(antrag["bemerkung"])
    if basis_url:
        zeilen.append("")
        zeilen.append(f"Im Backoffice: {basis_url}/admin/antrag/{antrag['id']}")
    zeilen.append("")
    zeilen.append(
        "Diese Nachricht geht an die Adresse, die im Backoffice unter"
        " Einstellungen hinterlegt ist."
    )
    return ("orga", empfaenger, betreff, "\n".join(zeilen))


def fuer(antrag, typ: str, begruendung: str = "") -> tuple | None:
    """Vorlage nach Typ – oder None, wenn keine Mailadresse hinterlegt ist."""
    if not (antrag["email"] or "").strip():
        return None
    if typ == "eingang":
        return vorlage_eingang(antrag)
    if typ == "genehmigt":
        return vorlage_genehmigt(antrag)
    if typ == "abgelehnt":
        return vorlage_abgelehnt(antrag, begruendung)
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
