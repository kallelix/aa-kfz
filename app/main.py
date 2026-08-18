"""Kennzeichen-Antrag – öffentliches Formular und Backoffice.

Die App spricht nur HTTP und lauscht auf 127.0.0.1. TLS macht der Reverse
Proxy davor; siehe README für den Start mit --proxy-headers.
"""

from __future__ import annotations

import asyncio
import csv
import hmac
import io
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import segno
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
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
                "offenbar woanders. Dann protokolliert die App die Proxy-IP "
                "und das Login-Rate-Limit trifft alle gemeinsam.",
                config.FORWARDED_ALLOW_IPS,
            )

    stop = asyncio.Event()
    aufgabe = None
    if config.MAIL_AKTIV:
        aufgabe = asyncio.create_task(worker.schleife(stop))
        if not config.ABHOLUNG:
            protokoll.warning(
                "ABHOLUNG ist nicht gesetzt - die Genehmigungsmail nennt keinen "
                "Ort und keine Uhrzeit fuer die Kartenuebergabe."
            )
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
    title=f"Kennzeichen-Antrag {config.VERANSTALTUNG}",
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
        "kategorien": config.KATEGORIEN,
        "kategorie_labels": config.KATEGORIE_LABELS,
        "kennzeichen_erfassen": config.KENNZEICHEN_ERFASSEN,
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
        "antrag.html", _kontext(request, werte={}, fehler={})
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
            "antrag.html",
            _kontext(request, werte=werte, fehler=fehler),
            status_code=422,
        )

    nummer = db.antrag_anlegen(werte, _remote_ip(request))

    # Eingangsbestätigung nur einreihen, nicht verschicken – siehe app/mail.py.
    angelegt = db.antrag_laden(nummer)
    vorlage = mail.fuer(angelegt, "eingang") if angelegt else None
    if vorlage is not None:
        db.mail_einreihen(nummer, vorlage)

    return RedirectResponse(DANKE_PFAD + "?nr=" + str(nummer), status_code=303)


@app.get(DANKE_PFAD)
async def danke(request: Request, nr: str = ""):
    # Nur anzeigen, nichts nachschlagen – die Seite gibt so keine Daten preis.
    nummer = nr if nr.isdigit() else None
    return templates.TemplateResponse("danke.html", _kontext(request, nummer=nummer))


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
        _kontext(
            request,
            fehler="",
            weiter=_weiter_pfad(weiter),
            kuerzel_abfragen=config.KUERZEL_ABFRAGEN,
            kuerzel="",
        ),
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
            _kontext(
                request,
                fehler=meldung,
                weiter=weiter,
                kuerzel_abfragen=config.KUERZEL_ABFRAGEN,
                kuerzel=kuerzel,
            ),
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


def _admin_kontext(request: Request, sitzung, **extra) -> dict:
    return _kontext(
        request,
        sitzung=sitzung,
        csrf=auth.csrf_token(sitzung.token),
        status_werte=db.STATUS_WERTE,
        telefon_offen=db.telefonisch_offen(),
        mail_aktiv=config.MAIL_AKTIV,
        mail_max_versuche=config.MAIL_MAX_VERSUCHE,
        **extra,
    )


# Rückmeldungen nach einem POST. Der Schlüssel wandert als Query-Parameter über
# die Weiterleitung – so bleibt der Text im Code und nichts Fremdes auf der Seite.
MELDUNGEN = {
    "gespeichert": "Änderungen gespeichert.",
    "genehmigt": "Antrag genehmigt.",
    "abgelehnt": "Antrag abgelehnt.",
    "zurueckgesetzt": "Entscheidung zurückgenommen, der Antrag steht wieder auf „neu“.",
    "ausgegeben": "Als ausgegeben markiert.",
    "geloescht": "Antrag gelöscht.",
    "nichts": "Nichts geändert – der Status passte nicht zu dieser Aktion.",
    "nichts_markiert": "Kein Antrag markiert.",
    "angerufen": "Als telefonisch informiert abgehakt.",
    "anruf_offen": "Wieder als „noch anrufen“ markiert.",
    "mail_erneut": "Mail steht wieder in der Schlange.",
    "link_neu": "Neuer Link erzeugt. Der bisherige funktioniert nicht mehr.",
    "link_weg": "Link zurückgezogen. Es gibt keinen offenen Zugang mehr.",
}


def _meldung(schluessel: str, anzahl: str = "") -> str:
    if schluessel == "sammel":
        if not anzahl.isdigit():
            return ""
        wieviele = int(anzahl)
        if wieviele == 0:
            return "Nichts geändert – die markierten Anträge waren schon entschieden."
        if wieviele == 1:
            return "Ein Antrag genehmigt."
        return f"{wieviele} Anträge genehmigt."
    return MELDUNGEN.get(schluessel, "")


def _kontingent_stand() -> dict:
    """Belegung je Kategorie gegen die konfigurierte Obergrenze.

    Ohne KONTINGENTE ist das Ergebnis leer und es wird nirgends gewarnt –
    offene Frage 1 im Plan ist damit vertagt, nicht entschieden.
    """
    stand = {}
    for schluessel, grenze in config.KONTINGENTE.items():
        belegt = db.kontingent_belegt(schluessel)
        stand[schluessel] = {
            "belegt": belegt,
            "grenze": grenze,
            "voll": belegt >= grenze,
        }
    return stand


def _csrf_fehler(request: Request, sitzung):
    return templates.TemplateResponse(
        "admin_fehlt.html",
        _admin_kontext(request, sitzung, meldung="Ungültiges Formular-Token."),
        status_code=400,
    )


def _zum_antrag(antrag_id: int, hinweis: str, anzahl: str = "") -> RedirectResponse:
    ziel = f"/admin/antrag/{antrag_id}?hinweis={hinweis}"
    if anzahl:
        ziel += f"&anzahl={anzahl}"
    return RedirectResponse(ziel, status_code=303)


@app.get("/admin")
async def admin_liste(
    request: Request,
    status: str = "neu",
    kategorie: str = "",
    suche: str = "",
    sortierung: str = "neueste",
    hinweis: str = "",
    anzahl: str = "",
    sitzung=Depends(auth.sitzung_erforderlich),
):
    # Leerer Status heißt "alle" – die bewusste Abwahl des Vorgabefilters.
    status = status if status in db.STATUS_WERTE else ""
    kategorie = kategorie if kategorie in config.KATEGORIE_KEYS else ""
    sortierung = sortierung if sortierung in db.SORTIERUNGEN else "neueste"
    suche = suche.strip()[:100]

    antraege = db.antraege_suchen(status, kategorie, suche, sortierung)
    return templates.TemplateResponse(
        "admin_liste.html",
        _admin_kontext(
            request,
            sitzung,
            antraege=antraege,
            zaehler=db.zaehler(),
            kontingente=_kontingent_stand(),
            mails_aufgegeben=db.mails_aufgegeben(),
            hinweis=_meldung(hinweis, anzahl),
            filter_status=status,
            filter_kategorie=kategorie,
            filter_suche=suche,
            sortierung=sortierung,
        ),
    )


def _nicht_gefunden(request: Request, sitzung):
    return templates.TemplateResponse(
        "admin_fehlt.html",
        _admin_kontext(request, sitzung, meldung="Diesen Antrag gibt es nicht (mehr)."),
        status_code=404,
    )


def _detail_seite(request, sitzung, antrag, werte=None, fehler=None, hinweis="",
                  status_code=200):
    """Detailansicht rendern – nach Fehlern mit den abgeschickten Werten."""
    if werte is None:
        werte = {feld: (antrag[feld] or "") for feld in db.BEARBEITBAR}
    return templates.TemplateResponse(
        "admin_detail.html",
        _admin_kontext(
            request,
            sitzung,
            antrag=antrag,
            werte=werte,
            fehler=fehler or {},
            hinweis=hinweis,
            kontingent=_kontingent_stand().get(antrag["kategorie"]),
            mails=db.mails_zu_antrag(antrag["id"]),
        ),
        status_code=status_code,
    )


@app.get("/admin/antrag/{antrag_id}")
async def admin_detail(
    request: Request,
    antrag_id: int,
    hinweis: str = "",
    sitzung=Depends(auth.sitzung_erforderlich),
):
    antrag = db.antrag_laden(antrag_id)
    if antrag is None:
        return _nicht_gefunden(request, sitzung)
    return _detail_seite(request, sitzung, antrag, hinweis=_meldung(hinweis))


@app.post("/admin/antrag/{antrag_id}/speichern")
async def admin_speichern(
    request: Request, antrag_id: int, sitzung=Depends(auth.sitzung_erforderlich)
):
    """Korrigierte Werte übernehmen – wahlweise gleich mit Genehmigung.

    Der Plan will "Genehmigen, optional mit korrigierten Werten": ein Formular,
    zwei Knöpfe.
    """
    daten = await request.form()
    if not auth.csrf_pruefen(sitzung, str(daten.get("csrf") or "")):
        return _csrf_fehler(request, sitzung)

    antrag = db.antrag_laden(antrag_id)
    if antrag is None:
        return _nicht_gefunden(request, sitzung)

    werte, fehler = validation.pruefen(daten)
    if fehler:
        return _detail_seite(
            request, sitzung, antrag, werte=werte, fehler=fehler, status_code=422
        )

    db.antrag_aktualisieren(antrag_id, werte)

    if str(daten.get("aktion") or "") == "genehmigen":
        # Erst neu laden: die Mail soll die korrigierten Werte nennen.
        aktuell = db.antrag_laden(antrag_id)
        erledigt = db.antrag_status_setzen(
            antrag_id, "genehmigt", sitzung.kuerzel,
            mail=mail.fuer(aktuell, "genehmigt") if aktuell else None,
        )
        return _zum_antrag(antrag_id, "genehmigt" if erledigt else "nichts")

    return _zum_antrag(antrag_id, "gespeichert")


@app.post("/admin/antrag/{antrag_id}/ablehnen")
async def admin_ablehnen(
    request: Request, antrag_id: int, sitzung=Depends(auth.sitzung_erforderlich)
):
    daten = await request.form()
    if not auth.csrf_pruefen(sitzung, str(daten.get("csrf") or "")):
        return _csrf_fehler(request, sitzung)

    antrag = db.antrag_laden(antrag_id)
    if antrag is None:
        return _nicht_gefunden(request, sitzung)

    begruendung = str(daten.get("begruendung") or "").strip()[:1000]
    if not begruendung:
        # Pflichtfeld: die Begründung geht später als Mail an den Antragsteller.
        return _detail_seite(
            request,
            sitzung,
            antrag,
            fehler={"begruendung": "Bitte eine Begründung angeben – sie geht an den Antragsteller."},
            status_code=422,
        )

    erledigt = db.antrag_status_setzen(
        antrag_id, "abgelehnt", sitzung.kuerzel, begruendung,
        mail=mail.fuer(antrag, "abgelehnt", begruendung),
    )
    return _zum_antrag(antrag_id, "abgelehnt" if erledigt else "nichts")


@app.post("/admin/antrag/{antrag_id}/status")
async def admin_status(
    request: Request, antrag_id: int, sitzung=Depends(auth.sitzung_erforderlich)
):
    """Zurücksetzen auf „neu" und das Häkchen „ausgegeben"."""
    daten = await request.form()
    if not auth.csrf_pruefen(sitzung, str(daten.get("csrf") or "")):
        return _csrf_fehler(request, sitzung)

    if db.antrag_laden(antrag_id) is None:
        return _nicht_gefunden(request, sitzung)

    ziel = str(daten.get("ziel") or "")
    if ziel not in ("neu", "ausgegeben"):
        return _zum_antrag(antrag_id, "nichts")

    erledigt = db.antrag_status_setzen(antrag_id, ziel, sitzung.kuerzel)
    hinweis = ("zurueckgesetzt" if ziel == "neu" else "ausgegeben") if erledigt else "nichts"
    return _zum_antrag(antrag_id, hinweis)


@app.post("/admin/sammelaktion")
async def admin_sammelaktion(
    request: Request, sitzung=Depends(auth.sitzung_erforderlich)
):
    """Mehrere markieren, alle genehmigen."""
    daten = await request.form()
    if not auth.csrf_pruefen(sitzung, str(daten.get("csrf") or "")):
        return _csrf_fehler(request, sitzung)

    ids = [int(w) for w in daten.getlist("ids") if str(w).isdigit()]
    zurueck = _weiter_pfad(str(daten.get("zurueck") or "/admin"))
    trenner = "&" if "?" in zurueck else "?"

    if not ids:
        return RedirectResponse(zurueck + trenner + "hinweis=nichts_markiert", status_code=303)

    # Mails vorbereiten; eingereiht wird nur für die Anträge, die der Wechsel
    # tatsächlich erfasst – das entscheidet sich in der Transaktion.
    mails = {}
    for antrag_id in ids:
        antrag = db.antrag_laden(antrag_id)
        vorlage = mail.fuer(antrag, "genehmigt") if antrag else None
        if vorlage is not None:
            mails[antrag_id] = vorlage

    betroffen = db.sammel_genehmigen(ids, sitzung.kuerzel, mails)
    return RedirectResponse(
        zurueck + trenner + "hinweis=sammel&anzahl=" + str(len(betroffen)),
        status_code=303,
    )


@app.post("/admin/antrag/{antrag_id}/loeschen")
async def admin_loeschen(
    request: Request, antrag_id: int, sitzung=Depends(auth.sitzung_erforderlich)
):
    daten = await request.form()
    if not auth.csrf_pruefen(sitzung, str(daten.get("csrf") or "")):
        return _csrf_fehler(request, sitzung)
    db.antrag_loeschen(antrag_id)
    return RedirectResponse("/admin?hinweis=geloescht", status_code=303)


# --- CSV-Export -------------------------------------------------------------

# Spalte -> Überschrift. `remote_ip` fehlt hier bewusst: die IP steht nur für
# Missbrauchsfälle in der Datenbank und hat in einer Datei, die per Mail
# herumgereicht wird, nichts verloren.
CSV_SPALTEN = (
    ("id", "Nr."),
    ("created_at", "Eingegangen"),
    ("status", "Status"),
    ("vorname", "Vorname"),
    ("nachname", "Name"),
    ("funktion", "Funktion"),
    ("kategorie", "Kategorie"),
    ("kategorie_klartext", "Kategorie (Klartext)"),
    ("email", "E-Mail"),
    ("telefon", "Telefon"),
    ("kontaktweg", "Kontaktweg"),
    ("kennzeichen", "Kennzeichen"),
    ("bemerkung", "Bemerkung"),
    ("entscheidung_am", "Entschieden am"),
    ("entscheidung_durch", "Entschieden durch"),
    ("begruendung", "Begründung"),
    ("tel_informiert_am", "Telefonisch informiert am"),
)


def _csv_zeile(antrag) -> list:
    berechnet = {
        "kategorie_klartext": config.KATEGORIE_LABELS.get(
            antrag["kategorie"], antrag["kategorie"]
        ),
        "kontaktweg": "E-Mail" if antrag["email"] else "Telefon",
    }
    werte = []
    for spalte, _ in CSV_SPALTEN:
        if spalte in berechnet:
            werte.append(berechnet[spalte])
        elif spalte in ("created_at", "entscheidung_am", "tel_informiert_am"):
            werte.append(_lokal(antrag[spalte]))
        else:
            werte.append(antrag[spalte] if antrag[spalte] is not None else "")
    return werte


@app.get("/admin/export.csv")
async def admin_export(
    request: Request,
    status: str = "",
    kategorie: str = "",
    suche: str = "",
    sortierung: str = "neueste",
    sitzung=Depends(auth.sitzung_erforderlich),
):
    """Dieselbe Auswahl wie in der Liste, nur als Datei.

    Ohne Parameter wird alles exportiert – wer auf „CSV" klickt, bekommt genau
    das, was gerade gefiltert auf dem Schirm steht.
    """
    status = status if status in db.STATUS_WERTE else ""
    kategorie = kategorie if kategorie in config.KATEGORIE_KEYS else ""
    sortierung = sortierung if sortierung in db.SORTIERUNGEN else "neueste"
    suche = suche.strip()[:100]

    puffer = io.StringIO(newline="")
    schreiber = csv.writer(
        puffer, delimiter=config.CSV_TRENNER, quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n"
    )
    schreiber.writerow([ueberschrift for _, ueberschrift in CSV_SPALTEN])
    for antrag in db.antraege_suchen(status, kategorie, suche, sortierung):
        schreiber.writerow(_csv_zeile(antrag))

    # BOM voran, sonst zeigt Excel unter Windows Umlaute als Buchstabensalat.
    inhalt = ("﻿" + puffer.getvalue()).encode("utf-8")
    dateiname = "antraege-" + datetime.now().strftime("%Y-%m-%d") + ".csv"
    return Response(
        content=inhalt,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{dateiname}"'},
    )


# --- Durchfahrtsliste für die Straßensperre ---------------------------------


def _durchfahrt_zeilen() -> list:
    """Die Tabellenzeilen, für beide Ansichten dieselben."""
    return [
        {
            "vorname": antrag["vorname"],
            "nachname": antrag["nachname"],
            "kennzeichen": antrag["kennzeichen"] or "",
            "kategorie": config.KATEGORIE_LABELS.get(
                antrag["kategorie"], antrag["kategorie"]
            ),
            # Vorgekaut fürs Filtern im Browser: Namen klein, Kennzeichen ohne
            # Trennzeichen. So bleibt die Normalisierung hier und muss in
            # JavaScript nicht ein zweites Mal richtig sein.
            "suchname": f"{antrag['vorname']} {antrag['nachname']}".lower(),
            "suchkfz": db.kfz_normalisieren(antrag["kennzeichen"] or ""),
        }
        for antrag in db.antraege_durchfahrt()
    ]


@app.get("/durchfahrt/{token}")
async def durchfahrt_offen(request: Request, token: str):
    """Dieselbe Liste ohne Anmeldung, geschützt nur durch den langen Token.

    Damit braucht niemand an der Sperre das Backoffice-Passwort – und damit
    auch niemand die Rechte zum Genehmigen oder Löschen. Zu sehen sind nur
    Name, Kennzeichen und Kategorie der Berechtigten; keine Kontaktdaten, keine
    Bemerkungen, keine abgelehnten Anträge.
    """
    gueltig = db.durchfahrt_token()
    if not gueltig or not hmac.compare_digest(token, gueltig):
        # Kein eigener Fehlertext: ein zurückgezogener und ein erfundener Link
        # sollen sich nicht unterscheiden lassen.
        raise HTTPException(status_code=404)

    return templates.TemplateResponse(
        "durchfahrt_offen.html", _kontext(request, zeilen=_durchfahrt_zeilen())
    )


@app.post("/admin/durchfahrt/link")
async def admin_durchfahrt_link(
    request: Request, sitzung=Depends(auth.sitzung_erforderlich)
):
    """Offenen Link erzeugen, erneuern oder zurückziehen."""
    daten = await request.form()
    if not auth.csrf_pruefen(sitzung, str(daten.get("csrf") or "")):
        return _csrf_fehler(request, sitzung)

    aktion = str(daten.get("aktion") or "")
    if aktion == "erzeugen":
        db.durchfahrt_token_erzeugen()
        hinweis = "link_neu"
    elif aktion == "zuruecknehmen":
        hinweis = "link_weg" if db.durchfahrt_token_zuruecknehmen() else "nichts"
    else:
        hinweis = "nichts"

    return RedirectResponse("/admin/durchfahrt?hinweis=" + hinweis, status_code=303)


@app.get("/admin/durchfahrt")
async def admin_durchfahrt(
    request: Request, hinweis: str = "", sitzung=Depends(auth.sitzung_erforderlich)
):
    """Nachschlagewerk an der Sperre: wer darf durch, mit welchem Fahrzeug.

    Bewusst schmal – keine Kennzahlen, keine Filter, keine Aktionen. Wer hier
    steht, will einen Namen oder ein Kennzeichen prüfen und sonst nichts.

    Die vollständige Liste geht in einem Rutsch in die Seite; gesucht wird im
    Browser. An der Straßensperre ist der Empfang mies, und eine Suche, die
    dort auf eine Antwort vom Server wartet, ist keine.
    """
    token = db.durchfahrt_token()
    return templates.TemplateResponse(
        "admin_durchfahrt.html",
        _admin_kontext(
            request,
            sitzung,
            zeilen=_durchfahrt_zeilen(),
            offen_url=str(request.base_url).rstrip("/") + "/durchfahrt/" + token
            if token
            else "",
            hinweis=_meldung(hinweis),
        ),
    )


# --- Druckansicht der Karten ------------------------------------------------


def _qr_svg(antrag_id: int) -> str:
    """QR-Code als eingebettetes SVG.

    Eingebettet statt als data:-URI, weil die ausgelieferte CSP `img-src 'self'`
    setzt und data: damit blockiert waere.
    """
    if config.KARTEN_URL_BASIS:
        inhalt = f"{config.KARTEN_URL_BASIS}/admin/antrag/{antrag_id}"
    else:
        inhalt = f"Antrag {antrag_id} – {config.VERANSTALTUNG}"
    # Fehlerkorrektur "M": vertraegt einen Knick in der Karte.
    return segno.make(inhalt, error="m").svg_inline(scale=3, dark="#000000", border=0)


@app.get("/admin/karten")
async def admin_karten(
    request: Request,
    status: str = "genehmigt",
    kategorie: str = "",
    suche: str = "",
    sortierung: str = "name",
    sitzung=Depends(auth.sitzung_erforderlich),
):
    """A6-Karten zum Ausdrucken, vier Stueck auf einen A4-Bogen.

    Vorgabe ist `genehmigt`: gedruckt wird, was ausgegeben werden soll. Wer
    andere Anträge braucht, stellt den Filter um – die Auswahl funktioniert wie
    in der Liste.
    """
    status = status if status in db.STATUS_WERTE else ""
    kategorie = kategorie if kategorie in config.KATEGORIE_KEYS else ""
    sortierung = sortierung if sortierung in db.SORTIERUNGEN else "name"
    suche = suche.strip()[:100]

    antraege = db.antraege_suchen(status, kategorie, suche, sortierung)
    return templates.TemplateResponse(
        "karten.html",
        _admin_kontext(
            request,
            sitzung,
            antraege=antraege,
            qr={antrag["id"]: _qr_svg(antrag["id"]) for antrag in antraege},
            logo=config.LOGO_DATEI if config.logo_vorhanden() else "",
            filter_status=status,
            filter_kategorie=kategorie,
            filter_suche=suche,
            sortierung=sortierung,
        ),
    )


# --- Telefonisch zu informieren ---------------------------------------------


@app.get("/admin/telefon")
async def admin_telefon(
    request: Request, hinweis: str = "", sitzung=Depends(auth.sitzung_erforderlich)
):
    """Entschiedene Anträge ohne Mailadresse – wen die Orga noch anrufen muss."""
    return templates.TemplateResponse(
        "admin_telefon.html",
        _admin_kontext(
            request,
            sitzung,
            antraege=db.antraege_telefonisch(),
            hinweis=_meldung(hinweis),
        ),
    )


@app.post("/admin/antrag/{antrag_id}/telefoniert")
async def admin_telefoniert(
    request: Request, antrag_id: int, sitzung=Depends(auth.sitzung_erforderlich)
):
    daten = await request.form()
    if not auth.csrf_pruefen(sitzung, str(daten.get("csrf") or "")):
        return _csrf_fehler(request, sitzung)

    if db.antrag_laden(antrag_id) is None:
        return _nicht_gefunden(request, sitzung)

    erledigt = str(daten.get("erledigt") or "1") == "1"
    db.tel_informiert_setzen(antrag_id, erledigt)

    zurueck = _weiter_pfad(str(daten.get("zurueck") or "/admin/telefon"))
    trenner = "&" if "?" in zurueck else "?"
    hinweis = "angerufen" if erledigt else "anruf_offen"
    return RedirectResponse(zurueck + trenner + "hinweis=" + hinweis, status_code=303)


# --- Mail-Queue -------------------------------------------------------------


@app.post("/admin/mail/{mail_id}/erneut")
async def admin_mail_erneut(
    request: Request, mail_id: int, sitzung=Depends(auth.sitzung_erforderlich)
):
    """Aufgegebene Mail von Hand wieder in die Schlange stellen."""
    daten = await request.form()
    if not auth.csrf_pruefen(sitzung, str(daten.get("csrf") or "")):
        return _csrf_fehler(request, sitzung)

    erneut = db.mail_erneut(mail_id)
    antrag_id = int(str(daten.get("antrag_id") or "0") or 0)
    if antrag_id:
        return _zum_antrag(antrag_id, "mail_erneut" if erneut else "nichts")
    return RedirectResponse("/admin", status_code=303)
