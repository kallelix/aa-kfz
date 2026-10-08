"""Anmelden, Abmelden und die Fehlerseiten dazu – für jeden Bereich gleich.

Stand vorher dreimal fast wortgleich in kennzeichen, presse und helfer. Mit
den Konten wäre jede Änderung dreimal zu machen gewesen; jetzt hängt jeder
Bereich sie sich mit einem Aufruf an:

    anmeldung.einrichten(app, auth=auth, templates=templates,
                         kontext=_kontext, bereich="presse")

Die Routen bleiben, wo sie waren – /presse/login, /presse/logout –, denn
jeder Bereich lässt sich auch für sich allein starten.
"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import Request
from fastapi.responses import RedirectResponse

from kern import auth as kern_auth
from kern import navigation


def einrichten(app, *, auth, templates, kontext, bereich: str,
               erlaubt: tuple = ()) -> None:
    """``kontext(request, **extra)`` liefert die Grundwerte jeder Seite des
    Bereichs. ``erlaubt`` sind weitere Pfadanfänge, auf die nach der
    Anmeldung weitergeleitet werden darf."""
    start = "/" + bereich
    anfaenge = (start,) + tuple(erlaubt)

    def weiter_pfad(roh: str) -> str:
        """Nur eigene Backoffice-Pfade – sonst wäre das eine offene
        Weiterleitung."""
        if (any(roh == a or roh.startswith(a.rstrip("/") + "/") or roh.startswith(a + "?")
                for a in anfaenge)
                and not roh.startswith("//") and "\\" not in roh):
            return roh
        return start

    def anmeldeseite(request, *, fehler="", weiter=start, email="", kuerzel="",
                     status_code=200):
        return templates.TemplateResponse(
            "admin_login.html",
            kontext(
                request,
                fehler=fehler,
                weiter=weiter,
                email=email,
                kuerzel=kuerzel,
                konten=auth.kontenmodus(),
                kuerzel_abfragen=getattr(auth.config, "KUERZEL_ABFRAGEN", True),
                verwaltung=kern_auth.VERWALTUNG,
            ),
            status_code=status_code,
        )

    @app.exception_handler(kern_auth.NichtAngemeldet)
    async def _nicht_angemeldet(request: Request, ausnahme):
        return RedirectResponse(f"{start}/login?weiter=" + quote(ausnahme.ziel),
                                status_code=303)

    @app.exception_handler(kern_auth.NichtEingerichtet)
    async def _nicht_eingerichtet(request: Request, ausnahme):
        return templates.TemplateResponse(
            "admin_nicht_eingerichtet.html", kontext(request), status_code=503)

    @app.exception_handler(kern_auth.KeinZugang)
    async def _kein_zugang(request: Request, ausnahme):
        sitzung = auth.sitzung_lesen(request)
        return templates.TemplateResponse(
            "kein_zugang.html",
            kontext(
                request,
                sitzung=sitzung,
                csrf=auth.csrf_token(sitzung.token) if sitzung else "",
                bereiche=navigation.bereiche(request.url.path, sitzung),
                grund=ausnahme.grund,
            ),
            status_code=403,
        )

    @app.get(f"{start}/login")
    async def login_formular(request: Request, weiter: str = start):
        if auth.sitzung_lesen(request) is not None:
            return RedirectResponse(weiter_pfad(weiter), status_code=303)
        if not auth.eingerichtet():
            raise kern_auth.NichtEingerichtet()
        return anmeldeseite(request, weiter=weiter_pfad(weiter))

    @app.post(f"{start}/login")
    async def login_absenden(request: Request):
        if not auth.eingerichtet():
            raise kern_auth.NichtEingerichtet()
        daten = await request.form()
        weiter = weiter_pfad(str(daten.get("weiter") or start))
        email = str(daten.get("email") or "").strip()[:200]
        kuerzel = str(daten.get("kuerzel") or "").strip()[:20]
        # uvicorn setzt request.client bei --proxy-headers schon aus
        # X-Forwarded-For; die Header selbst zu lesen wäre fälschbar.
        ip = request.client.host if request.client else "unbekannt"

        if auth.login_gesperrt(ip, email):
            return anmeldeseite(request, fehler="Zu viele Fehlversuche. Bitte eine Minute warten.",
                                weiter=weiter, email=email, kuerzel=kuerzel, status_code=429)

        token = auth.anmelden(email, str(daten.get("passwort") or ""), kuerzel)
        if token is None:
            auth.login_fehlversuch(ip, email)
            meldung = ("Mailadresse oder Passwort stimmt nicht." if auth.kontenmodus()
                       else "Passwort stimmt nicht.")
            return anmeldeseite(request, fehler=meldung, weiter=weiter, email=email,
                                kuerzel=kuerzel, status_code=401)

        auth.login_zuruecksetzen(ip, email)
        antwort = RedirectResponse(weiter, status_code=303)
        auth.cookie_setzen(antwort, request, token)
        return antwort

    @app.post(f"{start}/logout")
    async def logout(request: Request):
        sitzung = auth.sitzung_lesen(request)
        daten = await request.form()
        if sitzung is not None and not auth.csrf_pruefen(sitzung, str(daten.get("csrf") or "")):
            raise kern_auth.NichtAngemeldet(start)
        auth.abmelden(request)
        antwort = RedirectResponse(f"{start}/login", status_code=303)
        auth.cookie_loeschen(antwort)
        return antwort
