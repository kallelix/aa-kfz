"""Was dem Backoffice als ganzem gehört: Startseite, Konten, Veranstaltungen.

Liegt unter der Backoffice-Adresse neben den drei Bereichen:

    /                    Startseite: die Bereiche, die das Konto sehen darf
    /veranstaltungen     Veranstaltungen anlegen und ändern (Admin, Helfer-Orga)
    /konten              alle Konten (nur Admin): anlegen, ändern, sperren
    /konto               das eigene Konto: Passwort ändern
    /konto/passwort/…    Link aus der Mail: Passwort setzen
    /konto/vergessen     neuen Link anfordern
    /konto/login         Anmeldung, wie in den Bereichen

Eingeladen wird per Mail, über das Postfach, das dienst/main.py mitgibt.
Kommt die Mail nicht hinaus, zeigt die Seite dem Admin den Link – er kann
ihn dann selbst weitergeben, statt dass das Konto in der Luft hängt.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from jinja2 import ChoiceLoader, FileSystemLoader

from kern import anmeldung, navigation
from kern import mail as kern_mail
from kern.auth import Auth
from kern import veranstaltungen as va
from kern.konten import (BEREICHE, EINLADUNG_GILT, ROLLEN, ROLLEN_TEXT,
                         ZURUECKSETZEN_GILT, Fehler)

protokoll = logging.getLogger("uvicorn.error")

VORLAGEN = Path(__file__).resolve().parent / "templates"

MELDUNGEN = {
    "eingeladen": "Konto angelegt, die Einladung ist per Mail unterwegs.",
    "gespeichert": "Änderungen gespeichert.",
    "link": "Der Link ist per Mail unterwegs.",
    "abgemeldet": "Das Konto ist auf allen Geräten abgemeldet.",
    "passwort": "Dein neues Passwort gilt. Andere Geräte sind abgemeldet.",
    "telefon": "Deine Nummer ist gespeichert.",
    "willkommen": "Dein Passwort ist gesetzt – du bist angemeldet.",
    "va-angelegt": "Veranstaltung angelegt.",
    "va-geloescht": "Veranstaltung gelöscht.",
}


def darf_veranstaltungen(sitzung) -> bool:
    """Siehe Sitzung.pflegt_veranstaltungen."""
    return sitzung.pflegt_veranstaltungen


def _zeit(wert) -> str:
    if not wert:
        return ""
    if isinstance(wert, datetime):
        return wert.astimezone().strftime("%d.%m.%Y %H:%M")
    return str(wert)


def bauen(config, mail_config=None) -> FastAPI:
    """``config`` liefert Schlüssel, Sitzungsdauer, Datenbank und den Namen
    der Veranstaltung; ``mail_config`` das Postfach für die Einladungen."""
    mail_config = mail_config or config
    auth = Auth(config)
    konten = auth.konten
    veranstaltungen = va.Veranstaltungen(lambda: config.DATABASE_URL)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    templates = Jinja2Templates(directory=str(VORLAGEN / "konten"))
    templates.env.loader = ChoiceLoader([
        FileSystemLoader(str(VORLAGEN / "konten")),
        FileSystemLoader(str(VORLAGEN)),
    ])
    templates.env.filters["zeit"] = _zeit

    def kontext(request: Request, **extra) -> dict:
        return {"request": request, "bereich": "konto", "bereich_name": "Konten",
                "veranstaltung": config.VERANSTALTUNG, **extra}

    def admin_kontext(request: Request, sitzung, **extra) -> dict:
        """Diese Seiten stehen unter dem Reiter Verwaltung – bis auf die
        Startseite und das eigene Konto, die unter keinem stehen."""
        kopf = navigation.kopf(request, sitzung, veranstaltungen)
        gliederung = {"gruppen": [], "bereichsnav": []}
        if navigation.reiter_von(request.url.path) == "verwaltung":
            gliederung = navigation.gegliedert(
                navigation.verwaltung(sitzung, kopf["va_aktuell"]), request.url.path)
        hinweis = MELDUNGEN.get(request.query_params.get("hinweis", ""), "")
        return kontext(
            request,
            sitzung=sitzung,
            csrf=auth.csrf_token(sitzung.token),
            hinweis=hinweis,
            **kopf,
            **gliederung,
            **extra,
        )

    anmeldung.einrichten(app, auth=auth, templates=templates, kontext=kontext,
                         bereich="konto", erlaubt=("/konten", "/veranstaltungen", "/"))

    @app.get("/veranstaltung")
    async def veranstaltung_waehlen(request: Request, id: str = "", weiter: str = "/",
                                    sitzung=Depends(auth.angemeldet)):
        """Merkt sich im Browser, mit welcher Veranstaltung gearbeitet wird –
        für alle Bereiche. Ein Link statt eines Formulars: die Auswahl im Kopf
        geht so auch ohne Skript."""
        zeile = veranstaltungen.laden(id)
        # Nur eigene Pfade – sonst wäre das eine offene Weiterleitung.
        if not weiter.startswith("/") or weiter.startswith("//") or "\\" in weiter:
            weiter = "/"
        antwort = RedirectResponse(weiter, status_code=303)
        if zeile is not None:
            antwort.set_cookie(va.KEKS, str(zeile["id"]), max_age=400 * 24 * 3600,
                               httponly=True, samesite="lax",
                               secure=auth.keks_sicher(request), path="/")
        return antwort

    def veranstaltungen_erforderlich(request: Request):
        sitzung = auth.sitzung_erforderlich(request)
        if not darf_veranstaltungen(sitzung):
            raise auth.KeinZugang("bereich")
        return sitzung

    async def csrf_formular(request: Request, sitzung) -> dict:
        daten = await request.form()
        if not auth.csrf_pruefen(sitzung, str(daten.get("csrf") or "")):
            raise auth.NichtAngemeldet(request.url.path)
        return daten

    # --- Mails ------------------------------------------------------------------

    def link_text(request: Request, token: str) -> str:
        return str(request.base_url).rstrip("/") + "/konto/passwort/" + token

    def einladung_text(request, konto, link: str, von: str) -> tuple[str, str]:
        bereiche = ("alle" if konto["rolle"] == "admin"
                    else ", ".join(BEREICHE[b] for b in konto["bereiche"]))
        tage = EINLADUNG_GILT.days
        betreff = f"Dein Zugang zum Backoffice – {config.VERANSTALTUNG}"
        text = (
            f"Hallo {konto['name']},\n\n"
            f"{von or 'Die Orga'} hat dir ein Konto fürs Backoffice von "
            f"{config.VERANSTALTUNG} angelegt.\n"
            f"Rolle: {ROLLEN[konto['rolle']]} – {ROLLEN_TEXT[konto['rolle']]}.\n"
            f"Bereiche: {bereiche}.\n\n"
            f"Über diesen Link legst du dein Passwort fest:\n{link}\n\n"
            f"Der Link gilt {tage} Tage. Danach meldest du dich mit deiner "
            f"Mailadresse ({konto['email']}) und deinem Passwort an:\n"
            f"{str(request.base_url).rstrip('/')}/\n\n"
            "Kommt dir die Mail komisch vor, ignoriere sie einfach.\n"
        )
        return betreff, text

    def zuruecksetzen_text(konto, link: str) -> tuple[str, str]:
        stunden = int(ZURUECKSETZEN_GILT.total_seconds() // 3600)
        betreff = f"Neues Passwort fürs Backoffice – {config.VERANSTALTUNG}"
        text = (
            f"Hallo {konto['name']},\n\n"
            f"für dein Konto im Backoffice von {config.VERANSTALTUNG} wurde ein "
            "neues Passwort angefordert. Über diesen Link legst du es fest:\n"
            f"{link}\n\n"
            f"Der Link gilt {stunden} Stunden. Hast du nichts angefordert, ignoriere "
            "die Mail – dein bisheriges Passwort bleibt gültig.\n"
        )
        return betreff, text

    async def verschicken(empfaenger: str, betreff: str, text: str) -> str:
        """Leer, wenn die Mail hinaus ist, sonst der Grund."""
        try:
            await asyncio.to_thread(kern_mail.senden, mail_config, empfaenger, betreff, text)
            return ""
        except kern_mail.NichtEingerichtet:
            return "Für den Versand ist kein Postfach eingerichtet."
        except Exception as fehler:  # noqa: BLE001 - SMTP kann vieles werfen
            protokoll.warning("Kontenmail an %s ging nicht hinaus: %s", empfaenger, fehler)
            return "Der Mailserver hat abgelehnt: " + str(fehler)[:200]

    async def link_schicken(request: Request, konto, von: str = ""):
        """Einladung oder Zurücksetzen, je nachdem, ob das Konto schon ein
        Passwort hat. Gibt (link, fehlergrund) zurück."""
        if konto["passwort_hash"]:
            token = konten.link_anlegen(konto["id"], "zuruecksetzen")
            betreff, text = zuruecksetzen_text(konto, link_text(request, token))
        else:
            token = konten.link_anlegen(konto["id"], "einladung")
            betreff, text = einladung_text(request, konto, link_text(request, token), von)
        grund = await verschicken(konto["email"], betreff, text)
        return link_text(request, token), grund

    # --- Startseite -------------------------------------------------------------

    @app.get("/", response_class=HTMLResponse)
    async def startseite(request: Request, sitzung=Depends(auth.angemeldet)):
        return templates.TemplateResponse(
            "startseite.html",
            admin_kontext(request, sitzung, titel="Backoffice"))

    # --- Veranstaltungen --------------------------------------------------------

    def va_formular(request, sitzung, *, werte, veranstaltung=None, fehler="",
                    status_code=200):
        return templates.TemplateResponse(
            "veranstaltung_form.html",
            admin_kontext(request, sitzung, werte=werte, va_zeile=veranstaltung,
                          fehler=fehler, status_werte=va.STATUS,
                          status_text=va.STATUS_TEXT, nutzbar=va.NUTZBAR),
            status_code=status_code)

    def va_werte(daten) -> dict:
        werte = {feld: str(daten.get(feld) or "") for feld in
                 ("name", "kurz", "beginn", "ende", "ort", "beschreibung", "status",
                  "anmeldung_ab", "anmeldung_bis")}
        werte["nutzt"] = [b for b in va.NUTZBAR if daten.get("nutzt_" + b)]
        return werte

    @app.get("/veranstaltungen", response_class=HTMLResponse)
    async def va_liste(request: Request, sitzung=Depends(veranstaltungen_erforderlich)):
        vorgabe = veranstaltungen.vorgabe()
        return templates.TemplateResponse(
            "veranstaltungen.html",
            admin_kontext(request, sitzung, liste=veranstaltungen.liste(),
                          vorgabe_id=vorgabe["id"] if vorgabe else None,
                          status_werte=va.STATUS, nutzbar=va.NUTZBAR))

    @app.get("/veranstaltungen/neu", response_class=HTMLResponse)
    async def va_neu(request: Request, sitzung=Depends(veranstaltungen_erforderlich)):
        return va_formular(request, sitzung,
                           werte={"status": "planung", "nutzt": list(va.NUTZBAR)})

    @app.post("/veranstaltungen/neu", response_class=HTMLResponse)
    async def va_anlegen(request: Request, sitzung=Depends(veranstaltungen_erforderlich)):
        daten = await csrf_formular(request, sitzung)
        werte = va_werte(daten)
        try:
            veranstaltungen.anlegen(werte)
        except va.Fehler as fehler:
            return va_formular(request, sitzung, werte=werte, fehler=str(fehler),
                               status_code=400)
        return RedirectResponse("/veranstaltungen?hinweis=va-angelegt", status_code=303)

    @app.get("/veranstaltungen/{veranstaltung_id}", response_class=HTMLResponse)
    async def va_zeigen(request: Request, veranstaltung_id: int,
                        sitzung=Depends(veranstaltungen_erforderlich)):
        zeile = veranstaltungen.laden(veranstaltung_id)
        if zeile is None:
            return RedirectResponse("/veranstaltungen", status_code=303)
        return va_formular(request, sitzung, werte=dict(zeile), veranstaltung=zeile)

    @app.post("/veranstaltungen/{veranstaltung_id}", response_class=HTMLResponse)
    async def va_aendern(request: Request, veranstaltung_id: int,
                         sitzung=Depends(veranstaltungen_erforderlich)):
        daten = await csrf_formular(request, sitzung)
        zeile = veranstaltungen.laden(veranstaltung_id)
        if zeile is None:
            return RedirectResponse("/veranstaltungen", status_code=303)
        werte = va_werte(daten)
        try:
            veranstaltungen.aendern(veranstaltung_id, werte)
        except va.Fehler as fehler:
            return va_formular(request, sitzung, werte=werte, veranstaltung=zeile,
                               fehler=str(fehler), status_code=400)
        return RedirectResponse(f"/veranstaltungen/{veranstaltung_id}?hinweis=gespeichert",
                                status_code=303)

    @app.post("/veranstaltungen/{veranstaltung_id}/loeschen", response_class=HTMLResponse)
    async def va_loeschen(request: Request, veranstaltung_id: int,
                          sitzung=Depends(veranstaltungen_erforderlich)):
        await csrf_formular(request, sitzung)
        zeile = veranstaltungen.laden(veranstaltung_id)
        if zeile is None:
            return RedirectResponse("/veranstaltungen", status_code=303)
        try:
            veranstaltungen.loeschen(veranstaltung_id)
        except va.Fehler as fehler:
            return va_formular(request, sitzung, werte=dict(zeile), veranstaltung=zeile,
                               fehler=str(fehler), status_code=400)
        return RedirectResponse("/veranstaltungen?hinweis=va-geloescht", status_code=303)

    # --- Alle Konten (Admin) ----------------------------------------------------

    def formular_werte(daten) -> dict:
        return {
            "name": str(daten.get("name") or "").strip(),
            "email": str(daten.get("email") or "").strip(),
            "kuerzel": str(daten.get("kuerzel") or "").strip(),
            "rolle": str(daten.get("rolle") or ""),
            "bereiche": [b for b in BEREICHE if daten.get("bereich_" + b)],
            "telefon": str(daten.get("telefon") or "").strip(),
        }

    def kontoformular(request, sitzung, *, werte, konto=None, fehler="", status_code=200):
        return templates.TemplateResponse(
            "konto_form.html",
            admin_kontext(request, sitzung, werte=werte, konto=konto, fehler=fehler,
                          rollen=ROLLEN, rollen_text=ROLLEN_TEXT, alle_bereiche=BEREICHE),
            status_code=status_code)

    @app.get("/konten", response_class=HTMLResponse)
    async def konten_liste(request: Request, sitzung=Depends(auth.admin_erforderlich)):
        return templates.TemplateResponse(
            "konten.html",
            admin_kontext(request, sitzung, konten=konten.liste(), rollen=ROLLEN,
                          alle_bereiche=BEREICHE))

    @app.get("/konten/neu", response_class=HTMLResponse)
    async def konto_neu(request: Request, sitzung=Depends(auth.admin_erforderlich)):
        werte = {"name": "", "email": "", "kuerzel": "", "rolle": "orga", "bereiche": [],
                 "telefon": ""}
        return kontoformular(request, sitzung, werte=werte)

    @app.post("/konten/neu", response_class=HTMLResponse)
    async def konto_anlegen(request: Request, sitzung=Depends(auth.admin_erforderlich)):
        daten = await csrf_formular(request, sitzung)
        werte = formular_werte(daten)
        von = sitzung.name or sitzung.kuerzel
        try:
            konto_id = konten.anlegen(**werte, von=von)
        except Fehler as fehler:
            return kontoformular(request, sitzung, werte=werte, fehler=str(fehler),
                                 status_code=400)
        link, grund = await link_schicken(request, konten.laden(konto_id), von)
        if grund:
            return templates.TemplateResponse(
                "konto_link.html",
                admin_kontext(request, sitzung, konto=konten.laden(konto_id),
                              link=link, grund=grund))
        return RedirectResponse("/konten?hinweis=eingeladen", status_code=303)

    @app.get("/konten/{konto_id}", response_class=HTMLResponse)
    async def konto_zeigen(request: Request, konto_id: int,
                           sitzung=Depends(auth.admin_erforderlich)):
        konto = konten.laden(konto_id)
        if konto is None:
            return RedirectResponse("/konten", status_code=303)
        return kontoformular(request, sitzung, werte=dict(konto), konto=konto)

    @app.post("/konten/{konto_id}", response_class=HTMLResponse)
    async def konto_aendern(request: Request, konto_id: int,
                            sitzung=Depends(auth.admin_erforderlich)):
        daten = await csrf_formular(request, sitzung)
        konto = konten.laden(konto_id)
        if konto is None:
            return RedirectResponse("/konten", status_code=303)
        werte = formular_werte(daten)
        try:
            konten.aendern(konto_id, **werte, aktiv=bool(daten.get("aktiv")))
        except Fehler as fehler:
            return kontoformular(request, sitzung, werte=werte, konto=konto,
                                 fehler=str(fehler), status_code=400)
        return RedirectResponse(f"/konten/{konto_id}?hinweis=gespeichert", status_code=303)

    @app.post("/konten/{konto_id}/link", response_class=HTMLResponse)
    async def konto_link(request: Request, konto_id: int,
                         sitzung=Depends(auth.admin_erforderlich)):
        await csrf_formular(request, sitzung)
        konto = konten.laden(konto_id)
        if konto is None or not konto["aktiv"]:
            return RedirectResponse("/konten", status_code=303)
        link, grund = await link_schicken(request, konto, sitzung.name or sitzung.kuerzel)
        if grund:
            return templates.TemplateResponse(
                "konto_link.html",
                admin_kontext(request, sitzung, konto=konto, link=link, grund=grund))
        return RedirectResponse(f"/konten/{konto_id}?hinweis=link", status_code=303)

    @app.post("/konten/{konto_id}/abmelden")
    async def konto_abmelden(request: Request, konto_id: int,
                             sitzung=Depends(auth.admin_erforderlich)):
        await csrf_formular(request, sitzung)
        konten.sitzungen_beenden(konto_id)
        return RedirectResponse(f"/konten/{konto_id}?hinweis=abgemeldet", status_code=303)

    # --- Das eigene Konto -------------------------------------------------------

    @app.get("/konto", response_class=HTMLResponse)
    async def mein_konto(request: Request, sitzung=Depends(auth.angemeldet)):
        if sitzung.konto_id is None:
            # Mit dem gemeinsamen Passwort gibt es kein eigenes Konto.
            return RedirectResponse("/konten", status_code=303)
        return templates.TemplateResponse(
            "konto_mein.html",
            admin_kontext(request, sitzung, konto=konten.laden(sitzung.konto_id),
                          rollen=ROLLEN, rollen_text=ROLLEN_TEXT, alle_bereiche=BEREICHE,
                          fehler=""))

    @app.post("/konto/telefon")
    async def telefon_aendern(request: Request, sitzung=Depends(auth.angemeldet)):
        await csrf_formular(request, sitzung)
        if sitzung.konto_id is None:
            return RedirectResponse("/konten", status_code=303)
        daten = await request.form()
        konten.telefon_setzen(sitzung.konto_id, str(daten.get("telefon") or ""))
        return RedirectResponse("/konto?hinweis=telefon", status_code=303)

    @app.post("/konto/passwort", response_class=HTMLResponse)
    async def passwort_aendern(request: Request, sitzung=Depends(auth.angemeldet)):
        daten = await csrf_formular(request, sitzung)
        if sitzung.konto_id is None:
            return RedirectResponse("/konten", status_code=303)
        alt = str(daten.get("alt") or "")
        neu = str(daten.get("neu") or "")
        fehler = ""
        if not konten.passwort_stimmt(sitzung.konto_id, alt):
            fehler = "Dein bisheriges Passwort stimmt nicht."
        elif neu != str(daten.get("wiederholung") or ""):
            fehler = "Die beiden neuen Passwörter sind nicht gleich."
        else:
            try:
                konten.passwort_setzen(sitzung.konto_id, neu, ausser_sitzung=sitzung.token)
            except Fehler as f:
                fehler = str(f)
        if fehler:
            return templates.TemplateResponse(
                "konto_mein.html",
                admin_kontext(request, sitzung, konto=konten.laden(sitzung.konto_id),
                              rollen=ROLLEN, rollen_text=ROLLEN_TEXT,
                              alle_bereiche=BEREICHE, fehler=fehler),
                status_code=400)
        return RedirectResponse("/konto?hinweis=passwort", status_code=303)

    # --- Passwort über den Link aus der Mail ---------------------------------------

    def setzen_seite(request, *, konto, token, fehler="", status_code=200):
        return templates.TemplateResponse(
            "konto_passwort_setzen.html",
            kontext(request, konto=konto, token=token, fehler=fehler,
                    titel="Passwort festlegen"),
            status_code=status_code)

    @app.get("/konto/passwort/{token}", response_class=HTMLResponse)
    async def link_oeffnen(request: Request, token: str):
        # Nur anzeigen, nicht einlösen: Mailscanner rufen Links vorab auf.
        # Eingelöst wird erst mit dem Absenden des Formulars.
        konto = konten.link_lesen(token)
        return setzen_seite(request, konto=konto, token=token,
                            status_code=200 if konto else 410)

    @app.post("/konto/passwort/{token}", response_class=HTMLResponse)
    async def link_einloesen(request: Request, token: str):
        daten = await request.form()
        konto = konten.link_lesen(token)
        if konto is None:
            return setzen_seite(request, konto=None, token=token, status_code=410)
        neu = str(daten.get("neu") or "")
        if neu != str(daten.get("wiederholung") or ""):
            return setzen_seite(request, konto=konto, token=token, status_code=400,
                                fehler="Die beiden Passwörter sind nicht gleich.")
        try:
            konto = konten.link_einloesen(token, neu)
        except Fehler as fehler:
            return setzen_seite(request, konto=konto, token=token, fehler=str(fehler),
                                status_code=400)
        if konto is None:
            return setzen_seite(request, konto=None, token=token, status_code=410)
        # Gleich angemeldet - wer gerade sein Passwort gesetzt hat, soll es
        # nicht sofort noch einmal tippen müssen.
        sitzung = konten.sitzung_anlegen(konto["id"], timedelta(hours=config.SESSION_STUNDEN))
        antwort = RedirectResponse("/?hinweis=willkommen", status_code=303)
        auth.cookie_setzen(antwort, request, sitzung)
        return antwort

    # --- Passwort vergessen ------------------------------------------------------

    def vergessen_seite(request, *, email="", fertig=False, fehler="", status_code=200):
        return templates.TemplateResponse(
            "konto_vergessen.html",
            kontext(request, email=email, fertig=fertig, fehler=fehler,
                    titel="Passwort vergessen"),
            status_code=status_code)

    @app.get("/konto/vergessen", response_class=HTMLResponse)
    async def vergessen(request: Request):
        return vergessen_seite(request)

    @app.post("/konto/vergessen", response_class=HTMLResponse)
    async def vergessen_absenden(request: Request):
        daten = await request.form()
        email = str(daten.get("email") or "").strip()[:200]
        ip = request.client.host if request.client else "unbekannt"
        # Jede Anfrage zählt, nicht nur Fehlversuche: sonst ließe sich über
        # dieses Formular beliebig viel Post an fremde Adressen auslösen.
        schluessel = "vergessen:" + ip
        if auth.login_gesperrt(schluessel, email):
            return vergessen_seite(request, email=email, status_code=429,
                                   fehler="Zu viele Anfragen. Bitte eine Minute warten.")
        auth.login_fehlversuch(schluessel, email)
        konto = konten.nach_email(email)
        if konto is not None and konto["aktiv"]:
            await link_schicken(request, konto)
        # Dieselbe Antwort, ob es das Konto gibt oder nicht - sonst ließe
        # sich hier abfragen, wer eins hat.
        return vergessen_seite(request, email=email, fertig=True)

    return app
