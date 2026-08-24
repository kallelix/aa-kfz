"""Presse-Akkreditierung – öffentliches Formular und Backoffice.

Die App spricht nur HTTP und lauscht auf 127.0.0.1 bzw. der eigenen IP. TLS
macht der Reverse Proxy davor; gestartet wird mit `python -m app`.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import auth, config, db, validation, worker

BASIS = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASIS / "templates"))


def _lokal(zeitstempel):
    """ISO-UTC aus der Datenbank in etwas Lesbares umwandeln."""
    if not zeitstempel:
        return ""
    try:
        zeit = datetime.fromisoformat(zeitstempel)
    except ValueError:
        return zeitstempel
    if zeit.tzinfo is None:
        zeit = zeit.replace(tzinfo=timezone.utc)
    return zeit.astimezone().strftime("%d.%m.%Y %H:%M")


templates.env.filters["zeit"] = _lokal

protokoll = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(app: FastAPI):
    nachgetragen = db.init()
    if nachgetragen:
        protokoll.info("Datenbank ergaenzt: %s", ", ".join(nachgetragen))
    if config.SECRET_KEY_FLUECHTIG:
        protokoll.warning(
            "APP_SECRET_KEY ist nicht gesetzt - es wurde einer erzeugt. "
            "Alle Anmeldungen enden mit dem naechsten Neustart."
        )
    if not auth.eingerichtet():
        protokoll.warning(
            "ADMIN_PASSWORD_HASH ist nicht gesetzt - das Backoffice bleibt "
            "geschlossen. Hash erzeugen mit: python -m app.passwort"
        )
    if not config.nur_localhost():
        protokoll.warning(
            "Die App lauscht auf %s, also nicht nur auf localhost. Der Port "
            "muss per Firewall auf den Reverse Proxy beschraenkt sein.",
            config.BIND,
        )
        if config.FORWARDED_ALLOW_IPS in ("127.0.0.1", "::1"):
            protokoll.warning(
                "FORWARDED_ALLOW_IPS steht auf %s, der Proxy sitzt aber "
                "offenbar woanders.",
                config.FORWARDED_ALLOW_IPS,
            )

    stop = asyncio.Event()
    aufgabe = None
    if config.MAIL_AKTIV:
        aufgabe = asyncio.create_task(worker.schleife(stop))
    else:
        protokoll.warning(
            "SMTP_HOST oder MAIL_FROM fehlt - es wird nichts verschickt. "
            "Die Mails sammeln sich in mail_out und gehen nicht verloren."
        )

    try:
        yield
    finally:
        stop.set()
        if aufgabe is not None:
            try:
                await asyncio.wait_for(aufgabe, timeout=5)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                aufgabe.cancel()


# Keine öffentliche API-Doku – die App liefert nur HTML-Seiten aus.
app = FastAPI(
    title=f"Presse-Akkreditierung {config.VERANSTALTUNG}",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.mount("/static", StaticFiles(directory=str(BASIS / "static")), name="static")

DANKE_PFAD = config.pfad("danke")


def _kontext(request: Request, **extra) -> dict:
    """Werte, die jede Seite braucht."""
    basis = {
        "request": request,
        "veranstaltung": config.VERANSTALTUNG,
        "ort": config.ORT,
        "abholort": config.ABHOLORT,
        "gebuehr": config.gebuehr(),
        "bilder_anzahl": config.BILDER_ANZAHL,
        "kontakt_name": config.KONTAKT_NAME,
        "kontakt_mail": config.KONTAKT_MAIL,
        "kontakt_telefon": config.KONTAKT_TELEFON,
        "aufbewahrung_hinweis": config.AUFBEWAHRUNG_HINWEIS,
        "form_pfad": config.FORM_PATH,
        "honeypot": validation.HONEYPOT,
    }
    basis.update(extra)
    return basis


def _remote_ip(request: Request, immer: bool = False):
    """Client-IP. uvicorn setzt request.client bei --proxy-headers bereits aus
    X-Forwarded-For; die Header selbst auszuwerten wäre fälschbar."""
    if request.client is None:
        return None
    if not immer and not config.IP_SPEICHERN:
        return None
    return request.client.host


# --- Öffentliches Formular --------------------------------------------------


@app.get(config.FORM_PATH)
async def formular(request: Request):
    return templates.TemplateResponse(
        "anmeldung.html",
        _kontext(request, werte={}, fehler={}, badges_knapp=db.badges_erschoepft()),
    )


@app.post(config.FORM_PATH)
async def formular_absenden(request: Request):
    formular_daten = await request.form()

    # Bot: so tun als sei alles gut, aber nichts speichern.
    if validation.ist_bot(formular_daten):
        return RedirectResponse(DANKE_PFAD, status_code=303)

    werte, fehler = validation.pruefen(formular_daten)
    if fehler:
        return templates.TemplateResponse(
            "anmeldung.html",
            _kontext(
                request,
                werte=werte,
                fehler=fehler,
                badges_knapp=db.badges_erschoepft(),
            ),
            status_code=422,
        )

    nummer = db.anmeldung_anlegen(werte, _remote_ip(request))
    # TODO (Schritt 6): Bestätigungsmail in mail_out einreihen.

    ziel = f"{DANKE_PFAD}?nr={nummer}"
    if werte["gegenleistung"]:
        ziel += f"&art={werte['gegenleistung']}"
    return RedirectResponse(ziel, status_code=303)


@app.get(DANKE_PFAD)
async def danke(request: Request, nr: str = "", art: str = ""):
    # Nur anzeigen, nichts nachschlagen – die Seite gibt so keine Daten preis.
    nummer = nr if nr.isdigit() else None
    gegenleistung = art if art in validation.GEGENLEISTUNGEN else ""
    return templates.TemplateResponse(
        "danke.html", _kontext(request, nummer=nummer, gegenleistung=gegenleistung)
    )
