"""Mails verschicken und Fristen wahren (Lastenheft 2.4, I-03).

Läuft alle MAIL_INTERVALL Sekunden, wenn Mail eingerichtet ist: erst die
fälligen Mails aus mail_out, dann die Fristen – wer seine Anmeldung nicht
bestätigt hat, wird erinnert, und wer es auch danach nicht tut, gibt seine
Plätze frei. Ohne Mail läuft nichts davon: wer keine Mail bekommt, kann
nichts bestätigen, und verfallen darf dann auch nichts.

Fehlschläge wie in Presse: gezählt und mit wachsendem Abstand wiederholt,
nach MAIL_MAX_VERSUCHE bleibt die Mail liegen.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from . import config, db, mail, normalisieren, selbstanmeldung, zugang

protokoll = logging.getLogger("uvicorn.error")


def _backoff(versuche: int) -> str:
    """1, 2, 4, 8 … Minuten, bei einer Stunde gedeckelt."""
    minuten = min(2 ** max(versuche - 1, 0), 60)
    return (db.jetzt_lokal() + timedelta(minutes=minuten)).strftime("%Y-%m-%d %H:%M:%S")


def verschicken() -> tuple[int, int]:
    """Ein Durchgang. Liefert (gesendet, fehlgeschlagen)."""
    gesendet = fehlgeschlagen = 0
    for zeile in db.mails_faellig():
        try:
            mail.senden(zeile["empfaenger"], zeile["betreff"], zeile["body"])
        except Exception as ausnahme:  # noqa: BLE001 – jeder Fehler ist ein Fehlversuch
            versuche = zeile["versuche"] + 1
            aufgegeben = versuche >= config.MAIL_MAX_VERSUCHE
            db.mail_fehlgeschlagen(zeile["id"], f"{type(ausnahme).__name__}: {ausnahme}",
                                   None if aufgegeben else _backoff(versuche))
            fehlgeschlagen += 1
            (protokoll.error if aufgegeben else protokoll.warning)(
                "Mail %s (%s) fehlgeschlagen, Versuch %s: %s",
                zeile["id"], zeile["typ"], versuche, ausnahme)
        else:
            db.mail_gesendet(zeile["id"])
            gesendet += 1
    return gesendet, fehlgeschlagen


def link(pfad: str) -> str:
    """Absolut, für Mails. Ohne BASIS_URL bleibt nur der Pfad – das meldet
    der Start."""
    return config.BASIS_URL + pfad


def fristen() -> tuple[int, int]:
    """Erinnern und verfallen lassen (I-03). Liefert (erinnert, verfallen)."""
    erinnert = verfallen = 0
    frist = config.BESTAETIGEN_FRIST_STUNDEN
    for person in db.unbestaetigt(frist):
        v = db.VERANSTALTUNGEN.laden(person["veranstaltung_id"])
        frei = db.verfallen_lassen(person["id"])
        if v is not None:
            # Ohne helfer_id: die Person ist danach meist gelöscht, und mit ihr
            # gingen sonst auch ihre ungesendeten Mails.
            db.mail_einreihen(None, mail.verfallen(
                person, selbstanmeldung.va_text(v),
                link("/" + normalisieren.kurzadresse(v["kurz"]))))
        protokoll.info("Anmeldung %s nicht bestätigt, %d Plätze frei", person["id"], len(frei))
        verfallen += 1
    for person in db.unbestaetigt(config.BESTAETIGEN_ERINNERN_STUNDEN, nur_unerinnert=True):
        v = db.VERANSTALTUNGEN.laden(person["veranstaltung_id"])
        if v is None:
            continue
        rest = max(1, frist - config.BESTAETIGEN_ERINNERN_STUNDEN)
        db.mail_einreihen(person["id"], mail.erinnerung(
            person, selbstanmeldung.va_text(v),
            link("/bestaetigen/" + zugang.token(zugang.BESTAETIGEN, person)),
            zugang.code(person), rest))
        db.erinnert(person["id"])
        erinnert += 1
    db.mails_aufraeumen()
    return erinnert, verfallen


def runde() -> None:
    gesendet, fehlgeschlagen = verschicken()
    erinnert, verfallen = fristen()
    if gesendet or fehlgeschlagen or erinnert or verfallen:
        protokoll.info("Versand: %s gesendet, %s fehlgeschlagen, %s erinnert, %s verfallen",
                       gesendet, fehlgeschlagen, erinnert, verfallen)


async def schleife(stop: asyncio.Event) -> None:
    """Läuft, bis `stop` gesetzt wird. Versand und Datenbank blockieren und
    wandern deshalb in einen Thread – sonst steht der Webserver still."""
    protokoll.info("Mail-Versand gestartet (alle %s s)", config.MAIL_INTERVALL)
    while not stop.is_set():
        try:
            await asyncio.to_thread(runde)
        except Exception:  # noqa: BLE001 – die Schleife darf nie sterben
            protokoll.exception("Versand: unerwarteter Fehler")
        try:
            await asyncio.wait_for(stop.wait(), timeout=config.MAIL_INTERVALL)
        except asyncio.TimeoutError:
            pass
    protokoll.info("Mail-Versand beendet")
