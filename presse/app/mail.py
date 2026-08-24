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
# Kommen in Schritt 6: Eingangsbestätigung in drei Varianten (Gebühr,
# Bilderspende, nicht kommerziell) und die Erinnerung an die Bilderspende.


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
