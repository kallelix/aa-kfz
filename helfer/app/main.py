"""Helfer-Dashboard – Backoffice für die Schichtplanung.

Anders als die beiden Schwester-Apps gibt es hier kein öffentliches Formular:
Helfer melden sich nicht selbst an, die Orga teilt ein. Öffentlich ist später
nur die Monitoransicht hinter einem Token.

Die App spricht nur HTTP und lauscht auf 127.0.0.1 bzw. der eigenen IP. TLS
macht der Reverse Proxy davor; gestartet wird mit `python -m app`.
"""

from __future__ import annotations

import asyncio
import hmac
import logging
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote, urlencode

from fastapi import Depends, FastAPI, Request
from fastapi.responses import (JSONResponse, RedirectResponse,
                               Response)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import (auth, band, config, csv_import, db, eintraege,
               normalisieren, unterschriften, worker, zeitplan)

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
templates.env.filters["ausschnitt"] = unterschriften.ausschnitt


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
    aufgaben = []

    # Eine gestellte Uhr heisst: das hier ist keine laufende Veranstaltung,
    # sondern eine Vorfuehrung oder ein Probelauf. Nichts davon soll von
    # selbst fremde Server abfragen - und die Vermerke waeren ohnehin
    # unbrauchbar, weil jeder Lauf denselben Zeitstempel traegt und sich vom
    # vorigen nicht unterscheiden laesst. Von Hand geht im Backoffice beides
    # weiter: wer den Knopf drueckt, weiss, was er tut.
    von_selbst = not config.JETZT_FEST
    if not von_selbst:
        protokoll.info(
            "JETZT_FEST ist gesetzt - kein Zeitplan-Abruf und kein "
            "Helferabgleich von selbst. Von Hand geht beides."
        )

    if von_selbst and config.serien() and 0 <= config.ZEITPLAN_STUNDE <= 23:
        aufgaben.append(asyncio.create_task(worker.schleife(stop)))
    elif von_selbst:
        protokoll.info(
            "Kein automatischer Zeitplan-Abruf - im Backoffice geht er von Hand."
        )

    if von_selbst and config.IMPORT_ABRUF_MOEGLICH             and config.IMPORT_TAKT_MINUTEN > 0:
        protokoll.info("Helferabgleich alle %d Minuten",
                       config.IMPORT_TAKT_MINUTEN)
        aufgaben.append(asyncio.create_task(worker.import_schleife(stop)))
    elif von_selbst:
        protokoll.info(
            "Kein selbsttaetiger Helferabgleich - im Backoffice geht er von Hand."
        )

    try:
        yield
    finally:
        stop.set()
        for aufgabe in aufgaben:
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


# --- Hauptnavigation -------------------------------------------------------

# Die Reihenfolge folgt dem Ablauf: erst was waehrend der Veranstaltung
# staendig gebraucht wird, dann die beiden Ausgabetische.
#
# Jeder Eintrag nennt neben seinem Ziel die Pfade, die er mitmarkiert. Das ist
# noetig, weil die Einzelansichten in der Einzahl heissen - /admin/schicht/7
# gehoert zu "Schichten", faengt aber nicht mit /admin/schichten an.
HAUPTNAV = (
    ("/admin", "Übersicht", ()),
    ("/admin/band", "Zeitplan", ()),
    ("/admin/aufgaben", "Aufgaben", ("/admin/aufgabe",)),
    ("/admin/schichten", "Schichten", ("/admin/schicht",)),
    ("/admin/helfer", "Helfer", ()),
    ("/admin/funk", "Funken", ()),
    ("/admin/schluessel", "Schlüssel", ()),
)

# Was man einmal einrichtet und danach selten anfasst - zusammengefasst hinter
# einem Punkt, damit die Zeile darueber die sieben zeigt, in denen man
# tatsaechlich arbeitet.
UNTERNAV = (
    ("/admin/einstellungen", "Einstellungen", ()),
    ("/admin/monitor", "Monitor", ()),
    ("/admin/import", "Import", ()),
    ("/admin/unterschriften", "Unterschriften", ()),
    ("/admin/zeitplan", "Zeitplan-Abruf", ("/admin/programm",)),
)


def _navigation(pfad: str) -> dict:
    """Die Navigation mit dem Punkt der gerade offenen Seite markiert.

    Es gewinnt der laengste passende Pfadanfang. Ein blosses „faengt damit an“
    reichte nicht: /admin ist der Anfang von allem und waere sonst auf jeder
    Seite hervorgehoben. So braucht die Uebersicht auch keine Sonderregel –
    sie passt eben nur, solange nichts Genaueres passt.
    """

    def treffer(eintrag) -> int:
        laenge = 0
        for anfang in (eintrag[0],) + eintrag[2]:
            if pfad == anfang or pfad.startswith(anfang + "/"):
                laenge = max(laenge, len(anfang))
        return laenge

    laengster = max(treffer(eintrag) for eintrag in HAUPTNAV + UNTERNAV)

    def punkte(eintraege) -> list:
        gemacht = []
        for ziel, name, weitere in eintraege:
            eigen = treffer((ziel, name, weitere))
            gemacht.append({"ziel": ziel, "name": name,
                            "hier": eigen > 0 and eigen == laengster})
        return gemacht

    unten = punkte(UNTERNAV)
    return {"hauptnav": punkte(HAUPTNAV), "unternav": unten,
            "unternav_hier": any(punkt["hier"] for punkt in unten)}


def _admin(request: Request, sitzung: auth.Sitzung, **extra) -> dict:
    # Marke und Takt gehen an jede Backoffice-Seite: das Skript in der
    # Grundvorlage fragt damit nach, ob inzwischen jemand unterschrieben hat.
    #
    # Heisst tabletstand und nicht stand: /admin/band reicht unter dem Namen
    # bereits den Tagesstand durch, und zwei gleiche Schluesselwoerter waeren
    # keine stille Ueberdeckung, sondern ein Fehler auf jeder solchen Seite.
    return _kontext(request, sitzung=sitzung,
                    csrf=auth.csrf_token(sitzung.token),
                    tabletstand=unterschriften.stand(),
                    admin_takt=config.ADMIN_TAKT,
                    **_navigation(request.url.path), **extra)


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
               groessen=normalisieren.GROESSEN,
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
async def helfer_liste(request: Request, hinweis: str = "", suche: str = "",
                       sitzung: auth.Sitzung = Depends(auth.sitzung_erforderlich)):
    return templates.TemplateResponse(
        "admin_helfer.html",
        _admin(request, sitzung, hinweis=hinweis, helfer=db.helfer_liste(),
               zaehler=db.zaehler(), tshirt=db.tshirt_zaehler(),
               groessen=normalisieren.GROESSEN, suche=suche,
               unterschrieben=unterschriften.je_vorgang("tshirt"),
               tablet=bool(db.tablet_token())))


# ACHTUNG, Reihenfolge: /admin/helfer/neu muss VOR
# /admin/helfer/{helfer_id} stehen. Starlette nimmt die erste Route, die
# passt – steht die parametrisierte vorn, landet "neu" als Wert in
# helfer_id und die Anfrage scheitert an der Zahlenprüfung.
@app.get("/admin/helfer/neu")
async def helfer_neu(request: Request,
                     sitzung: auth.Sitzung = Depends(auth.sitzung_erforderlich)):
    leer = {"name": "", "email": "", "telefon": "", "veggie": "",
            "tshirt": "", "bemerkung": ""}
    return _helferformular(request, sitzung, leer, {})


@app.post("/admin/helfer/neu")
async def helfer_anlegen_von_hand(
        request: Request,
        sitzung: auth.Sitzung = Depends(auth.sitzung_erforderlich)):
    daten = await request.form()
    if not auth.csrf_pruefen(sitzung, str(daten.get("csrf") or "")):
        return Response("Ungültiger CSRF-Token", status_code=400)

    werte = _helfer_werte(daten)
    if not werte["name"]:
        return _helferformular(request, sitzung, werte,
                               {"name": "Ohne Namen geht es nicht."})

    nummer, meldung = db.helfer_von_hand(_helfer_daten(werte))
    if meldung == "gibt-es-schon":
        return _helferformular(
            request, sitzung, werte,
            {"name": "Diese Person steht schon in der Liste – gleicher Name "
                     "und gleiche Mailadresse."}, person=db.helfer_laden(nummer))
    return _zurueck("/admin/helfer", "angelegt", sprung="helfer-" + str(nummer))


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


# --- Monitor ---------------------------------------------------------------

def _token_stimmt(uebermittelt: str) -> bool:
    """Vergleich in gleichbleibender Zeit. Ein leerer Token in der Datenbank
    heißt: der Link ist widerrufen, dann stimmt gar nichts mehr."""
    hinterlegt = db.monitor_token()
    if not hinterlegt:
        return False
    return hmac.compare_digest(hinterlegt, uebermittelt)


def _monitor_kontext(request: Request, token: str, tag: str = "") -> dict:
    jetzt = db.jetzt_lokal()
    stand = db.monitor_stand(jetzt, config.MONITOR_VORSCHAU)
    # strftime('%A') käme im C-Locale als "Saturday" heraus, und ein Locale
    # auf dem Server zu setzen wäre für einen Wochentag zu viel Aufwand.
    stand["tag_lang"] = (config.WOCHENTAGE[jetzt.weekday()] + ", " +
                         jetzt.strftime("%d.%m.%Y"))
    return _kontext(
        request, token=token, stand=stand,
        # Nur der Tagesblick, wenn ein Tag angefragt ist – sonst None.
        tagesblick=db.tagesstand(tag, jetzt) if tag else None,
        band=_band(tag, jetzt) if tag else None,
        tagesleiste=db.monitor_tage(),
        heute=jetzt.strftime("%Y-%m-%d"),
        intervall=config.MONITOR_INTERVALL,
        warnschwelle=config.MONITOR_WARNUNG,
        overlay_sekunden=config.MONITOR_OVERLAY_SEKUNDEN,
        tagesblick_sekunden=config.MONITOR_TAGESBLICK_SEKUNDEN,
        tage=config.TAGE)


def _band(tag: str, jetzt) -> dict | None:
    """Das Programm-Band eines Tages, fertig gerechnet."""
    stand = db.tagesstand(tag, jetzt)
    return band.bauen(
        tag, stand["programm"], stand["schichten"],
        # Die Jetzt-Linie gehoert nur auf den laufenden Tag. An einem anderen
        # stuende sie an einer Stelle, die dort nichts bedeutet.
        jetzt=jetzt if stand["ist_heute"] else None,
        farben={s["schluessel"]: s["farbe"] for s in config.serien()},
        aufgaben=[dict(a) for a in db.aufgaben(tag=tag)])


def _tag_pruefen(roh: str) -> str:
    """Nur ein Datum, das es wirklich gibt. Alles andere wird verworfen,
    statt es in eine Abfrage zu reichen."""
    roh = (roh or "").strip()
    if not roh:
        return ""
    try:
        date.fromisoformat(roh)
    except ValueError:
        return ""
    return roh


@app.get("/monitor/{token}")
async def monitor(request: Request, token: str):
    # 404 statt 403: ein falscher Link soll nicht verraten, dass es einen
    # richtigen gibt.
    if not _token_stimmt(token):
        return templates.TemplateResponse("admin_fehlt.html",
                                          _kontext(request), status_code=404)
    return templates.TemplateResponse("monitor.html",
                                      _monitor_kontext(request, token))


@app.get("/monitor/{token}/inhalt")
async def monitor_inhalt(request: Request, token: str, tag: str = ""):
    """Nur der wechselnde Teil. Die Seite holt ihn sich selbst, damit der
    Bildschirm nicht alle Minute weiß aufblitzt.

    Mit `tag` kommt der Tagesblick statt der Jetzt-Ansicht zurück. Auch der
    frischt sich weiter auf: wer am Sonntag plant, während im Backoffice
    jemand einteilt, soll die neuen Zahlen sehen.
    """
    if not _token_stimmt(token):
        return Response("", status_code=404)
    tag = _tag_pruefen(tag)
    antwort = templates.TemplateResponse(
        "monitor_tag.html" if tag else "monitor_inhalt.html",
        _monitor_kontext(request, token, tag))
    antwort.headers["Cache-Control"] = "no-store"
    return antwort


@app.get("/admin/monitor")
async def monitor_verwalten(
        request: Request, hinweis: str = "",
        sitzung: auth.Sitzung = Depends(auth.sitzung_erforderlich)):
    token = db.monitor_token()
    basis = config.BASIS_URL or str(request.base_url).rstrip("/")
    return templates.TemplateResponse(
        "admin_monitor.html",
        _admin(request, sitzung, hinweis=hinweis, token=token,
               adresse=(basis + "/monitor/" + token) if token else "",
               intervall=config.MONITOR_INTERVALL,
               vorschau=config.MONITOR_VORSCHAU))


@app.post("/admin/monitor")
async def monitor_link(
        request: Request,
        sitzung: auth.Sitzung = Depends(auth.sitzung_erforderlich)):
    daten = await request.form()
    if not auth.csrf_pruefen(sitzung, str(daten.get("csrf") or "")):
        return Response("Ungültiger CSRF-Token", status_code=400)

    if str(daten.get("aktion")) == "widerrufen":
        db.monitor_token_loeschen()
        return _zurueck("/admin/monitor", "widerrufen")
    db.monitor_token_neu()
    return _zurueck("/admin/monitor", "neuer-link")


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


# --- Aufgabenplan ----------------------------------------------------------

def _aufgabe_kontext(request: Request, sitzung, aufgabe, werte, fehler,
                     konflikt=None):
    return _admin(
        request, sitzung, hinweis="", aufgabe=aufgabe, werte=werte,
        fehler=fehler, konflikt=konflikt,
        phasen=eintraege.PHASEN, status_texte=eintraege.STATUS,
        tage=db.monitor_tage(),
        vorschlaege={s: db.vorschlaege(s)
                     for s in ("ort", "verantwortlich", "kontakt")})


def _aus_zeile(zeile) -> dict:
    """Ein gespeicherter Datensatz in der Form, die das Formular erwartet."""
    return {
        "titel": zeile["titel"], "phase": zeile["phase"],
        "status": zeile["status"], "datum": zeile["datum"] or "",
        "beginn": eintraege.uhr(zeile["beginn"]),
        "ende": eintraege.uhr(zeile["ende"]),
        "ort": zeile["ort"], "verantwortlich": zeile["verantwortlich"],
        "kontakt": zeile["kontakt"], "notiz": zeile["notiz"],
        "version": zeile["version"],
    }


@app.get("/admin/aufgaben")
async def aufgaben(request: Request, phase: str = "", status: str = "",
                   hinweis: str = "",
                   sitzung: auth.Sitzung = Depends(auth.sitzung_erforderlich)):
    liste = db.aufgaben(phase=phase if phase in eintraege.PHASEN else "",
                        status=status if status in eintraege.STATUS else "")
    return templates.TemplateResponse(
        "admin_aufgaben.html",
        _admin(request, sitzung, hinweis=hinweis, aufgaben=liste,
               zaehler=db.aufgaben_zaehler(), f_phase=phase, f_status=status,
               phasen=eintraege.PHASEN, status_texte=eintraege.STATUS))


@app.get("/admin/aufgabe/neu")
async def aufgabe_neu(request: Request, tag: str = "",
                      sitzung: auth.Sitzung = Depends(auth.sitzung_erforderlich)):
    leer = {"titel": "", "phase": "event", "status": "offen",
            "datum": _tag_pruefen(tag), "beginn": "", "ende": "", "ort": "",
            "verantwortlich": "", "kontakt": "", "notiz": "", "version": 0}
    return templates.TemplateResponse(
        "admin_aufgabe.html",
        _aufgabe_kontext(request, sitzung, None, leer, {}))


@app.post("/admin/aufgabe/neu")
async def aufgabe_anlegen(request: Request,
                          sitzung: auth.Sitzung = Depends(auth.sitzung_erforderlich)):
    daten = await request.form()
    if not auth.csrf_pruefen(sitzung, str(daten.get("csrf") or "")):
        return Response("Ungültiger CSRF-Token", status_code=400)

    werte, fehler = eintraege.pruefen(dict(daten))
    if fehler:
        eingabe = {**{k: str(v) for k, v in daten.items()}, "version": 0}
        return templates.TemplateResponse(
            "admin_aufgabe.html",
            _aufgabe_kontext(request, sitzung, None, eingabe, fehler),
            status_code=400)

    nummer = db.aufgabe_anlegen(werte, sitzung.kuerzel)
    return _zurueck("/admin/aufgaben", "angelegt",
                    sprung="aufgabe-" + str(nummer))


@app.get("/admin/aufgabe/{aufgabe_id}")
async def aufgabe_formular(request: Request, aufgabe_id: int,
                           sitzung: auth.Sitzung = Depends(auth.sitzung_erforderlich)):
    zeile = db.aufgabe_laden(aufgabe_id)
    if zeile is None:
        return templates.TemplateResponse("admin_fehlt.html",
                                          _kontext(request), status_code=404)
    return templates.TemplateResponse(
        "admin_aufgabe.html",
        _aufgabe_kontext(request, sitzung, zeile, _aus_zeile(zeile), {}))


@app.post("/admin/aufgabe/{aufgabe_id}")
async def aufgabe_sichern(request: Request, aufgabe_id: int,
                          sitzung: auth.Sitzung = Depends(auth.sitzung_erforderlich)):
    daten = await request.form()
    if not auth.csrf_pruefen(sitzung, str(daten.get("csrf") or "")):
        return Response("Ungültiger CSRF-Token", status_code=400)

    zeile = db.aufgabe_laden(aufgabe_id)
    if zeile is None:
        return templates.TemplateResponse("admin_fehlt.html",
                                          _kontext(request), status_code=404)

    werte, fehler = eintraege.pruefen(dict(daten))
    eingabe = {**{k: str(v) for k, v in daten.items()},
               "version": daten.get("version") or 0}
    if fehler:
        return templates.TemplateResponse(
            "admin_aufgabe.html",
            _aufgabe_kontext(request, sitzung, zeile, eingabe, fehler),
            status_code=400)

    ergebnis = db.aufgabe_speichern(aufgabe_id, werte,
                                    daten.get("version"), sitzung.kuerzel)
    if ergebnis == "weg":
        return templates.TemplateResponse("admin_fehlt.html",
                                          _kontext(request), status_code=404)
    if ergebnis == "konflikt":
        # Nicht überschreiben, sondern zeigen, was inzwischen dasteht. Die
        # eigene Eingabe bleibt im Formular; die Version wird auf den jetzigen
        # Stand gesetzt, damit ein zweites Absenden bewusst gewinnt.
        aktuell = db.aufgabe_laden(aufgabe_id)
        eingabe["version"] = aktuell["version"]
        return templates.TemplateResponse(
            "admin_aufgabe.html",
            _aufgabe_kontext(request, sitzung, aktuell, eingabe, {},
                             konflikt=_aus_zeile(aktuell)),
            status_code=409)

    return _zurueck("/admin/aufgaben", "gespeichert",
                    sprung="aufgabe-" + str(aufgabe_id))


@app.post("/admin/aufgabe/{aufgabe_id}/status")
async def aufgabe_status(request: Request, aufgabe_id: int,
                         sitzung: auth.Sitzung = Depends(auth.sitzung_erforderlich)):
    daten = await _csrf_pflicht(request, sitzung)
    if daten is None:
        return Response("Ungültiger CSRF-Token", status_code=400)
    neu = str(daten.get("status") or "")
    if neu not in eintraege.STATUS:
        return _zurueck("/admin/aufgaben", "unbekannt")
    db.aufgabe_status(aufgabe_id, neu, sitzung.kuerzel)
    return _zurueck("/admin/aufgaben", "status",
                    phase=str(daten.get("f_phase") or ""),
                    status=str(daten.get("f_status") or ""),
                    sprung="aufgabe-" + str(aufgabe_id))


@app.post("/admin/aufgabe/{aufgabe_id}/loeschen")
async def aufgabe_weg(request: Request, aufgabe_id: int,
                      sitzung: auth.Sitzung = Depends(auth.sitzung_erforderlich)):
    daten = await _csrf_pflicht(request, sitzung)
    if daten is None:
        return Response("Ungültiger CSRF-Token", status_code=400)
    db.aufgabe_loeschen(aufgabe_id)
    return _zurueck("/admin/aufgaben", "geloescht")


# --- Programmpunkt von Hand ------------------------------------------------

@app.get("/admin/programm/{programm_id}")
async def programm_formular(request: Request, programm_id: int,
                            sitzung: auth.Sitzung = Depends(auth.sitzung_erforderlich)):
    zeile = db.programm_eintrag(programm_id)
    if zeile is None:
        return templates.TemplateResponse("admin_fehlt.html",
                                          _kontext(request), status_code=404)
    werte = {"titel": zeile["titel"], "beginn": eintraege.uhr(zeile["beginn"]),
             "ende": eintraege.uhr(zeile["ende"]), "notiz": zeile["notiz"],
             "version": zeile["version"]}
    return templates.TemplateResponse(
        "admin_programm.html",
        _admin(request, sitzung, hinweis="", eintrag=zeile, werte=werte,
               fehler={}, konflikt=None,
               serie=config.serie(zeile["serie"])))


@app.post("/admin/programm/{programm_id}")
async def programm_sichern(request: Request, programm_id: int,
                           sitzung: auth.Sitzung = Depends(auth.sitzung_erforderlich)):
    daten = await request.form()
    if not auth.csrf_pruefen(sitzung, str(daten.get("csrf") or "")):
        return Response("Ungültiger CSRF-Token", status_code=400)

    zeile = db.programm_eintrag(programm_id)
    if zeile is None:
        return templates.TemplateResponse("admin_fehlt.html",
                                          _kontext(request), status_code=404)

    werte, fehler = eintraege.programm_pruefen(dict(daten), zeile["datum"])
    eingabe = {**{k: str(v) for k, v in daten.items()},
               "version": daten.get("version") or 0}

    def seite(konflikt=None, code=200):
        return templates.TemplateResponse(
            "admin_programm.html",
            _admin(request, sitzung, hinweis="",
                   eintrag=db.programm_eintrag(programm_id),
                   werte=eingabe, fehler=fehler, konflikt=konflikt,
                   serie=config.serie(zeile["serie"])), status_code=code)

    if fehler:
        return seite(code=400)

    ergebnis = db.programm_speichern(programm_id, werte, daten.get("version"))
    if ergebnis == "weg":
        return templates.TemplateResponse("admin_fehlt.html",
                                          _kontext(request), status_code=404)
    if ergebnis == "konflikt":
        aktuell = db.programm_eintrag(programm_id)
        eingabe["version"] = aktuell["version"]
        return seite(konflikt={
            "titel": aktuell["titel"],
            "beginn": eintraege.uhr(aktuell["beginn"]),
            "ende": eintraege.uhr(aktuell["ende"]),
            "notiz": aktuell["notiz"]}, code=409)

    return _zurueck("/admin/zeitplan", "gespeichert")


@app.post("/admin/programm/{programm_id}/freigeben")
async def programm_freigeben(request: Request, programm_id: int,
                             sitzung: auth.Sitzung = Depends(auth.sitzung_erforderlich)):
    daten = await _csrf_pflicht(request, sitzung)
    if daten is None:
        return Response("Ungültiger CSRF-Token", status_code=400)
    db.programm_freigeben(programm_id)
    return _zurueck("/admin/zeitplan", "freigegeben")


# --- Programm-Band ---------------------------------------------------------

@app.get("/admin/band")
async def band_ansicht(request: Request, tag: str = "",
                       sitzung: auth.Sitzung = Depends(auth.sitzung_erforderlich)):
    jetzt = db.jetzt_lokal()
    tage = db.monitor_tage()
    gewaehlt = _tag_pruefen(tag)
    if not gewaehlt and tage:
        # Ohne Angabe der heutige Tag, sonst der erste, an dem etwas ansteht.
        heute = jetzt.strftime("%Y-%m-%d")
        gewaehlt = heute if any(t["datum"] == heute for t in tage) else tage[0]["datum"]

    stand = db.tagesstand(gewaehlt, jetzt) if gewaehlt else None
    return templates.TemplateResponse(
        "admin_band.html",
        _admin(request, sitzung, hinweis="", tage=tage, gewaehlt=gewaehlt,
               stand=stand, band=_band(gewaehlt, jetzt) if gewaehlt else None))


# --- T-Shirt-Ausgabe und Helfer von Hand -----------------------------------

def _helfer_zurueck(request: Request, helfer_id: int, hinweis: str):
    """Zurück in die Liste, an dieselbe Zeile und mit demselben Suchbegriff.

    Ohne das landet man nach jedem Haken wieder oben in einer ungefilterten
    Liste von hundert Namen – bei einer Ausgabe, bei der Leute Schlange
    stehen, ist das der Unterschied zwischen benutzbar und nicht.
    """
    return _zurueck("/admin/helfer", hinweis,
                    suche=str(request.query_params.get("suche") or ""),
                    sprung="helfer-" + str(helfer_id))


@app.post("/admin/helfer/{helfer_id}/tshirt")
async def tshirt_ausgeben(request: Request, helfer_id: int,
                          sitzung: auth.Sitzung = Depends(auth.sitzung_erforderlich)):
    daten = await _csrf_pflicht(request, sitzung)
    if daten is None:
        return Response("Ungültiger CSRF-Token", status_code=400)
    if db.helfer_laden(helfer_id) is None:
        return _zurueck("/admin/helfer", "unbekannt")

    groesse = str(daten.get("groesse") or "").strip()
    if groesse and groesse not in normalisieren.GROESSEN:
        return _zurueck("/admin/helfer", "groesse",
                        suche=str(daten.get("suche") or ""),
                        sprung="helfer-" + str(helfer_id))

    db.tshirt_ausgeben(helfer_id, groesse, sitzung.kuerzel)
    _unterschrift_dazu("tshirt", helfer_id, "ausgabe", sitzung.kuerzel)
    return _zurueck("/admin/helfer", "tshirt",
                    suche=str(daten.get("suche") or ""),
                    sprung="helfer-" + str(helfer_id))


@app.post("/admin/helfer/{helfer_id}/tshirt/zurueck")
async def tshirt_zurueck(request: Request, helfer_id: int,
                         sitzung: auth.Sitzung = Depends(auth.sitzung_erforderlich)):
    daten = await _csrf_pflicht(request, sitzung)
    if daten is None:
        return Response("Ungültiger CSRF-Token", status_code=400)
    db.tshirt_zuruecknehmen(helfer_id)
    return _zurueck("/admin/helfer", "tshirt-zurueck",
                    suche=str(daten.get("suche") or ""),
                    sprung="helfer-" + str(helfer_id))


def _helferformular(request: Request, sitzung, werte, fehler, person=None):
    return templates.TemplateResponse(
        "admin_helfer_form.html",
        _admin(request, sitzung, hinweis="", werte=werte, fehler=fehler,
               person=person, groessen=normalisieren.GROESSEN))


def _helfer_werte(daten) -> dict:
    return {
        "name": normalisieren.text(daten.get("name")),
        "email": normalisieren.text(daten.get("email")),
        "telefon": normalisieren.text(daten.get("telefon")),
        "veggie": str(daten.get("veggie") or ""),
        "tshirt": str(daten.get("tshirt") or ""),
        "bemerkung": (daten.get("bemerkung") or "").strip(),
    }


def _helfer_daten(werte: dict) -> dict:
    return {
        "name": werte["name"], "email": werte["email"],
        "telefon": werte["telefon"],
        "veggie": {"ja": 1, "nein": 0}.get(werte["veggie"]),
        "tshirt": werte["tshirt"] if werte["tshirt"] in normalisieren.GROESSEN
                  else None,
        "tshirt_roh": werte["tshirt"],
        "bemerkung": werte["bemerkung"],
    }


@app.get("/admin/helfer/{helfer_id}/aendern")
async def helfer_formular(request: Request, helfer_id: int,
                          sitzung: auth.Sitzung = Depends(auth.sitzung_erforderlich)):
    person = db.helfer_laden(helfer_id)
    if person is None:
        return templates.TemplateResponse("admin_fehlt.html",
                                          _kontext(request), status_code=404)
    werte = {"name": person["name"], "email": person["email"],
             "telefon": person["telefon"],
             "veggie": {1: "ja", 0: "nein"}.get(person["veggie"], ""),
             "tshirt": person["tshirt"] or "",
             "bemerkung": person["bemerkung"]}
    return _helferformular(request, sitzung, werte, {}, person=person)


@app.post("/admin/helfer/{helfer_id}/aendern")
async def helfer_sichern(request: Request, helfer_id: int,
                         sitzung: auth.Sitzung = Depends(auth.sitzung_erforderlich)):
    daten = await request.form()
    if not auth.csrf_pruefen(sitzung, str(daten.get("csrf") or "")):
        return Response("Ungültiger CSRF-Token", status_code=400)

    person = db.helfer_laden(helfer_id)
    if person is None:
        return templates.TemplateResponse("admin_fehlt.html",
                                          _kontext(request), status_code=404)

    werte = _helfer_werte(daten)
    if not werte["name"]:
        return _helferformular(request, sitzung, werte,
                               {"name": "Ohne Namen geht es nicht."}, person)
    if not db.helfer_aendern(helfer_id, _helfer_daten(werte)):
        return _helferformular(
            request, sitzung, werte,
            {"name": "So heißt schon jemand anderes mit derselben "
                     "Mailadresse."}, person)
    return _zurueck("/admin/helfer/" + str(helfer_id), "gespeichert")


# --- Funkgeräte und Material -----------------------------------------------

def _person_aus_formular(daten, sitzung) -> tuple[int | None, str]:
    """Ermittelt die Person: entweder eine vorhandene aus der Auswahl oder
    eine neue aus dem Textfeld daneben.

    Zwei Wege statt eines Namensfeldes mit Vorschlägen, weil Namen hier nicht
    eindeutig sind – "Thomas" gibt es mehrfach. Getippt heißt deshalb immer
    neu, ausgewählt immer die eine gemeinte Person.
    """
    neuer_name = normalisieren.text(daten.get("neuer_name"))
    if neuer_name:
        nummer, _ = db.helfer_von_hand({"name": neuer_name})
        return nummer, "neu"
    try:
        nummer = int(str(daten.get("helfer_id") or ""))
    except ValueError:
        return None, "keiner"
    return (nummer, "vorhanden") if db.helfer_laden(nummer) else (None, "keiner")


@app.get("/admin/funk")
async def funk(request: Request, hinweis: str = "", offen: str = "",
               sitzung: auth.Sitzung = Depends(auth.sitzung_erforderlich)):
    # Einmal alles holen und in Python trennen: der Umschalter zeigt beide
    # Zahlen, und zwei Abfragen fuer ein paar Dutzend Zeilen waeren Aufwand
    # ohne Gegenwert.
    alle = db.ausleihen_liste()
    noch_draussen = [z for z in alle if not z["zurueck_am"]]
    return templates.TemplateResponse(
        "admin_funk.html",
        _admin(request, sitzung, hinweis=hinweis,
               ausleihen=noch_draussen if offen else alle,
               anzahl_alle=len(alle), anzahl_offen=len(noch_draussen),
               nur_offen=bool(offen), zaehler=db.material_zaehler(),
               material=db.MATERIAL, material_text=db.MATERIAL_TEXT,
               helfer=db.helfer_liste(), tage=db.monitor_tage(),
               heute=db.jetzt_lokal().strftime("%Y-%m-%d"),
               vorgaben=db.material_vorgaben(),
               unterschrieben=unterschriften.je_vorgang("material"),
               tablet=bool(db.tablet_token())))


@app.post("/admin/funk/ausgeben")
async def funk_ausgeben(request: Request,
                        sitzung: auth.Sitzung = Depends(auth.sitzung_erforderlich)):
    daten = await _csrf_pflicht(request, sitzung)
    if daten is None:
        return Response("Ungültiger CSRF-Token", status_code=400)

    helfer_id, woher = _person_aus_formular(daten, sitzung)
    if helfer_id is None:
        return _zurueck("/admin/funk", "keiner")

    datum = _tag_pruefen(str(daten.get("datum") or ""))

    mengen = {stueck: daten.get(stueck) for stueck in db.MATERIAL}
    nummer = db.ausleihen(helfer_id, mengen, datum,
                          str(daten.get("bemerkung") or ""), sitzung.kuerzel)
    if nummer is None:
        return _zurueck("/admin/funk", "nichts")
    _unterschrift_dazu("material", nummer, "ausgabe", sitzung.kuerzel)
    return _zurueck("/admin/funk", "neu-angelegt" if woher == "neu" else "ausgegeben")


@app.post("/admin/ausleihe/{ausleihe_id}/zurueck")
async def ausleihe_zurueck(request: Request, ausleihe_id: int,
                           sitzung: auth.Sitzung = Depends(auth.sitzung_erforderlich)):
    daten = await _csrf_pflicht(request, sitzung)
    if daten is None:
        return Response("Ungültiger CSRF-Token", status_code=400)
    # Ohne Mengen im Formular kommt alles zurück – der häufige Fall braucht
    # einen Klick, der seltene ein Formular.
    mengen = None
    if str(daten.get("teilweise") or ""):
        mengen = {stueck: daten.get(stueck) for stueck in db.MATERIAL}
    db.ausleihe_zurueck(ausleihe_id, mengen, sitzung.kuerzel)
    _unterschrift_dazu("material", ausleihe_id, "rueckgabe", sitzung.kuerzel)
    return _zurueck("/admin/funk", "zurueck",
                    offen=str(daten.get("offen") or ""))


@app.post("/admin/ausleihe/{ausleihe_id}/loeschen")
async def ausleihe_weg(request: Request, ausleihe_id: int,
                       sitzung: auth.Sitzung = Depends(auth.sitzung_erforderlich)):
    daten = await _csrf_pflicht(request, sitzung)
    if daten is None:
        return Response("Ungültiger CSRF-Token", status_code=400)
    db.ausleihe_loeschen(ausleihe_id)
    return _zurueck("/admin/funk", "geloescht")


# --- KFZ-Schlüssel ---------------------------------------------------------

@app.get("/admin/schluessel")
async def schluessel(request: Request, hinweis: str = "", offen: str = "",
                     sitzung: auth.Sitzung = Depends(auth.sitzung_erforderlich)):
    alle = db.schluessel_liste()
    noch_draussen = [z for z in alle if not z["zurueck_am"]]
    return templates.TemplateResponse(
        "admin_schluessel.html",
        _admin(request, sitzung, hinweis=hinweis,
               schluessel=noch_draussen if offen else alle,
               anzahl_alle=len(alle), anzahl_offen=len(noch_draussen),
               nur_offen=bool(offen), fahrzeuge=db.fahrzeuge(),
               namen=db.namen_vorschlaege(),
               unterschrieben=unterschriften.je_vorgang("schluessel"),
               tablet=bool(db.tablet_token())))


@app.post("/admin/schluessel/ausgeben")
async def schluessel_ausgeben(request: Request,
                              sitzung: auth.Sitzung = Depends(auth.sitzung_erforderlich)):
    daten = await _csrf_pflicht(request, sitzung)
    if daten is None:
        return Response("Ungültiger CSRF-Token", status_code=400)

    kennzeichen = str(daten.get("kennzeichen") or "")
    if not normalisieren.kennzeichen(kennzeichen):
        return _zurueck("/admin/schluessel", "kein-kennzeichen")

    name = str(daten.get("name") or "")
    fahrzeug_id, neu = db.fahrzeug_sichern(kennzeichen, name)
    if fahrzeug_id is None:
        return _zurueck("/admin/schluessel", "kein-kennzeichen")

    nummer = db.schluessel_ausgeben(fahrzeug_id, name,
                                    str(daten.get("bemerkung") or ""),
                                    sitzung.kuerzel)
    _unterschrift_dazu("schluessel", nummer, "ausgabe", sitzung.kuerzel)
    return _zurueck("/admin/schluessel",
                    "fahrzeug-neu" if neu else "schluessel-raus")


@app.post("/admin/schluessel/{schluessel_id}/zurueck")
async def schluessel_zurueck(request: Request, schluessel_id: int,
                             sitzung: auth.Sitzung = Depends(auth.sitzung_erforderlich)):
    daten = await _csrf_pflicht(request, sitzung)
    if daten is None:
        return Response("Ungültiger CSRF-Token", status_code=400)
    if db.schluessel_zurueck(schluessel_id, sitzung.kuerzel):
        _unterschrift_dazu("schluessel", schluessel_id, "rueckgabe",
                           sitzung.kuerzel)
    return _zurueck("/admin/schluessel", "zurueck",
                    offen=str(daten.get("offen") or ""))


@app.post("/admin/schluessel/{schluessel_id}/loeschen")
async def schluessel_weg(request: Request, schluessel_id: int,
                         sitzung: auth.Sitzung = Depends(auth.sitzung_erforderlich)):
    daten = await _csrf_pflicht(request, sitzung)
    if daten is None:
        return Response("Ungültiger CSRF-Token", status_code=400)
    db.schluessel_loeschen(schluessel_id)
    return _zurueck("/admin/schluessel", "geloescht")


@app.post("/admin/fahrzeug/{fahrzeug_id}/loeschen")
async def fahrzeug_weg(request: Request, fahrzeug_id: int,
                       sitzung: auth.Sitzung = Depends(auth.sitzung_erforderlich)):
    daten = await _csrf_pflicht(request, sitzung)
    if daten is None:
        return Response("Ungültiger CSRF-Token", status_code=400)
    ausgang = db.fahrzeug_loeschen(fahrzeug_id)
    return _zurueck("/admin/schluessel",
                    {"weg": "fahrzeug-weg",
                     "hat-vorgaenge": "fahrzeug-hat-vorgaenge"}.get(
                         ausgang, "unbekannt"))


# --- Einstellungen ---------------------------------------------------------

def _einstellungsseite(request: Request, sitzung, hinweis: str = ""):
    """Die Seite zeigt zweierlei: was sich hier ändern lässt, und was in der
    .env steht. Das Zweite ist nur zum Nachsehen – wer wissen will, warum der
    Monitor alle 60 Sekunden neu lädt, soll es nicht im Dateisystem suchen
    müssen."""
    aus_der_env = [
        ("Veranstaltungstage", ", ".join(t.isoformat() for t in config.TAGE),
         "TAGE"),
        ("Zeitzone", config.ZEITZONE, "ZEITZONE"),
        ("Gestellte Uhr", config.JETZT_FEST or "aus (echte Uhr)", "JETZT_FEST"),
        ("Monitor: Auffrischen", str(config.MONITOR_INTERVALL) + " s",
         "MONITOR_INTERVALL"),
        ("Monitor: Vorschau", str(config.MONITOR_VORSCHAU) + " min",
         "MONITOR_VORSCHAU"),
        ("Monitor: Warnung ab", str(config.MONITOR_WARNUNG) + " fehlenden",
         "MONITOR_WARNUNG"),
        ("Monitor: Overlay schließt", str(config.MONITOR_OVERLAY_SEKUNDEN) + " s",
         "MONITOR_OVERLAY_SEKUNDEN"),
        ("Monitor: Tagesblick endet",
         str(config.MONITOR_TAGESBLICK_SEKUNDEN) + " s",
         "MONITOR_TAGESBLICK_SEKUNDEN"),
        ("Zeitplan: Abruf um", "%02d:00 Uhr" % (config.ZEITPLAN_STUNDE % 24)
         if 0 <= config.ZEITPLAN_STUNDE <= 23 else "aus", "ZEITPLAN_STUNDE"),
        ("Zeitplan: Serien",
         ", ".join(s["titel"] for s in config.serien()) or "keine",
         "ZEITPLAN_SERIEN"),
        ("Unterschrift: verfällt nach",
         str(config.UNTERSCHRIFT_MINUTEN) + " min", "UNTERSCHRIFT_MINUTEN"),
        ("Unterschrift: Nachfrist",
         str(config.UNTERSCHRIFT_NACHFRIST) + " min", "UNTERSCHRIFT_NACHFRIST"),
        ("Tablet: fragt nach alle", str(config.UNTERSCHRIFT_TAKT) + " s",
         "UNTERSCHRIFT_TAKT"),
        ("Backoffice: fragt nach alle", str(config.ADMIN_TAKT) + " s"
         if config.ADMIN_TAKT else "aus", "ADMIN_TAKT"),
    ]
    return templates.TemplateResponse(
        "admin_einstellungen.html",
        _admin(request, sitzung, hinweis=hinweis,
               vorgaben=db.material_vorgaben(),
               material=db.MATERIAL, material_text=db.MATERIAL_TEXT,
               hoechstwert=db.MATERIAL_VORGABE_MAX,
               aus_der_env=aus_der_env,
               jetzt_fest=bool(config.JETZT_FEST)))


@app.get("/admin/einstellungen")
async def einstellungen(request: Request, hinweis: str = "",
                        sitzung: auth.Sitzung = Depends(auth.sitzung_erforderlich)):
    return _einstellungsseite(request, sitzung, hinweis)


@app.post("/admin/einstellungen")
async def einstellungen_speichern(
        request: Request,
        sitzung: auth.Sitzung = Depends(auth.sitzung_erforderlich)):
    daten = await _csrf_pflicht(request, sitzung)
    if daten is None:
        return Response("Ungültiger CSRF-Token", status_code=400)
    db.material_vorgaben_setzen({s: daten.get(s) for s in db.MATERIAL})
    return _zurueck("/admin/einstellungen", "gespeichert")


# --- Nachfragen aus dem Backoffice -----------------------------------------

@app.get("/admin/stand")
async def admin_stand(request: Request, seit: int = 0, art: str = "",
                      sitzung: auth.Sitzung = Depends(auth.sitzung_erforderlich)):
    """Was sich seit `seit` getan hat. Klein gehalten – die Antwort geht alle
    paar Sekunden über die Leitung."""
    antwort = JSONResponse(unterschriften.stand(seit, art))
    antwort.headers["Cache-Control"] = "no-store"
    return antwort


# --- Unterschriften: Tablet und Verwaltung ---------------------------------

def _unterschrift_dazu(art: str, vorgang_id: int, richtung: str,
                       kuerzel: str = "") -> None:
    """Stellt den eben abgeschlossenen Vorgang gleich aufs Tablet.

    Absichtlich ohne Rückmeldung und ohne Umweg über einen zweiten Klick: an
    einem Ausgabetisch nach jeder Übergabe erst zu scrollen und einen Knopf zu
    suchen, hält die Schlange auf. Gibt es kein Tablet, passiert nichts – die
    Übergabe ist ohnehin schon gespeichert.
    """
    if not db.tablet_token():
        return
    unterschriften.anfordern(art, vorgang_id, richtung, kuerzel)


def _tablet_token_stimmt(uebermittelt: str) -> bool:
    hinterlegt = db.tablet_token()
    if not hinterlegt:
        return False
    return hmac.compare_digest(hinterlegt, uebermittelt)


def _tablet_kontext(request: Request, token: str, **extra) -> dict:
    return _kontext(request, token=token, offen=unterschriften.offen(),
                    takt=config.UNTERSCHRIFT_TAKT,
                    aufbewahrung=config.UNTERSCHRIFT_AUFBEWAHRUNG, **extra)


@app.get("/unterschrift/{token}")
async def tablet(request: Request, token: str, hinweis: str = ""):
    # 404 statt 403: ein falscher Link soll nicht verraten, dass es einen
    # richtigen gibt.
    if not _tablet_token_stimmt(token):
        return templates.TemplateResponse("admin_fehlt.html",
                                          _kontext(request), status_code=404)
    return templates.TemplateResponse(
        "unterschrift.html", _tablet_kontext(request, token, hinweis=hinweis))


@app.get("/unterschrift/{token}/stand")
async def tablet_stand(request: Request, token: str):
    """Nur der wechselnde Teil. Das Tablet fragt im Takt nach – ohne das
    müsste jemand am Tisch die Seite neu laden, während er ausgibt."""
    if not _tablet_token_stimmt(token):
        return Response("", status_code=404)
    antwort = templates.TemplateResponse("unterschrift_stand.html",
                                         _tablet_kontext(request, token))
    antwort.headers["Cache-Control"] = "no-store"
    return antwort


@app.post("/unterschrift/{token}/zeichnen")
async def tablet_zeichnen(request: Request, token: str):
    if not _tablet_token_stimmt(token):
        return Response("", status_code=404)

    daten = await request.form()
    try:
        nummer = int(str(daten.get("id") or ""))
    except ValueError:
        return _zurueck("/unterschrift/" + token, "weg")

    ergebnis = unterschriften.zeichnen(nummer, str(daten.get("pfad") or ""),
                                       str(daten.get("name") or ""))
    # Kein Hinweis beim Erfolg: die Rückkehr in den Wartezustand mit dem
    # grünen Haken IST die Bestätigung. Eine Meldung darüber bliebe in der
    # Adresse stehen und schöbe von da an bei jeder weiteren Unterschrift die
    # Knöpfe nach unten aus dem Bild.
    if ergebnis == "ok":
        return RedirectResponse("/unterschrift/" + token, status_code=303)
    return _zurueck("/unterschrift/" + token, ergebnis)


@app.post("/unterschrift/{token}/abbrechen")
async def tablet_abbrechen(request: Request, token: str):
    """Auch vom Tablet aus – wer die Übergabe abbricht, steht dort und nicht
    am Rechner."""
    if not _tablet_token_stimmt(token):
        return Response("", status_code=404)
    await request.form()
    unterschriften.abbrechen()
    return _zurueck("/unterschrift/" + token, "abgebrochen")


@app.get("/admin/unterschriften")
async def unterschriften_verwalten(
        request: Request, hinweis: str = "",
        sitzung: auth.Sitzung = Depends(auth.sitzung_erforderlich)):
    token = db.tablet_token()
    basis = config.BASIS_URL or str(request.base_url).rstrip("/")
    return templates.TemplateResponse(
        "admin_unterschriften.html",
        _admin(request, sitzung, hinweis=hinweis, token=token,
               adresse=(basis + "/unterschrift/" + token) if token else "",
               offen=unterschriften.offen(), liste=unterschriften.liste(),
               zaehler=unterschriften.zaehler(),
               minuten=config.UNTERSCHRIFT_MINUTEN))


@app.post("/admin/unterschriften/link")
async def unterschriften_link(
        request: Request,
        sitzung: auth.Sitzung = Depends(auth.sitzung_erforderlich)):
    daten = await _csrf_pflicht(request, sitzung)
    if daten is None:
        return Response("Ungültiger CSRF-Token", status_code=400)
    if str(daten.get("aktion")) == "widerrufen":
        db.tablet_token_loeschen()
        return _zurueck("/admin/unterschriften", "widerrufen")
    db.tablet_token_neu()
    return _zurueck("/admin/unterschriften", "neuer-link")


@app.post("/admin/unterschrift/anfordern")
async def unterschrift_anfordern(
        request: Request,
        sitzung: auth.Sitzung = Depends(auth.sitzung_erforderlich)):
    daten = await _csrf_pflicht(request, sitzung)
    if daten is None:
        return Response("Ungültiger CSRF-Token", status_code=400)

    ziel = _weiter_pfad(str(daten.get("weiter") or "/admin/unterschriften"))
    if not db.tablet_token():
        return _zurueck(ziel, "kein-tablet")

    try:
        vorgang = int(str(daten.get("vorgang_id") or ""))
    except ValueError:
        return _zurueck(ziel, "unbekannt")

    _, meldung = unterschriften.anfordern(
        str(daten.get("art") or ""), vorgang,
        str(daten.get("richtung") or ""), sitzung.kuerzel)
    return _zurueck(ziel, meldung)


@app.post("/admin/unterschrift/abbrechen")
async def unterschrift_abbrechen(
        request: Request,
        sitzung: auth.Sitzung = Depends(auth.sitzung_erforderlich)):
    daten = await _csrf_pflicht(request, sitzung)
    if daten is None:
        return Response("Ungültiger CSRF-Token", status_code=400)
    unterschriften.abbrechen()
    return _zurueck(_weiter_pfad(str(daten.get("weiter") or "")),
                    "abgebrochen")


# --- Import ----------------------------------------------------------------

def _abruf_takt() -> int:
    """Wie oft von selbst abgeglichen wird. 0 heisst: gar nicht."""
    if config.JETZT_FEST:
        return 0
    return config.IMPORT_TAKT_MINUTEN

@app.get("/admin/import")
async def import_formular(request: Request, hinweis: str = "",
                          sitzung: auth.Sitzung = Depends(auth.sitzung_erforderlich)):
    return templates.TemplateResponse(
        "admin_import.html",
        _admin(request, sitzung, hinweis=hinweis, bericht=None, fehler="",
               abruf_moeglich=config.IMPORT_ABRUF_MOEGLICH,
               abruf_takt=_abruf_takt(), uhr_steht=bool(config.JETZT_FEST),
               letzter=db.letzter_import(nur_geglueckt=False),
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
                   fehler=fehler, abruf_moeglich=config.IMPORT_ABRUF_MOEGLICH,
                   abruf_takt=_abruf_takt(), uhr_steht=bool(config.JETZT_FEST),
                   letzter=db.letzter_import(nur_geglueckt=False),
                   laeufe=db.importe()), status_code=code)

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


@app.post("/admin/import/abrufen")
async def import_abrufen(request: Request,
                         sitzung: auth.Sitzung = Depends(auth.sitzung_erforderlich)):
    """Holt beide Listen beim Dienst, statt sie hochladen zu lassen.

    Es ist derselbe Import: nur die Herkunft der beiden Dateien ist eine
    andere, gepruefte und geschrieben wird danach genau dasselbe.
    """
    daten = await request.form()
    if not auth.csrf_pruefen(sitzung, str(daten.get("csrf") or "")):
        return Response("Ungültiger CSRF-Token", status_code=400)

    def seite(fehler="", bericht=None, code=200):
        return templates.TemplateResponse(
            "admin_import.html",
            _admin(request, sitzung, hinweis="", bericht=bericht,
                   fehler=fehler, abruf_moeglich=config.IMPORT_ABRUF_MOEGLICH,
                   abruf_takt=_abruf_takt(), uhr_steht=bool(config.JETZT_FEST),
                   letzter=db.letzter_import(nur_geglueckt=False),
                   laeufe=db.importe()), status_code=code)

    # urllib blockiert; im Thread bleibt die Anwendung derweil ansprechbar -
    # wie beim Zeitplan-Abruf.
    try:
        bericht = await asyncio.to_thread(csv_import.abrufen, sitzung.kuerzel)
    except csv_import.Fehler as fehler:
        return seite(str(fehler), code=400)

    return seite(bericht=bericht)
