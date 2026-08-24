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

from . import auth, config, db, mail, validation, worker

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

    # Bestätigung nur einreihen, nicht verschicken – siehe app/mail.py.
    angelegt = db.anmeldung_laden(nummer)
    vorlage = mail.fuer(angelegt, "eingang") if angelegt else None
    if vorlage is not None:
        db.mail_einreihen(nummer, vorlage)

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


# --- Anmeldung --------------------------------------------------------------


@app.exception_handler(auth.NichtAngemeldet)
async def _nicht_angemeldet(request: Request, ausnahme):
    return RedirectResponse(
        "/admin/login?weiter=" + quote(ausnahme.ziel), status_code=303
    )


@app.exception_handler(auth.NichtEingerichtet)
async def _nicht_eingerichtet(request: Request, ausnahme):
    return templates.TemplateResponse(
        "admin_nicht_eingerichtet.html", _kontext(request), status_code=503
    )


def _weiter_pfad(roh: str) -> str:
    """Nur eigene Backoffice-Pfade zulassen – sonst wäre das eine offene
    Weiterleitung."""
    if roh.startswith("/admin") and not roh.startswith("//") and "\\" not in roh:
        return roh
    return "/admin"


@app.get("/admin/login")
async def login_formular(request: Request, weiter: str = "/admin"):
    if not auth.eingerichtet():
        raise auth.NichtEingerichtet()
    if auth.sitzung_lesen(request) is not None:
        return RedirectResponse(_weiter_pfad(weiter), status_code=303)
    return templates.TemplateResponse(
        "admin_login.html",
        _kontext(request, fehler="", weiter=_weiter_pfad(weiter),
                 kuerzel_abfragen=config.KUERZEL_ABFRAGEN, kuerzel=""),
    )


@app.post("/admin/login")
async def login_absenden(request: Request):
    if not auth.eingerichtet():
        raise auth.NichtEingerichtet()

    daten = await request.form()
    weiter = _weiter_pfad(str(daten.get("weiter") or "/admin"))
    kuerzel = str(daten.get("kuerzel") or "").strip()[:20]
    ip = _remote_ip(request, immer=True) or "unbekannt"

    def abweisen(meldung, code=401):
        return templates.TemplateResponse(
            "admin_login.html",
            _kontext(request, fehler=meldung, weiter=weiter,
                     kuerzel_abfragen=config.KUERZEL_ABFRAGEN, kuerzel=kuerzel),
            status_code=code,
        )

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
        sitzung, str(daten.get("csrf") or "")
    ):
        raise auth.NichtAngemeldet("/admin")
    antwort = RedirectResponse("/admin/login", status_code=303)
    auth.cookie_loeschen(antwort)
    return antwort


# --- Backoffice -------------------------------------------------------------

MELDUNGEN = {
    "gespeichert": "Änderungen gespeichert.",
    "geloescht": "Anmeldung gelöscht.",
    "badge": "Badge als ausgegeben vermerkt.",
    "badge_zurueck": "Badge-Häkchen zurückgenommen.",
    "gebuehr": "Gebühr als bezahlt vermerkt.",
    "gebuehr_zurueck": "Gebühren-Häkchen zurückgenommen.",
    "bilder": "Bilder als erhalten vermerkt.",
    "bilder_zurueck": "Bilder-Häkchen zurückgenommen.",
    "erinnert": "Erinnerung steht in der Schlange.",
    "nichts": "Nichts geändert – der Zustand passte nicht zu dieser Aktion.",
}


def _meldung(schluessel: str, anzahl: str = "") -> str:
    if schluessel == "sammel":
        if not anzahl.isdigit():
            return ""
        wieviele = int(anzahl)
        if wieviele == 0:
            return "Keine Erinnerung verschickt – es stand nichts mehr offen."
        if wieviele == 1:
            return "Eine Erinnerung steht in der Schlange."
        return f"{wieviele} Erinnerungen stehen in der Schlange."
    return MELDUNGEN.get(schluessel, "")


def _admin_kontext(request: Request, sitzung, **extra) -> dict:
    return _kontext(
        request,
        sitzung=sitzung,
        csrf=auth.csrf_token(sitzung.token),
        status_werte=db.STATUS_WERTE,
        bilder_offen=db.bilder_offen_zaehlen(),
        **extra,
    )


def _csrf_fehler(request: Request, sitzung):
    return templates.TemplateResponse(
        "admin_fehlt.html",
        _admin_kontext(request, sitzung, meldung="Ungültiges Formular-Token."),
        status_code=400,
    )


def _nicht_gefunden(request: Request, sitzung):
    return templates.TemplateResponse(
        "admin_fehlt.html",
        _admin_kontext(
            request, sitzung, meldung="Diese Anmeldung gibt es nicht (mehr)."
        ),
        status_code=404,
    )


@app.get("/admin")
async def admin_liste(
    request: Request,
    status: str = "",
    gegenleistung: str = "",
    suche: str = "",
    sortierung: str = "neueste",
    hinweis: str = "",
    sitzung=Depends(auth.sitzung_erforderlich),
):
    status = status if status in db.STATUS_WERTE else ""
    if gegenleistung not in ("gebuehr", "bilderspende", "keine"):
        gegenleistung = ""
    sortierung = sortierung if sortierung in db.SORTIERUNGEN else "neueste"
    suche = suche.strip()[:100]

    return templates.TemplateResponse(
        "admin_liste.html",
        _admin_kontext(
            request,
            sitzung,
            anmeldungen=db.anmeldungen_suchen(status, gegenleistung, suche, sortierung),
            zaehler=db.zaehler(),
            mails_aufgegeben=db.mails_aufgegeben(),
            hinweis=_meldung(hinweis),
            filter_status=status,
            filter_gegenleistung=gegenleistung,
            filter_suche=suche,
            sortierung=sortierung,
        ),
    )


def _detail_seite(request, sitzung, anmeldung, werte=None, fehler=None, hinweis="",
                  status_code=200):
    if werte is None:
        werte = {feld: (anmeldung[feld] or "") for feld in db.BEARBEITBAR}
        werte["kommerziell"] = bool(anmeldung["kommerziell"])
    return templates.TemplateResponse(
        "admin_detail.html",
        _admin_kontext(
            request,
            sitzung,
            anmeldung=anmeldung,
            werte=werte,
            fehler=fehler or {},
            hinweis=hinweis,
            mails=db.mails_zu_anmeldung(anmeldung["id"]),
        ),
        status_code=status_code,
    )


@app.get("/admin/anmeldung/{anmeldung_id}")
async def admin_detail(
    request: Request,
    anmeldung_id: int,
    hinweis: str = "",
    sitzung=Depends(auth.sitzung_erforderlich),
):
    anmeldung = db.anmeldung_laden(anmeldung_id)
    if anmeldung is None:
        return _nicht_gefunden(request, sitzung)
    return _detail_seite(request, sitzung, anmeldung, hinweis=_meldung(hinweis))


@app.post("/admin/anmeldung/{anmeldung_id}/speichern")
async def admin_speichern(
    request: Request, anmeldung_id: int, sitzung=Depends(auth.sitzung_erforderlich)
):
    daten = await request.form()
    if not auth.csrf_pruefen(sitzung, str(daten.get("csrf") or "")):
        return _csrf_fehler(request, sitzung)

    anmeldung = db.anmeldung_laden(anmeldung_id)
    if anmeldung is None:
        return _nicht_gefunden(request, sitzung)

    # Im Backoffice wird korrigiert, nicht neu zugestimmt: die beiden Häkchen
    # sind hier keine Pflicht, ihre Zeitstempel bleiben unangetastet.
    werte, fehler = validation.pruefen_backoffice(daten)
    if fehler:
        return _detail_seite(
            request, sitzung, anmeldung, werte=werte, fehler=fehler, status_code=422
        )

    db.anmeldung_aktualisieren(anmeldung_id, werte)
    return RedirectResponse(
        f"/admin/anmeldung/{anmeldung_id}?hinweis=gespeichert", status_code=303
    )


@app.post("/admin/anmeldung/{anmeldung_id}/loeschen")
async def admin_loeschen(
    request: Request, anmeldung_id: int, sitzung=Depends(auth.sitzung_erforderlich)
):
    daten = await request.form()
    if not auth.csrf_pruefen(sitzung, str(daten.get("csrf") or "")):
        return _csrf_fehler(request, sitzung)
    db.anmeldung_loeschen(anmeldung_id)
    return RedirectResponse("/admin?hinweis=geloescht", status_code=303)


# --- Abholliste am Orga-Büro ------------------------------------------------


@app.get("/admin/abholung")
async def admin_abholung(
    request: Request, hinweis: str = "", sitzung=Depends(auth.sitzung_erforderlich)
):
    """Der Schalter: Namen suchen, Badge aushändigen, Häkchen setzen.

    Die vollständige Liste geht in die Seite, gesucht wird im Browser – am
    Schalter soll das Tippen sofort etwas zeigen und nicht auf den Server
    warten. Die Häkchen ändern Serverzustand und laden neu; das ist in Ordnung,
    weil pro Besucher ohnehin einmal gesucht wird.
    """
    zeilen = [
        {
            "id": a["id"],
            "vorname": a["vorname"],
            "nachname": a["nachname"],
            "firma": a["firma"],
            "gegenleistung": a["gegenleistung"] or "",
            "status": a["status"],
            "badge_am": a["badge_am"],
            "badge_durch": a["badge_durch"] or "",
            "gebuehr_bezahlt_am": a["gebuehr_bezahlt_am"],
            # Vorgekaut fürs Filtern im Browser.
            "suchtext": f"{a['vorname']} {a['nachname']} {a['firma']}".lower(),
        }
        for a in db.anmeldungen_abholung()
    ]

    return templates.TemplateResponse(
        "admin_abholung.html",
        _admin_kontext(request, sitzung, zeilen=zeilen, hinweis=_meldung(hinweis)),
    )


def _zurueck(daten, vorgabe: str = "/admin/abholung") -> str:
    ziel = _weiter_pfad(str(daten.get("zurueck") or vorgabe))
    return ziel + ("&" if "?" in ziel else "?")


@app.post("/admin/anmeldung/{anmeldung_id}/badge")
async def admin_badge(
    request: Request, anmeldung_id: int, sitzung=Depends(auth.sitzung_erforderlich)
):
    daten = await request.form()
    if not auth.csrf_pruefen(sitzung, str(daten.get("csrf") or "")):
        return _csrf_fehler(request, sitzung)

    if db.anmeldung_laden(anmeldung_id) is None:
        return _nicht_gefunden(request, sitzung)

    if str(daten.get("ausgeben") or "1") == "1":
        # Das Kürzel kommt aus der Sitzung – wer angemeldet ist, gibt aus.
        hinweis = "badge" if db.badge_ausgeben(anmeldung_id, sitzung.kuerzel) else "nichts"
    else:
        hinweis = "badge_zurueck" if db.badge_zuruecknehmen(anmeldung_id) else "nichts"

    return RedirectResponse(_zurueck(daten) + "hinweis=" + hinweis, status_code=303)


@app.post("/admin/anmeldung/{anmeldung_id}/gebuehr")
async def admin_gebuehr(
    request: Request, anmeldung_id: int, sitzung=Depends(auth.sitzung_erforderlich)
):
    daten = await request.form()
    if not auth.csrf_pruefen(sitzung, str(daten.get("csrf") or "")):
        return _csrf_fehler(request, sitzung)

    if db.anmeldung_laden(anmeldung_id) is None:
        return _nicht_gefunden(request, sitzung)

    bezahlt = str(daten.get("bezahlt") or "1") == "1"
    erledigt = db.gebuehr_setzen(anmeldung_id, bezahlt)
    hinweis = ("gebuehr" if bezahlt else "gebuehr_zurueck") if erledigt else "nichts"

    return RedirectResponse(_zurueck(daten) + "hinweis=" + hinweis, status_code=303)


# --- Bilderspende nachhalten ------------------------------------------------


@app.get("/admin/bilder")
async def admin_bilder(
    request: Request, hinweis: str = "", anzahl: str = "",
    sitzung=Depends(auth.sitzung_erforderlich)
):
    """Wer Bilder schuldet und noch nicht geliefert hat.

    Sortiert so, dass die noch nie Erinnerten oben stehen – danach arbeitet man
    die Liste ab.
    """
    return templates.TemplateResponse(
        "admin_bilder.html",
        _admin_kontext(
            request,
            sitzung,
            anmeldungen=db.anmeldungen_bilder_offen(),
            hinweis=_meldung(hinweis, anzahl),
        ),
    )


@app.post("/admin/anmeldung/{anmeldung_id}/bilder")
async def admin_bilder_haken(
    request: Request, anmeldung_id: int, sitzung=Depends(auth.sitzung_erforderlich)
):
    daten = await request.form()
    if not auth.csrf_pruefen(sitzung, str(daten.get("csrf") or "")):
        return _csrf_fehler(request, sitzung)

    if db.anmeldung_laden(anmeldung_id) is None:
        return _nicht_gefunden(request, sitzung)

    erhalten = str(daten.get("erhalten") or "1") == "1"
    erledigt = db.bilder_setzen(anmeldung_id, erhalten)
    hinweis = ("bilder" if erhalten else "bilder_zurueck") if erledigt else "nichts"

    return RedirectResponse(
        _zurueck(daten, "/admin/bilder") + "hinweis=" + hinweis, status_code=303
    )


@app.post("/admin/anmeldung/{anmeldung_id}/erinnerung")
async def admin_erinnerung(
    request: Request, anmeldung_id: int, sitzung=Depends(auth.sitzung_erforderlich)
):
    daten = await request.form()
    if not auth.csrf_pruefen(sitzung, str(daten.get("csrf") or "")):
        return _csrf_fehler(request, sitzung)

    anmeldung = db.anmeldung_laden(anmeldung_id)
    if anmeldung is None:
        return _nicht_gefunden(request, sitzung)

    erledigt = db.erinnerung_einreihen(
        anmeldung_id, mail.fuer(anmeldung, "erinnerung")
    )
    return RedirectResponse(
        _zurueck(daten, "/admin/bilder")
        + "hinweis=" + ("erinnert" if erledigt else "nichts"),
        status_code=303,
    )


@app.post("/admin/erinnerungen")
async def admin_erinnerungen(
    request: Request, sitzung=Depends(auth.sitzung_erforderlich)
):
    """Alle offenen auf einmal erinnern."""
    daten = await request.form()
    if not auth.csrf_pruefen(sitzung, str(daten.get("csrf") or "")):
        return _csrf_fehler(request, sitzung)

    verschickt = 0
    for anmeldung in db.anmeldungen_bilder_offen():
        if db.erinnerung_einreihen(anmeldung["id"], mail.fuer(anmeldung, "erinnerung")):
            verschickt += 1

    return RedirectResponse(
        "/admin/bilder?hinweis=sammel&anzahl=" + str(verschickt), status_code=303
    )
