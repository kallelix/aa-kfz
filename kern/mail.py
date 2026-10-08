"""SMTP-Versand für alle Bereiche.

Stand vorher Wort für Wort gleich in kennzeichen/app/mail.py und
presse/app/mail.py – nur das Konfigurationsmodul war ein anderes. Mit den
Backoffice-Konten kommt ein dritter Nutzer dazu, die Einladungen; das war der
Anlass, den Versand hierher zu ziehen (Lastenheft, Schritt 1.3).

Was verschickt wird, bleibt beim Bereich: Vorlagen, Warteschlange und Worker
gehören dorthin. Hier steht nur der Weg zum Server. ``config`` ist das
Konfigurationsmodul des Bereichs, dessen Postfach die Mail verschickt –
gelesen werden SMTP_HOST, SMTP_PORT, SMTP_TLS, SMTP_USER, SMTP_PASS,
SMTP_TIMEOUT, MAIL_FROM und MAIL_REPLY_TO.
"""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr


class NichtEingerichtet(Exception):
    """SMTP_HOST oder MAIL_FROM fehlen – es wird nichts verschickt."""


def aktiv(config) -> bool:
    return bool(config.SMTP_HOST and config.MAIL_FROM)


def _verbindung(config):
    if config.SMTP_TLS == "ssl":
        return smtplib.SMTP_SSL(
            config.SMTP_HOST,
            config.SMTP_PORT,
            timeout=config.SMTP_TIMEOUT,
            context=ssl.create_default_context(),
        )
    return smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=config.SMTP_TIMEOUT)


def senden(config, empfaenger: str, betreff: str, body: str) -> None:
    """Verschickt eine Mail. Wirft bei jedem Fehler – wer aufruft, entscheidet,
    ob es noch einmal versucht wird."""
    if not aktiv(config):
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

    with _verbindung(config) as smtp:
        if config.SMTP_TLS == "starttls":
            smtp.starttls(context=ssl.create_default_context())
        if config.SMTP_USER:
            smtp.login(config.SMTP_USER, config.SMTP_PASS)
        smtp.send_message(nachricht)
