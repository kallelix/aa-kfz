"""Helfer-Dashboard – Backoffice für die Schichtplanung.

Anders als die beiden Schwester-Apps gibt es hier kein öffentliches Formular:
Helfer melden sich nicht selbst an, die Orga teilt ein. Öffentlich ist später
nur die Monitoransicht hinter einem Token.

Die App spricht nur HTTP und lauscht auf 127.0.0.1 bzw. der eigenen IP. TLS
macht der Reverse Proxy davor; gestartet wird mit `python -m app`.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urlencode

from fastapi import Depends, FastAPI, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import auth, config, csv_import, db, worker, zeitplan

BASIS = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASIS / "templates"))

protokoll = logging.getLogger("uvicorn.error")

WOCHENTAGE_KURZ = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")


# --- Jinja-Filter ----------------------------------------------------------

def _zeitpunkt(wert):
    """'2026-08-29 06:30' -> '29.08. 06:30'."""
    if not wert:
        return ""
    try:
        return datetime.fromisoformat(wert).strftime("%d.%m. %H:%M")
    except ValueError:
        return wert


def _uhr(wert):
    """Nur die Uhrzeit."""
    if not wert:
        return ""
    try:
        return datetime.fromisoformat(wert).strftime("%H:%M")
    except ValueError:
        return wert


def _tag(wert):
    """'2026-08-29' -> 'Sa 29.08.'."""
    if not wert:
        return ""
    try:
        zeit = datetime.fromisoformat(wert)
    except ValueError:
        return wert
    return WOCHENTAGE_KURZ[zeit.weekday()] + zeit.strftime(" %d.%m.")


def _spanne(zeile):
    """Die Zeitspanne einer Schicht, mit Tag nur dann zweimal, wenn sie über
    Mitternacht läuft."""
    beginn, ende = zeile["beginn"], zeile["ende"]
    if beginn[:10] == ende[:10]:
        return _uhr(beginn) + "–" + _uhr(ende)
    return _uhr(beginn) + "–" + _uhr(ende) + " (+1)"


def _programmzeit(zeile):
    """Die Zeitangabe eines Programmpunkts. Offene Enden bleiben offen, und
    was gar keine Uhrzeit hat, zeigt seinen Wortlaut ('anschließend')."""
    if not zeile["beginn"]:
        return zeile["zeit_roh"] or "ohne Zeit"
    if not zeile["ende"]:
        return "ab " + _uhr(zeile["beginn"])
    return _uhr(zeile["beginn"]) + "–" + _uhr(zeile["ende"])


templates.env.filters["zeitpunkt"] = _zeitpunkt
templates.env.filters["uhr"] = _uhr
templates.env.filters["tag"] = _tag
templates.env.filters["spanne"] = _spanne
templates.env.filters["programmzeit"] = _programmzeit


# --- Start -----------------------------------------------------------------

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
    if config.JETZT_FEST:
        protokoll.warning(
            "JETZT_FEST steht auf %s - das Dashboard geht nach einer "
            "gestellten Uhr, nicht nach der echten Zeit.", config.JETZT_FEST
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
                "offenbar woanders.", config.FORWARDED_ALLOW_IPS,
            )

    stop = asyncio.Event()
    aufgabe = None
    if config.serien() and 0 <= config.ZEITPLAN_STUNDE <= 23:
        aufgabe = asyncio.create_task(worker.schleife(stop))
    else:
        protokoll.info(
            "Kein automatischer Zeitplan-Abruf - im Backoffice geht er von Hand."
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


app = FastAPI(
    title="Helfer-Dashboard " + config.VERANSTALTUNG,
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.mount("/static", StaticFiles(directory=str(BASIS / "static")), name="static")


def _kontext(request: Request, **extra) -> dict:
    basis = {
        "request": request,
        "veranstaltung": config.VERANSTALTUNG,
        "ort": config.ORT,
        "kontakt_name": config.KONTAKT_NAME,
        "kontakt_mail": config.KONTAKT_MAIL,
        "kontakt_telefon": config.KONTAKT_TELEFON,
    }
    basis.update(extra)
    return basis


def _admin(request: Request, sitzung: auth.Sitzung, **extra) -> dict:
    return _kontext(request, sitzung=sitzung,
                    csrf=auth.csrf_token(sitzung.token), **extra)


def _remote_ip(request: Request) -> str:
    """Client-IP. uvicorn setzt request.client bei --proxy-headers bereits aus
    X-Forwarded-For; die Header selbst auszuwerten wäre fälschbar."""
    return request.client.host if request.client else "unbekannt"


# --- Anmeldung -------------------------------------------------------------

@app.exception_handler(auth.NichtAngemeldet)
async def _nicht_angemeldet(request: Request, ausnahme):
    return RedirectResponse("/admin/login?weiter=" + quote(ausnahme.ziel),
                            status_code=303)


@app.exception_handler(auth.NichtEingerichtet)
async def _nicht_eingerichtet(request: Request, ausnahme):
    return templates.TemplateResponse("admin_nicht_eingerichtet.html",
                                      _kontext(request), status_code=503)


def _weiter_pfad(roh: str) -> str:
    """Nur eigene Backoffice-Pfade zulassen – sonst wäre das eine offene
    Weiterleitung."""
    if roh.startswith("/admin") and not roh.startswith("//") and "\\" not in roh:
        return roh
    return "/admin"


@app.get("/")
async def start():
    return RedirectResponse("/admin", status_code=303)


@app.get("/admin/login")
async def login_formular(request: Request, weiter: str = "/admin"):
    if not auth.eingerichtet():
        raise auth.NichtEingerichtet()
    if auth.sitzung_lesen(request) is not None:
        return RedirectResponse(_weiter_pfad(weiter), status_code=303)
    return templates.TemplateResponse(
        "admin_login.html",
        _kontext(request, fehler="", weiter=_weiter_pfad(weiter),
                 kuerzel_abfragen=config.KUERZEL_ABFRAGEN, kuerzel=""))


@app.post("/admin/login")
async def login_absenden(request: Request):
    if not auth.eingerichtet():
        raise auth.NichtEingerichtet()

    daten = await request.form()
    weiter = _weiter_pfad(str(daten.get("weiter") or "/admin"))
    kuerzel = str(daten.get("kuerzel") or "").strip()[:20]
    ip = _remote_ip(request)

    def abweisen(meldung, code=401):
        return templates.TemplateResponse(
            "admin_login.html",
            _kontext(request, fehler=meldung, weiter=weiter,
                     kuerzel_abfragen=config.KUERZEL_ABFRAGEN,
                     kuerzel=kuerzel),
            status_code=code)

    if auth.login_gesperrt(ip):
        return abweisen("Zu viele Fehlversuche. Bitte eine Minute warten.", 429)
    if not auth.passwort_pruefen(str(daten.get("passwort") or "")):
        auth.login_fehlversuch(ip)
        return abweisen("Passwort stimmt nicht.")

    auth.login_zuruecksetzen(ip)
    antwort = RedirectResponse(weiter, status_code=303)
    auth.cookie_setzen(antwort, request, auth.token_erzeugen(kuerzel))
    return antwort


@app.post("/admin/logout")
async def logout(request: Request):
    sitzung = auth.sitzung_lesen(request)
    daten = await request.form()
    if sitzung is not None and not auth.csrf_pruefen(
            sitzung, str(daten.get("csrf") or "")):
        raise auth.NichtAngemeldet("/admin")
    antwort = RedirectResponse("/admin/login", status_code=303)
    auth.cookie_loeschen(antwort)
    return antwort


async def _csrf_pflicht(request: Request, sitzung: auth.Sitzung):
    daten = await request.form()
    if not auth.csrf_pruefen(sitzung, str(daten.get("csrf") or "")):
        return None
    return daten


def _zurueck(ziel: str, hinweis: str = "", **parameter) -> RedirectResponse:
    """Nach jedem POST eine Umleitung – sonst legt Neuladen dieselbe Änderung
    ein zweites Mal an. Der Hinweis reist als Parameter mit."""
    werte = {k: v for k, v in parameter.items() if v}
    if hinweis:
        werte["hinweis"] = hinweis
    sprung = werte.pop("sprung", "")
    adresse = ziel + ("?" + urlencode(werte) if werte else "")
    if sprung:
        adresse += "#" + sprung
    return RedirectResponse(adresse, status_code=303)


# --- Übersicht -------------------------------------------------------------

@app.get("/admin")
async def uebersicht(request: Request, hinweis: str = "",
                     sitzung: auth.Sitzung = Depends(auth.sitzung_erforderlich)):
    zaehler = db.zaehler()
    luecken = [z for z in db.schichten(nur_luecken=True)]
    return templates.TemplateResponse(
        "admin_uebersicht.html",
        _admin(request, sitzung, hinweis=hinweis, zaehler=zaehler,
               luecken=luecken[:12], luecken_gesamt=len(luecken),
               konflikte=db.konflikte(), doppelt=db.doppelt_besetzt(),
               importe=db.importe()[:1], jetzt=db.jetzt_lokal()))


# --- Schichten -------------------------------------------------------------

@app.get("/admin/schichten")
async def schichten(request: Request, liste: str = "", tag: str = "",
                    luecken: str = "", hinweis: str = "",
                    sitzung: auth.Sitzung = Depends(auth.sitzung_erforderlich)):
    reihen = db.schichten(liste=liste, tag=tag, nur_luecken=bool(luecken))
    return templates.TemplateResponse(
        "admin_schichten.html",
        _admin(request, sitzung, hinweis=hinweis, schichten=reihen,
               listen=db.listen(), tage=db.tage(),
               f_liste=liste, f_tag=tag, f_luecken=bool(luecken)))


@app.get("/admin/schicht/{schicht_id}")
async def schicht(request: Request, schicht_id: int, hinweis: str = "",
                  suche: str = "",
                  sitzung: auth.Sitzung = Depends(auth.sitzung_erforderlich)):
    eintrag = db.schicht_laden(schicht_id)
    if eintrag is None:
        return templates.TemplateResponse("admin_fehlt.html",
                                          _kontext(request), status_code=404)
    besetzt = db.besetzung(schicht_id)
    drin = {z["id"] for z in besetzt}
    return templates.TemplateResponse(
        "admin_schicht.html",
        _admin(request, sitzung, hinweis=hinweis, schicht=eintrag,
               besetzung=besetzt, suche=suche,
               helfer=[h for h in db.helfer_liste() if h["id"] not in drin]))


@app.post("/admin/schicht/{schicht_id}/einteilen")
async def einteilen(request: Request, schicht_id: int,
                    sitzung: auth.Sitzung = Depends(auth.sitzung_erforderlich)):
    daten = await _csrf_pflicht(request, sitzung)
    if daten is None:
        return Response("Ungültiger CSRF-Token", status_code=400)

    ziel = "/admin/schicht/" + str(schicht_id)
    if db.schicht_laden(schicht_id) is None:
        return _zurueck("/admin/schichten", "unbekannt")

    try:
        helfer_id = int(str(daten.get("helfer_id") or ""))
    except ValueError:
        return _zurueck(ziel, "keiner")
    if db.helfer_laden(helfer_id) is None:
        return _zurueck(ziel, "keiner")

    # Doppelte Plätze gibt es in den Bestandsdaten, von Hand soll aber niemand
    # aus Versehen zweimal auf derselben Schicht landen.
    if db.steht_schon_drin(schicht_id, helfer_id):
        return _zurueck(ziel, "schon-drin")

    db.einteilen(schicht_id, helfer_id, quelle="hand", kuerzel=sitzung.kuerzel)
    return _zurueck(ziel, "eingeteilt")


@app.post("/admin/einteilung/{einteilung_id}/austragen")
async def austragen(request: Request, einteilung_id: int,
                    sitzung: auth.Sitzung = Depends(auth.sitzung_erforderlich)):
    daten = await _csrf_pflicht(request, sitzung)
    if daten is None:
        return Response("Ungültiger CSRF-Token", status_code=400)
    ziel = _weiter_pfad(str(daten.get("weiter") or "/admin/schichten"))
    db.austragen(einteilung_id)
    return _zurueck(ziel, "ausgetragen")


# --- Helfer ----------------------------------------------------------------

@app.get("/admin/helfer")
async def helfer_liste(request: Request, hinweis: str = "",
                       sitzung: auth.Sitzung = Depends(auth.sitzung_erforderlich)):
    return templates.TemplateResponse(
        "admin_helfer.html",
        _admin(request, sitzung, hinweis=hinweis, helfer=db.helfer_liste(),
               zaehler=db.zaehler()))


@app.get("/admin/helfer/{helfer_id}")
async def helfer_detail(request: Request, helfer_id: int, hinweis: str = "",
                        sitzung: auth.Sitzung = Depends(auth.sitzung_erforderlich)):
    person = db.helfer_laden(helfer_id)
    if person is None:
        return templates.TemplateResponse("admin_fehlt.html",
                                          _kontext(request), status_code=404)
    return templates.TemplateResponse(
        "admin_helfer_detail.html",
        _admin(request, sitzung, hinweis=hinweis, person=person,
               schichten=db.helfer_schichten(helfer_id)))


# --- Zeitplan der Rennserien -----------------------------------------------

def _zeitplan_seite(request: Request, sitzung, berichte=None, code: int = 200):
    serien = []
    for eintrag in config.serien():
        letzter = db.letzter_erfolg(eintrag["schluessel"])
        serien.append({
            **eintrag,
            "eintraege": db.programm(serie=eintrag["schluessel"]),
            "letzter_erfolg": letzter["gelaufen_am"] if letzter else "",
        })
    return templates.TemplateResponse(
        "admin_zeitplan.html",
        _admin(request, sitzung, hinweis="", serien=serien, berichte=berichte,
               abrufe=db.abrufe(8), stunde=config.ZEITPLAN_STUNDE,
               tage=config.TAGE), status_code=code)


@app.get("/admin/zeitplan")
async def zeitplan_ansicht(
        request: Request,
        sitzung: auth.Sitzung = Depends(auth.sitzung_erforderlich)):
    return _zeitplan_seite(request, sitzung)


@app.post("/admin/zeitplan/abrufen")
async def zeitplan_abrufen(
        request: Request,
        sitzung: auth.Sitzung = Depends(auth.sitzung_erforderlich)):
    daten = await request.form()
    if not auth.csrf_pruefen(sitzung, str(daten.get("csrf") or "")):
        return Response("Ungültiger CSRF-Token", status_code=400)

    # urllib blockiert; im Thread bleibt die Anwendung derweil ansprechbar.
    berichte = await asyncio.to_thread(
        zeitplan.alle_abrufen, sitzung.kuerzel or "von Hand")
    return _zeitplan_seite(request, sitzung, berichte=berichte)


# --- Import ----------------------------------------------------------------

@app.get("/admin/import")
async def import_formular(request: Request, hinweis: str = "",
                          sitzung: auth.Sitzung = Depends(auth.sitzung_erforderlich)):
    return templates.TemplateResponse(
        "admin_import.html",
        _admin(request, sitzung, hinweis=hinweis, bericht=None, fehler="",
               laeufe=db.importe()))


@app.post("/admin/import")
async def import_ausfuehren(request: Request,
                            sitzung: auth.Sitzung = Depends(auth.sitzung_erforderlich)):
    daten = await request.form()
    if not auth.csrf_pruefen(sitzung, str(daten.get("csrf") or "")):
        return Response("Ungültiger CSRF-Token", status_code=400)

    def seite(fehler="", bericht=None, code=200):
        return templates.TemplateResponse(
            "admin_import.html",
            _admin(request, sitzung, hinweis="", bericht=bericht,
                   fehler=fehler, laeufe=db.importe()), status_code=code)

    offen = daten.get("offen")
    vergeben = daten.get("vergeben")
    if not hasattr(offen, "read") or not hasattr(vergeben, "read"):
        return seite("Es werden beide Dateien gebraucht: Offene Posten und "
                     "Vergebene Posten. Eine allein ergibt einen halben "
                     "Bedarf – siehe Erklärung oben.", code=400)

    offen_roh = await offen.read()
    vergeben_roh = await vergeben.read()
    namen = (offen.filename or "offen.csv") + " + " + \
            (vergeben.filename or "vergeben.csv")

    try:
        bericht = csv_import.importieren(offen_roh, vergeben_roh, namen,
                                         sitzung.kuerzel)
    except csv_import.Fehler as fehler:
        return seite(str(fehler), code=400)

    return seite(bericht=bericht)
