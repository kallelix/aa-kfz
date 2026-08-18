"""Hintergrund-Task, der die Mail-Queue abarbeitet.

Läuft alle `MAIL_INTERVALL` Sekunden, nimmt sich die fälligen Zeilen aus
`mail_out` und verschickt sie. Fehlschläge werden gezählt und mit wachsendem
Abstand wiederholt; nach `MAIL_MAX_VERSUCHE` bleibt die Mail liegen und
taucht im Backoffice als „fehlgeschlagen" auf.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from . import config, db, mail

protokoll = logging.getLogger("uvicorn.error")


def _backoff(versuche: int) -> str:
    """1, 2, 4, 8 … Minuten, bei einer Stunde gedeckelt."""
    minuten = min(2 ** max(versuche - 1, 0), 60)
    zeitpunkt = datetime.now(timezone.utc) + timedelta(minutes=minuten)
    return zeitpunkt.replace(microsecond=0).isoformat()


def runde() -> tuple:
    """Ein Durchgang. Liefert (gesendet, fehlgeschlagen)."""
    gesendet = 0
    fehlgeschlagen = 0

    for zeile in db.mails_faellig():
        try:
            mail.senden(zeile["empfaenger"], zeile["betreff"], zeile["body"])
        except Exception as ausnahme:  # noqa: BLE001 – jeder Fehler ist ein Fehlversuch
            versuche = zeile["versuche"] + 1
            aufgegeben = versuche >= config.MAIL_MAX_VERSUCHE
            db.mail_fehlgeschlagen(
                zeile["id"],
                f"{type(ausnahme).__name__}: {ausnahme}",
                None if aufgegeben else _backoff(versuche),
            )
            fehlgeschlagen += 1
            if aufgegeben:
                protokoll.error(
                    "Mail %s an %s nach %s Versuchen aufgegeben: %s",
                    zeile["id"], zeile["empfaenger"], versuche, ausnahme,
                )
            else:
                protokoll.warning(
                    "Mail %s an %s fehlgeschlagen (Versuch %s): %s",
                    zeile["id"], zeile["empfaenger"], versuche, ausnahme,
                )
        else:
            db.mail_gesendet(zeile["id"])
            gesendet += 1

    return gesendet, fehlgeschlagen


async def schleife(stop: asyncio.Event) -> None:
    """Läuft, bis `stop` gesetzt wird. Der Versand selbst ist blockierend und
    wandert deshalb in einen Thread – sonst steht der Webserver still."""
    protokoll.info(
        "Mail-Worker gestartet (alle %s s, bis zu %s Versuche je Mail)",
        config.MAIL_INTERVALL, config.MAIL_MAX_VERSUCHE,
    )
    while not stop.is_set():
        try:
            gesendet, fehlgeschlagen = await asyncio.to_thread(runde)
            if gesendet or fehlgeschlagen:
                protokoll.info(
                    "Mail-Worker: %s gesendet, %s fehlgeschlagen", gesendet, fehlgeschlagen
                )
        except Exception:  # noqa: BLE001 – die Schleife darf nie sterben
            protokoll.exception("Mail-Worker: unerwarteter Fehler")

        try:
            await asyncio.wait_for(stop.wait(), timeout=config.MAIL_INTERVALL)
        except asyncio.TimeoutError:
            pass

    protokoll.info("Mail-Worker beendet")
