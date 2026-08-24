"""Täglicher Zeitplan-Abruf im Hintergrund.

Bewusst nicht beim Hochfahren: dann hinge der Start des Dienstes an fremden
Servern. Stattdessen einmal am Tag zur konfigurierten Stunde – und im
Backoffice jederzeit auf Knopfdruck.

Schlägt der Abruf fehl, bleibt der letzte erfolgreiche Stand einfach stehen.
Das Backoffice zeigt, wann er zuletzt geklappt hat.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from . import config, db, zeitplan

protokoll = logging.getLogger("uvicorn.error")


def sekunden_bis_naechsten_lauf() -> float:
    """Bis zur nächsten vollen Stunde ZEITPLAN_STUNDE. Steht die Uhr schon
    darüber, ist es morgen."""
    jetzt = db.jetzt_lokal()
    ziel = jetzt.replace(hour=config.ZEITPLAN_STUNDE % 24, minute=0, second=0,
                         microsecond=0)
    if ziel <= jetzt:
        ziel += timedelta(days=1)
    return (ziel - jetzt).total_seconds()


async def schleife(stop: asyncio.Event) -> None:
    while not stop.is_set():
        warten = sekunden_bis_naechsten_lauf()
        try:
            await asyncio.wait_for(stop.wait(), timeout=warten)
            return  # stop kam zuerst
        except asyncio.TimeoutError:
            pass

        try:
            # Der Abruf blockiert (urllib), deshalb in einen Thread, damit die
            # Anwendung derweil weiter antwortet.
            berichte = await asyncio.to_thread(zeitplan.alle_abrufen, "automatisch")
        except Exception:  # noqa: BLE001 – die Schleife darf nie sterben
            protokoll.exception("Zeitplan-Abruf ist unerwartet gescheitert")
            continue

        for bericht in berichte:
            if bericht["fehler"]:
                protokoll.warning("Zeitplan %s: %s", bericht["serie"],
                                  bericht["fehler"])
            elif zeitplan.unveraendert(bericht):
                protokoll.info("Zeitplan %s: unveraendert", bericht["serie"])
            else:
                protokoll.info(
                    "Zeitplan %s: %d neu, %d geaendert, %d entfallen",
                    bericht["serie"], len(bericht["neu"]),
                    len(bericht["geaendert"]), len(bericht["entfallen"]))
