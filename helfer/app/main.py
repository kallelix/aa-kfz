"""Helfer-Dashboard – Backoffice für die Schichtplanung.

Anders als die beiden Schwester-Apps gibt es hier kein öffentliches Formular:
Helfer melden sich nicht selbst an, die Orga teilt ein. Öffentlich ist später
nur die Monitoransicht hinter einem Token.

Die App spricht nur HTTP und lauscht auf 127.0.0.1 bzw. der eigenen IP. TLS
macht der Reverse Proxy davor; gestartet wird mit `python -m app`.
"""

from __future__ import annotations

import asyncio
import csv
import hmac
import io
import logging
import re
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlencode

from fastapi import Depends, FastAPI, Request
from fastapi.responses import (JSONResponse, RedirectResponse,
                               Response)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import ChoiceLoader, FileSystemLoader
from starlette.convertors import StringConvertor, register_url_convertor

from . import (band, config, csv_import, db, eintraege, ical, mail, normalisieren,
               planung, selbstanmeldung, unterschriften, versand, worker, zeitplan,
               zugang)

# Die Repo-Wurzel steht schon auf dem Suchpfad - siehe __init__.py.
from . import WURZEL as _WURZELPFAD
_WURZEL = str(_WURZELPFAD)

from kern import anmeldung, navigation
from kern import auth as kern_auth
from kern import veranstaltungen as va
from kern.auth import Auth

WURZEL_STATIC = Path(_WURZEL) / "kern" / "static"

BASIS = Path(__file__).resolve().parent
# Eine Instanz je Anwendung: die drei laufen in einem Prozess und haben
# verschiedene Schluessel, Passwoerter und Sitzungsdauern. Sie heisst `auth`,
# damit jede Aufrufstelle bleibt, wie sie war.
auth = Auth(config, bereich="helfer")

# Zwei Sucher: erst die eigenen Vorlagen, dann die gemeinsamen aus kern. So
# kann jede Anwendung eine gemeinsame Vorlage ueberschreiben, indem sie eine
# gleichnamige daneben legt - und niemand muss dafuer kern anfassen.
templates = Jinja2Templates(directory=str(BASIS / "templates"))
templates.env.loader = ChoiceLoader([
    FileSystemLoader(str(BASIS / "templates")),
    FileSystemLoader(str(Path(_WURZEL) / "kern" / "templates")),
])

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


def _tag_lang(wert):
    """'2027-07-02' -> 'Freitag, 02.07.' – für die öffentliche Liste."""
    try:
        zeit = datetime.fromisoformat(str(wert))
    except ValueError:
        return wert
    return config.WOCHENTAGE[zeit.weekday()] + zeit.strftime(", %d.%m.")


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
templates.env.filters["tag_lang"] = lambda wert: _tag_lang(wert)
templates.env.filters["spanne"] = _spanne
templates.env.filters["programmzeit"] = _programmzeit
templates.env.filters["ausschnitt"] = unterschriften.ausschnitt


def _stufe(s) -> str:
    """R-02: rot unter Minimum, gelb unter Soll, grün ab Soll. Reserve zählt
    nie als fehlend – sie steckt nicht in `besetzt`."""
    if s["besetzt"] < s["minimum"]:
        return "rot"
    if s["besetzt"] < s["soll"]:
        return "gelb"
    return "gruen"


templates.env.filters["stufe"] = _stufe


# --- Start -----------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Erst kern: die Konten gehören allen Bereichen.
    auth.init()
    eingespielt = db.init()
    if eingespielt:
        protokoll.info("Migrationen eingespielt: %s", ", ".join(eingespielt))
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

    # Mails an Helfer (2.4). Ohne Mail auch keine Fristen: wer keine Mail
    # bekommt, kann nichts bestätigen.
    if config.MAIL_AKTIV:
        if not config.BASIS_URL:
            protokoll.warning("BASIS_URL ist nicht gesetzt - Links in Erinnerungen "
                              "aus dem Hintergrund bleiben ohne Adresse.")
        aufgaben.append(asyncio.create_task(versand.schleife(stop)))
    else:
        protokoll.info("Kein Mailversand an Helfer - die Mails sammeln sich in mail_out, "
                       "und unbestätigte Anmeldungen verfallen nicht.")

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
# Siehe kennzeichen/app/main.py: zweimal dasselbe Verzeichnis. Monitor und
# Tablet liegen unter dem eigenen Hostnamen an der Wurzel und brauchen
# "/static"; das Backoffice liegt unter /helfer.
app.mount("/static", StaticFiles(directory=str(BASIS / "static")), name="static")
app.mount("/helfer/static", StaticFiles(directory=str(BASIS / "static")),
          name="bereichsstatic")

# kern/static zweimal: unter der Wurzel fuer die oeffentlichen Seiten, die
# unter ihrem eigenen Hostnamen liegen, und unter dem Bereich fuers
# Backoffice. Dort liefert zwar auch der Dienst /static aus kern - aber die
# oeffentlichen Seiten erreicht der nie.
_GEMEINSAM = StaticFiles(directory=str(WURZEL_STATIC))
app.mount("/gemeinsam", _GEMEINSAM, name="gemeinsam")
app.mount("/helfer/gemeinsam", _GEMEINSAM, name="bereichsgemeinsam")


# Siehe kennzeichen/app/main.py.
BEREICH = "helfer"
BEREICH_NAME = "Helfer"


def _kontext(request: Request, **extra) -> dict:
    basis = {
        "request": request,
        "bereich": BEREICH,
        # Wo die gemeinsamen Dateien liegen. Ohne Anmeldung ist es eine
        # oeffentliche Seite unter eigenem Hostnamen, dort ohne Bereich.
        "gemeinsam": "/gemeinsam",
        "bereich_name": BEREICH_NAME,
        "veranstaltung": config.VERANSTALTUNG,
        "ort": config.ORT,
        "kontakt_name": config.KONTAKT_NAME,
        "kontakt_mail": config.KONTAKT_MAIL,
        "kontakt_telefon": config.KONTAKT_TELEFON,
    }
    basis.update(extra)
    return basis


class KeineVeranstaltung(Exception):
    """Es gibt noch keine Veranstaltung – ohne sie hat hier nichts einen Platz."""


def _gewaehlt(request: Request):
    """Die Veranstaltung, mit der dieser Browser arbeitet: die gewählte aus
    dem Keks, sonst die Vorgabe. None, solange es keine gibt."""
    return db.veranstaltung(request.cookies.get(va.KEKS, ""))


def _veranstaltung(request: Request):
    """Für Depends: wie _gewaehlt, aber ohne Veranstaltung gibt es die Seite
    nicht – sie zeigt dann, wo man eine anlegt."""
    zeile = _gewaehlt(request)
    if zeile is None:
        raise KeineVeranstaltung()
    return zeile


# --- Bereichsleitung (B-02) -------------------------------------------------

# Was eine Bereichsleitung im Helferbereich öffnen darf: ihre Bereiche mit
# Schichten und Leuten. Alles andere – Ausgaben, Monitor, Import, die ganze
# Helferliste, neue Bereiche – gehört der Orga. Ob es auch IHR Bereich ist,
# prüft die Route selbst (_eigen); hier geht es nur um die Art der Seite.
_BEREICHSLEITUNG_PFADE = re.compile(
    r"^/helfer(/veranstaltung|/bereiche|/bereich/\d+(/schicht/neu)?"
    r"|/schichten|/schicht/\d+(/aendern|/loeschen|/einteilen)?"
    r"|/einteilung/\d+/austragen|/helfer/\d+|/aenderungen"
    r"|/druck(/schicht/\d+|/bereich/\d+|/tag/[0-9-]+|/mappe/[0-9-]+|/person/\d+)?)?$")


def _sitzung(request: Request) -> kern_auth.Sitzung:
    """Wie auth.sitzung_erforderlich, dazu die Grenzen der Bereichsleitung.
    Jede Route im Backoffice hängt daran."""
    sitzung = auth.sitzung_erforderlich(request)
    if (sitzung.ist_bereichsleitung
            and not _BEREICHSLEITUNG_PFADE.match(request.url.path)):
        raise kern_auth.KeinZugang("bereichsleitung")
    return sitzung


def _leitung(sitzung) -> int | None:
    """Das Konto, auf dessen Bereiche eine Ansicht beschränkt ist – nur bei
    einer Bereichsleitung, sonst None."""
    return sitzung.konto_id if sitzung.ist_bereichsleitung else None


def _sieht_grenzen(sitzung) -> bool:
    """Einsatzgrenzen sehen nur Orga und die Leitung des betroffenen
    Bereichs (K-08) – nicht, wer nur lesend dabei ist."""
    return sitzung.rolle in ("admin", "orga") or sitzung.ist_bereichsleitung


def _pflegt_grenzen(sitzung) -> bool:
    """Setzen, aufheben und übersteuern darf nur die Orga (K-05, K-09)."""
    return sitzung.rolle in ("admin", "orga")


def _eigen(sitzung, pruefung, nummer: int) -> None:
    """Bricht ab, wenn eine Bereichsleitung etwas außerhalb ihrer Bereiche
    anfasst. `pruefung` ist eine der db.leitet_*-Funktionen."""
    if sitzung.ist_bereichsleitung and not pruefung(sitzung.konto_id, nummer):
        raise kern_auth.KeinZugang("bereichsleitung")


# Die Meldungen standen bis zur Zusammenfuehrung in der eigenen Huelle des
# Helferbereichs. Die gibt es nicht mehr - die gemeinsame zeigt nur noch, was
# ihr gereicht wird.
MELDUNGEN = {
    'eingeteilt': 'Eingeteilt.',
    'ausgetragen': 'Ausgetragen.',
    'schon-drin': 'Diese Person steht bereits auf der Schicht.',
    'keiner': 'Es war niemand ausgewählt.',
    'unbekannt': 'Diese Schicht gibt es nicht.',
    'neuer-link': 'Neuer Monitor-Link erzeugt. Der alte gilt nicht mehr.',
    'widerrufen': 'Der Monitor-Link ist widerrufen.',
    'angelegt': 'Angelegt.',
    'gespeichert': 'Gespeichert.',
    'geloescht': 'Gelöscht.',
    'status': 'Status geändert.',
    'freigegeben': 'Der Punkt folgt wieder der Website.',
    'tshirt': 'T-Shirt als ausgegeben vermerkt.',
    'tshirt-zurueck': 'Die Ausgabe wurde zurückgenommen.',
    'groesse': 'Diese Größe gibt es nicht.',
    'ausgegeben': 'Material ausgegeben.',
    'neu-angelegt': 'Material ausgegeben – die Person war noch nicht erfasst und wurde angelegt.',
    'nichts': 'Es war nichts zum Ausgeben angekreuzt.',
    'zurueck': 'Als zurück vermerkt.',
    'schluessel-raus': 'Schlüssel ausgegeben.',
    'fahrzeug-neu': 'Schlüssel ausgegeben – das Fahrzeug war neu und steht jetzt im Stamm.',
    'kein-kennzeichen': 'Ohne Kennzeichen geht es nicht.',
    'angefordert': 'Steht auf dem Tablet.',
    'abgebrochen': 'Die Anforderung ist zurückgenommen.',
    'kein-tablet': 'Es gibt keinen Tablet-Link – erst einen erzeugen.',
    'fahrzeug-weg': 'Fahrzeug aus dem Stamm genommen.',
    'fahrzeug-hat-vorgaenge': 'An diesem Fahrzeug hängen noch Vorgänge. Erst die löschen, sonst ginge die Ausgabehistorie mit verloren.',
    'bereich-nicht-leer': 'Der Bereich hat noch Schichten. Erst die löschen oder in einen anderen Bereich legen.',
    'schicht-besetzt': 'Auf dieser Schicht stehen noch Leute. Erst austragen, dann löschen.',
    'alter-gesenkt': 'Gespeichert. Das Mindestalter dieser Schicht liegt unter dem ihres Bereichs – Jugendliche dann nur unter ständiger Aufsicht eines Erwachsenen.',
    'vorlage-nicht': 'Übernehmen geht nur in eine Veranstaltung, die noch keine Bereiche hat.',
    'grenze-gesetzt': 'Einsatzgrenze gespeichert.',
    'grenze-aufgehoben': 'Einsatzgrenze aufgehoben.',
    'grenze-ziel': 'Bitte einen Bereich oder eine Schicht dieser Veranstaltung wählen.',
    'zweit-nur-bereich': '„Nur zu zweit“ gilt für einen ganzen Bereich, nicht für eine einzelne Schicht.',
    'grenze': 'Für diese Person gilt hier eine Einsatzgrenze. Trotzdem einteilen? Dann bitte mit Vermerk.',
    'grenze-orga': 'Für diese Person gilt hier eine Einsatzgrenze. Übersteuern kann das nur die Orga.',
    'vermerk-fehlt': 'Ohne Vermerk geht es nicht.',
}

# Welche davon eine Warnung ist und keine Erfolgsmeldung.
WARNUNGEN = ("schon-drin", "keiner", "unbekannt", "widerrufen", "groesse",
             "nichts", "kein-kennzeichen", "tshirt-zurueck", "geloescht",
             "abgebrochen", "kein-tablet", "bereich-nicht-leer",
             "schicht-besetzt", "alter-gesenkt", "vorlage-nicht", "grenze-ziel",
             "zweit-nur-bereich", "grenze", "grenze-orga", "vermerk-fehlt")


# --- Navigation (Lastenheft 2.1b, kern/navigation.py) -----------------------

# Der Helferbereich nach dem Ablauf: erst planen, dann die Leute, dann der
# Veranstaltungstag. Was man einmal einrichtet, steht nicht hier, sondern bei
# der Veranstaltung (Reiter Verwaltung); Funk und Schlüssel unter Ausgabe.
def _helfer_gruppen(aktuell) -> list:
    vor_ort = []
    # Shirts gibt es nur, wenn die Veranstaltung welche ausgibt.
    if aktuell is not None and db.angebot(aktuell["id"])["shirt"]:
        vor_ort.append(("/helfer/shirts", "Shirts & Goodies", ()))
    vor_ort.append(("/helfer/monitor", "Monitor", ()))
    vor_ort.append(("/helfer/druck", "Drucken", ()))
    return [
        ("Übersicht", [("/helfer", "Übersicht", ()),
                       ("/helfer/aenderungen", "Änderungen", ())]),
        ("Planen", [
            ("/helfer/bereiche", "Bereiche & Schichten",
             ("/helfer/bereich", "/helfer/schichten", "/helfer/schicht")),
            ("/helfer/aufgaben", "Aufgaben", ("/helfer/aufgabe",)),
            ("/helfer/band", "Zeitplan", ())]),
        ("Leute", [("/helfer/helfer", "Helfer", ())]),
        ("Vor Ort", vor_ort),
    ]


# Was eine Bereichsleitung sieht: ihre Bereiche, darin die Schichten.
GRUPPEN_BEREICHSLEITUNG = [
    ("Meine Bereiche", [("/helfer/bereiche", "Meine Bereiche",
                         ("/helfer/bereich", "/helfer/schichten", "/helfer/schicht",
                          "/helfer/helfer")),
                        ("/helfer/aenderungen", "Änderungen", ()),
                        ("/helfer/druck", "Drucken", ())]),
]

# Der Reiter Ausgabe. Bis die Materialausgabe verallgemeinert ist (3.8),
# sind es die beiden Tische von heute.
GRUPPEN_AUSGABE = [
    ("Ausgabe", [("/helfer/funk", "Funk", ("/helfer/ausleihe",)),
                 ("/helfer/schluessel", "Schlüssel", ("/helfer/fahrzeug",))]),
]


def _navigation(request: Request, sitzung, aktuell) -> dict:
    """Gruppen und Punkte für die Seite, je nachdem, unter welchem Reiter sie
    steht – derselbe Bereich liefert Seiten für drei Reiter."""
    pfad = request.url.path
    reiter = navigation.reiter_von(pfad)
    if reiter == "verwaltung":
        gruppen = navigation.verwaltung(sitzung, aktuell)
    elif reiter == "ausgabe":
        gruppen = GRUPPEN_AUSGABE
    elif sitzung.ist_bereichsleitung:
        gruppen = GRUPPEN_BEREICHSLEITUNG
    else:
        gruppen = _helfer_gruppen(aktuell)
    return navigation.gegliedert(gruppen, pfad)


def _admin(request: Request, sitzung: auth.Sitzung, **extra) -> dict:
    # Marke und Takt gehen an jede Backoffice-Seite: das Skript in der
    # Grundvorlage fragt damit nach, ob inzwischen jemand unterschrieben hat.
    #
    # Heisst tabletstand und nicht stand: /helfer/band reicht unter dem Namen
    # bereits den Tagesstand durch, und zwei gleiche Schluesselwoerter waeren
    # keine stille Ueberdeckung, sondern ein Fehler auf jeder solchen Seite.
    roh = str(extra.pop("hinweis", "") or "")
    aktuell = _gewaehlt(request)
    # Die Bereichsleitung hat mit den Ausgabetischen nichts zu tun: kein
    # Tablet-Stand, kein Nachfragen alle paar Sekunden.
    leitung = sitzung.ist_bereichsleitung
    # Kopf und Reiter wie in allen Bereichen. Die Veranstaltung nach der Uhr
    # des Dashboards (JETZT_FEST); gewählt wird sie im gemeinsamen Dienst
    # unter /veranstaltung, für sich allein hier.
    kopf = navigation.kopf(request, sitzung, db.VERANSTALTUNGEN, aktuell=aktuell,
                           wahl=None if sitzung.verwaltung else "/helfer/veranstaltung")
    return _kontext(request, sitzung=sitzung,
                    veranstaltung=aktuell["name"] if aktuell else config.VERANSTALTUNG,
                    ort=aktuell["ort"] if aktuell else config.ORT,
                    nur_eigene=leitung,
                    csrf=auth.csrf_token(sitzung.token),
                    tabletstand=({"offen": None, "marke": 0} if leitung
                                 else unterschriften.stand()),
                    admin_takt=0 if leitung else config.ADMIN_TAKT,
                    gemeinsam="/helfer/gemeinsam",
                    # Die Meldung wird hier aufgeloest, nicht in der Vorlage:
                    # die gemeinsame Huelle kennt die Tabelle nicht.
                    hinweis=MELDUNGEN.get(roh, roh),
                    hinweis_art=("hinweis-warnung" if roh in WARNUNGEN
                                 else "hinweis-ok"),
                    **kopf, **_navigation(request, sitzung, aktuell), **extra)


# --- Anmeldung -------------------------------------------------------------

def _weiter_pfad(roh: str) -> str:
    """Nur eigene Backoffice-Pfade zulassen – sonst wäre das eine offene
    Weiterleitung."""
    if roh.startswith("/helfer") and not roh.startswith("//") and "\\" not in roh:
        return roh
    return "/helfer"




# Anmelden, Abmelden und die Fehlerseiten dazu liegen in kern/anmeldung.py,
# für alle drei Bereiche gleich.
anmeldung.einrichten(app, auth=auth, templates=templates, kontext=_kontext,
                     bereich="helfer")


@app.exception_handler(KeineVeranstaltung)
async def _keine_veranstaltung(request: Request, ausnahme):
    sitzung = auth.sitzung_lesen(request)
    if sitzung is None:
        return RedirectResponse("/helfer/login", status_code=303)
    return templates.TemplateResponse("admin_keine_veranstaltung.html",
                                      _admin(request, sitzung))


@app.get("/helfer/veranstaltung")
async def veranstaltung_waehlen(request: Request, id: str = "", weiter: str = "/helfer",
                                sitzung: auth.Sitzung = Depends(_sitzung)):
    """Merkt sich im Browser, mit welcher Veranstaltung gearbeitet wird.

    Ein Link statt eines Formulars: die Auswahl oben ist eine Klappliste wie
    die Einstellungen daneben, und sie geht ohne Skript.
    """
    zeile = db.VERANSTALTUNGEN.laden(id)
    antwort = RedirectResponse(_weiter_pfad(weiter), status_code=303)
    if zeile is not None:
        antwort.set_cookie(va.KEKS, str(zeile["id"]), max_age=400 * 24 * 3600,
                           httponly=True, samesite="lax",
                           secure=auth.keks_sicher(request), path="/")
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

@app.get("/helfer")
async def uebersicht(request: Request, hinweis: str = "",
                     sitzung: auth.Sitzung = Depends(_sitzung),
                     v=Depends(_veranstaltung)):
    if sitzung.ist_bereichsleitung:
        return RedirectResponse("/helfer/bereiche", status_code=303)
    zaehler = db.zaehler(v["id"])
    # Rot vor gelb (R-02), darin die größten Lücken zuerst.
    luecken = sorted(db.schichten(v["id"], nur_luecken=True),
                     key=lambda z: (_stufe(z) != "rot", -z["fehlt"], z["beginn"]))
    return templates.TemplateResponse(
        "admin_uebersicht.html",
        _admin(request, sitzung, hinweis=hinweis, zaehler=zaehler,
               groessen=normalisieren.GROESSEN,
               luecken=luecken[:12], luecken_gesamt=len(luecken),
               konflikte=db.konflikte(v["id"]), doppelt=db.doppelt_besetzt(v["id"]),
               allein=db.allein(v["id"]) if _sieht_grenzen(sitzung) else [],
               dubletten=db.moegliche_dubletten(),
               jugendschutz=db.jugendschutz(v["id"]),
               kurzfristig=db.kurzfristige_absagen(v["id"]),
               springer=db.springer_lage(v["id"]),
               importe=db.importe()[:1], jetzt=db.jetzt_lokal()))


# --- Schichten -------------------------------------------------------------

@app.get("/helfer/schichten")
async def schichten(request: Request, bereich: str = "", tag: str = "",
                    luecken: str = "", hinweis: str = "",
                    sitzung: auth.Sitzung = Depends(_sitzung),
                    v=Depends(_veranstaltung)):
    f_bereich = int(bereich) if bereich.isdigit() else None
    reihen = db.schichten(v["id"], bereich_id=f_bereich, tag=tag,
                          nur_luecken=bool(luecken), leitung=_leitung(sitzung))
    return templates.TemplateResponse(
        "admin_schichten.html",
        _admin(request, sitzung, hinweis=hinweis, schichten=reihen,
               bereichsliste=db.bereiche(v["id"], _leitung(sitzung)),
               tage=db.tage(v["id"]),
               f_bereich=f_bereich, f_tag=tag, f_luecken=bool(luecken)))


@app.get("/helfer/schicht/{schicht_id}")
async def schicht(request: Request, schicht_id: int, hinweis: str = "",
                  suche: str = "", bestaetigen: str = "",
                  sitzung: auth.Sitzung = Depends(_sitzung),
                  v=Depends(_veranstaltung)):
    eintrag = db.schicht_laden(schicht_id)
    if eintrag is None:
        return templates.TemplateResponse("admin_fehlt.html",
                                          _kontext(request), status_code=404)
    _eigen(sitzung, db.leitet_schicht, schicht_id)
    besetzt = db.besetzung(schicht_id)
    drin = {z["id"] for z in besetzt}
    # Die Rückfrage vor dem Übersteuern einer Einsatzgrenze (K-09).
    trotzdem = None
    if bestaetigen.isdigit() and _pflegt_grenzen(sitzung):
        trotzdem = db.helfer_laden(int(bestaetigen))
    return templates.TemplateResponse(
        "admin_schicht.html",
        _admin(request, sitzung, hinweis=hinweis, schicht=eintrag,
               besetzung=besetzt, suche=suche, trotzdem=trotzdem,
               warteliste=db.warteliste_von(schicht_id),
               sieht_grenzen=_sieht_grenzen(sitzung),
               allein=db.allein(v["id"], schicht_id=schicht_id)
               if _sieht_grenzen(sitzung) else [],
               helfer=[h for h in db.helfer_liste(v["id"]) if h["id"] not in drin]))


@app.post("/helfer/schicht/{schicht_id}/einteilen")
async def einteilen(request: Request, schicht_id: int,
                    sitzung: auth.Sitzung = Depends(_sitzung)):
    daten = await _csrf_pflicht(request, sitzung)
    if daten is None:
        return Response("Ungültiger CSRF-Token", status_code=400)

    ziel = "/helfer/schicht/" + str(schicht_id)
    if db.schicht_laden(schicht_id) is None:
        return _zurueck("/helfer/schichten", "unbekannt")
    _eigen(sitzung, db.leitet_schicht, schicht_id)

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

    # Eine Einsatzgrenze übersteuert nur die Orga, und nur mit Vermerk (K-09).
    vermerk = ""
    if db.unter_grenze(schicht_id, helfer_id):
        if not _pflegt_grenzen(sitzung):
            return _zurueck(ziel, "grenze-orga")
        if not daten.get("trotzdem"):
            return _zurueck(ziel, "grenze", bestaetigen=helfer_id)
        vermerk = " ".join(str(daten.get("vermerk") or "").split())[:200]
        if not vermerk:
            return _zurueck(ziel, "vermerk-fehlt", bestaetigen=helfer_id)

    db.einteilen(schicht_id, helfer_id, quelle="hand", kuerzel=sitzung.kuerzel,
                 vermerk=vermerk)
    return _zurueck(ziel, "eingeteilt")


@app.post("/helfer/einteilung/{einteilung_id}/austragen")
async def austragen(request: Request, einteilung_id: int,
                    sitzung: auth.Sitzung = Depends(_sitzung)):
    daten = await _csrf_pflicht(request, sitzung)
    if daten is None:
        return Response("Ungültiger CSRF-Token", status_code=400)
    ziel = _weiter_pfad(str(daten.get("weiter") or "/helfer/schichten"))
    _eigen(sitzung, db.leitet_einteilung, einteilung_id)
    # Der Platz ist frei: Reserve und Warteliste rücken nach (R-04).
    versand.angebot_mails(db.austragen(einteilung_id, sitzung.kuerzel), _basis(request))
    return _zurueck(ziel, "ausgetragen")


# --- Bereiche und Schichten pflegen (V-03 bis V-06) ------------------------

def _fehlt(request: Request):
    return templates.TemplateResponse("admin_fehlt.html", _kontext(request),
                                      status_code=404)


@app.get("/helfer/bereiche")
async def bereiche(request: Request, hinweis: str = "",
                   sitzung: auth.Sitzung = Depends(_sitzung),
                   v=Depends(_veranstaltung)):
    liste = db.bereiche(v["id"], _leitung(sitzung))
    return templates.TemplateResponse(
        "admin_bereiche.html",
        _admin(request, sitzung, hinweis=hinweis, bereichsliste=liste,
               leitungen=db.leitungen([b["id"] for b in liste]),
               # Die Orga sieht den Hinweis in der Übersicht.
               allein=db.allein(v["id"], sitzung.konto_id)
               if sitzung.ist_bereichsleitung else [],
               kurzfristig=db.kurzfristige_absagen(v["id"], sitzung.konto_id)
               if sitzung.ist_bereichsleitung else [],
               vorlagen=[] if liste or sitzung.ist_bereichsleitung
               else db.vorlagen(v["id"])))


@app.post("/helfer/bereiche/vorlage")
async def bereiche_aus_vorlage(request: Request,
                               sitzung: auth.Sitzung = Depends(_sitzung),
                               v=Depends(_veranstaltung)):
    daten = await _csrf_pflicht(request, sitzung)
    if daten is None:
        return Response("Ungültiger CSRF-Token", status_code=400)
    try:
        quelle = int(str(daten.get("von") or ""))
    except ValueError:
        return _zurueck("/helfer/bereiche", "vorlage-nicht")
    ergebnis = db.vorlage_uebernehmen(v["id"], quelle, sitzung.kuerzel)
    if ergebnis is None:
        return _zurueck("/helfer/bereiche", "vorlage-nicht")
    tage = ergebnis["tage"]
    return _zurueck("/helfer/bereiche", (
        "Übernommen: %d Bereiche, %d Schichten, %d Goodies. " % (
            ergebnis["bereiche"], ergebnis["schichten"], ergebnis["goodies"]) +
        ("Die Schichten liegen %d Tage %s." % (abs(tage), "später" if tage > 0 else "früher")
         if tage else "Die Tage sind dieselben.")))


def _bereich_werte(zeile) -> dict:
    return {f: zeile[f] for f in ("name", "beschreibung", "treffpunkt", "mindestalter",
                                  "voraussetzungen", "intern")}


def _leitung_aus(daten) -> list[int]:
    """Die angekreuzten Konten – nur solche, die leiten können."""
    moeglich = {k["id"] for k in db.leitung_moeglich()}
    gewaehlt = {int(w) for w in daten.getlist("leitung") if str(w).isdigit()}
    return sorted(gewaehlt & moeglich)


def _bereich_seite(request, sitzung, bereich, werte, fehler, status_code=200,
                   hinweis=""):
    if "leitung" not in werte:
        werte = {**werte, "leitung": [k["id"] for k in
                                      db.leitungen([bereich["id"]])[bereich["id"]]]
                 if bereich else []}
    return templates.TemplateResponse(
        "admin_bereich.html",
        _admin(request, sitzung, hinweis=hinweis, bereich=bereich, werte=werte,
               fehler=fehler, leitung_moeglich=db.leitung_moeglich(),
               schichten=db.schichten(bereich["veranstaltung_id"],
                                      bereich_id=bereich["id"]) if bereich else []),
        status_code=status_code)


@app.get("/helfer/bereich/neu")
async def bereich_neu(request: Request,
                      sitzung: auth.Sitzung = Depends(_sitzung),
                      v=Depends(_veranstaltung)):
    leer, _ = planung.bereich_pruefen({})
    return _bereich_seite(request, sitzung, None, leer, {})


@app.post("/helfer/bereich/neu")
async def bereich_anlegen(request: Request,
                          sitzung: auth.Sitzung = Depends(_sitzung),
                          v=Depends(_veranstaltung)):
    daten = await _csrf_pflicht(request, sitzung)
    if daten is None:
        return Response("Ungültiger CSRF-Token", status_code=400)
    werte, fehler = planung.bereich_pruefen(dict(daten))
    werte["leitung"] = _leitung_aus(daten)
    nummer = None if fehler else db.bereich_anlegen(v["id"], werte)
    if nummer is None:
        fehler = fehler or {"name": "Diesen Bereich gibt es in " + v["kurz"] + " schon."}
        return _bereich_seite(request, sitzung, None, werte, fehler, 400)
    db.leitung_setzen(nummer, werte["leitung"])
    return _zurueck("/helfer/bereich/" + str(nummer), "angelegt")


@app.get("/helfer/bereich/{bereich_id}")
async def bereich_formular(request: Request, bereich_id: int, hinweis: str = "",
                           sitzung: auth.Sitzung = Depends(_sitzung)):
    zeile = db.bereich_laden(bereich_id)
    if zeile is None:
        return _fehlt(request)
    _eigen(sitzung, db.leitet_bereich, bereich_id)
    return _bereich_seite(request, sitzung, zeile, _bereich_werte(zeile), {},
                          hinweis=hinweis)


@app.post("/helfer/bereich/{bereich_id}")
async def bereich_sichern(request: Request, bereich_id: int,
                          sitzung: auth.Sitzung = Depends(_sitzung)):
    daten = await _csrf_pflicht(request, sitzung)
    if daten is None:
        return Response("Ungültiger CSRF-Token", status_code=400)
    zeile = db.bereich_laden(bereich_id)
    if zeile is None:
        return _fehlt(request)
    _eigen(sitzung, db.leitet_bereich, bereich_id)
    werte, fehler = planung.bereich_pruefen(dict(daten))
    # Wer leitet, bestimmt die Orga – eine Bereichsleitung ändert es nicht.
    if not sitzung.ist_bereichsleitung:
        werte["leitung"] = _leitung_aus(daten)
    ergebnis = None if fehler else db.bereich_aendern(bereich_id, werte)
    if ergebnis is False:
        return _fehlt(request)
    if ergebnis is None:
        fehler = fehler or {"name": "Einen Bereich mit diesem Namen gibt es schon."}
        return _bereich_seite(request, sitzung, zeile, werte, fehler, 400)
    if "leitung" in werte:
        db.leitung_setzen(bereich_id, werte["leitung"])
    return _zurueck("/helfer/bereich/" + str(bereich_id), "gespeichert")


@app.post("/helfer/bereich/{bereich_id}/loeschen")
async def bereich_weg(request: Request, bereich_id: int,
                      sitzung: auth.Sitzung = Depends(_sitzung)):
    daten = await _csrf_pflicht(request, sitzung)
    if daten is None:
        return Response("Ungültiger CSRF-Token", status_code=400)
    if not db.bereich_loeschen(bereich_id):
        return _zurueck("/helfer/bereich/" + str(bereich_id), "bereich-nicht-leer")
    return _zurueck("/helfer/bereiche", "geloescht")


def _tage_auswahl(veranstaltung_id: int) -> list[dict]:
    """Die Tage der Veranstaltung für die Vorschläge am Datumsfeld."""
    zeile = db.VERANSTALTUNGEN.laden(veranstaltung_id)
    return [{"datum": tag.isoformat(),
             "lang": config.WOCHENTAGE[tag.weekday()] + ", " + tag.strftime("%d.%m.%Y")}
            for tag in (db.tage_der(zeile) if zeile else [])]


def _schicht_werte(zeile) -> dict:
    """Ein gespeicherter Datensatz in der Form, die das Formular erwartet."""
    return {"datum": zeile["datum"], "beginn": eintraege.uhr(zeile["beginn"]),
            "ende": eintraege.uhr(zeile["ende"]),
            **{f: zeile[f] for f in ("minimum", "soll", "reserve", "mindestalter",
                                     "ort", "hinweis", "intern")}}


def _schicht_seite(request, sitzung, bereich, schicht, werte, fehler,
                   status_code=200):
    return templates.TemplateResponse(
        "admin_schicht_form.html",
        _admin(request, sitzung, bereich=bereich, schicht=schicht, werte=werte,
               fehler=fehler, tage=_tage_auswahl(bereich["veranstaltung_id"]),
               bereichsliste=db.bereiche(bereich["veranstaltung_id"],
                                         _leitung(sitzung))),
        status_code=status_code)


def _schicht_eingabe(daten) -> dict:
    """Was im Formular stand, um es nach einem Fehler wieder hinzustellen."""
    return {**{f: str(daten.get(f) or "") for f in
               ("datum", "beginn", "ende", "minimum", "soll", "reserve",
                "mindestalter", "ort", "hinweis")},
            "intern": 1 if daten.get("intern") else 0}


def _alter_gesenkt(werte: dict, bereich) -> bool:
    return (werte["mindestalter"] is not None and bereich["mindestalter"] is not None
            and werte["mindestalter"] < bereich["mindestalter"])


@app.get("/helfer/bereich/{bereich_id}/schicht/neu")
async def schicht_neu(request: Request, bereich_id: int, von: str = "",
                      sitzung: auth.Sitzung = Depends(_sitzung)):
    bereich = db.bereich_laden(bereich_id)
    if bereich is None:
        return _fehlt(request)
    _eigen(sitzung, db.leitet_bereich, bereich_id)
    vorlage = db.schicht_laden(int(von)) if von.isdigit() else None
    if vorlage is not None:
        werte = _schicht_werte(vorlage)
    else:
        tage = _tage_auswahl(bereich["veranstaltung_id"])
        werte = {"datum": tage[0]["datum"] if tage else "", "beginn": "", "ende": "",
                 "minimum": None, "soll": None, "reserve": None,
                 "mindestalter": None, "ort": "", "hinweis": "", "intern": 0}
    return _schicht_seite(request, sitzung, bereich, None, werte, {})


@app.post("/helfer/bereich/{bereich_id}/schicht/neu")
async def schicht_anlegen(request: Request, bereich_id: int,
                          sitzung: auth.Sitzung = Depends(_sitzung)):
    daten = await _csrf_pflicht(request, sitzung)
    if daten is None:
        return Response("Ungültiger CSRF-Token", status_code=400)
    bereich = db.bereich_laden(bereich_id)
    if bereich is None:
        return _fehlt(request)
    _eigen(sitzung, db.leitet_bereich, bereich_id)
    werte, fehler = planung.schicht_pruefen(dict(daten))
    nummer = None if fehler else db.schicht_anlegen(
        bereich["veranstaltung_id"], bereich_id, werte)
    if nummer is None:
        fehler = fehler or {"beginn": "Zu dieser Zeit hat der Bereich schon eine Schicht."}
        return _schicht_seite(request, sitzung, bereich, None,
                              _schicht_eingabe(daten), fehler, 400)
    return _zurueck("/helfer/bereich/" + str(bereich_id),
                    "alter-gesenkt" if _alter_gesenkt(werte, bereich) else "angelegt")


@app.get("/helfer/schicht/{schicht_id}/aendern")
async def schicht_formular(request: Request, schicht_id: int,
                           sitzung: auth.Sitzung = Depends(_sitzung)):
    zeile = db.schicht_laden(schicht_id)
    if zeile is None:
        return _fehlt(request)
    _eigen(sitzung, db.leitet_schicht, schicht_id)
    return _schicht_seite(request, sitzung, db.bereich_laden(zeile["bereich_id"]),
                          zeile, _schicht_werte(zeile), {})


@app.post("/helfer/schicht/{schicht_id}/aendern")
async def schicht_sichern(request: Request, schicht_id: int,
                          sitzung: auth.Sitzung = Depends(_sitzung)):
    daten = await _csrf_pflicht(request, sitzung)
    if daten is None:
        return Response("Ungültiger CSRF-Token", status_code=400)
    zeile = db.schicht_laden(schicht_id)
    if zeile is None:
        return _fehlt(request)
    _eigen(sitzung, db.leitet_schicht, schicht_id)
    # Der Bereich darf wechseln, aber nur innerhalb der Veranstaltung – und
    # für eine Bereichsleitung nur in einen ihrer eigenen.
    roh = str(daten.get("bereich_id") or "")
    bereich = db.bereich_laden(int(roh)) if roh.isdigit() else None
    if (bereich is None or bereich["veranstaltung_id"] != zeile["veranstaltung_id"]
            or (sitzung.ist_bereichsleitung
                and not db.leitet_bereich(sitzung.konto_id, bereich["id"]))):
        bereich = db.bereich_laden(zeile["bereich_id"])
    werte, fehler = planung.schicht_pruefen(dict(daten))
    ergebnis = None if fehler else db.schicht_aendern(schicht_id, bereich["id"], werte)
    if ergebnis is False:
        return _fehlt(request)
    if ergebnis is None:
        fehler = fehler or {"beginn": "Zu dieser Zeit hat der Bereich schon eine Schicht."}
        return _schicht_seite(request, sitzung, bereich, zeile,
                              _schicht_eingabe(daten), fehler, 400)
    return _zurueck("/helfer/bereich/" + str(bereich["id"]),
                    "alter-gesenkt" if _alter_gesenkt(werte, bereich) else "gespeichert")


@app.post("/helfer/schicht/{schicht_id}/loeschen")
async def schicht_weg(request: Request, schicht_id: int,
                      sitzung: auth.Sitzung = Depends(_sitzung)):
    daten = await _csrf_pflicht(request, sitzung)
    if daten is None:
        return Response("Ungültiger CSRF-Token", status_code=400)
    zeile = db.schicht_laden(schicht_id)
    if zeile is None:
        return _zurueck("/helfer/bereiche", "unbekannt")
    _eigen(sitzung, db.leitet_schicht, schicht_id)
    if db.schicht_loeschen(schicht_id):
        return _zurueck("/helfer/schicht/" + str(schicht_id) + "/aendern", "schicht-besetzt")
    return _zurueck("/helfer/bereich/" + str(zeile["bereich_id"]), "geloescht")


# --- Shirt, Verpflegung, Goodies (V-07) ------------------------------------

@app.get("/helfer/goodies")
async def goodies(request: Request, hinweis: str = "",
                  sitzung: auth.Sitzung = Depends(_sitzung),
                  v=Depends(_veranstaltung)):
    return templates.TemplateResponse(
        "admin_goodies.html",
        _admin(request, sitzung, hinweis=hinweis, angebot=db.angebot(v["id"]),
               goodies=db.goodies(v["id"])))


@app.post("/helfer/goodies/angebot")
async def angebot_sichern(request: Request,
                          sitzung: auth.Sitzung = Depends(_sitzung),
                          v=Depends(_veranstaltung)):
    daten = await _csrf_pflicht(request, sitzung)
    if daten is None:
        return Response("Ungültiger CSRF-Token", status_code=400)
    werte = {f: 1 if daten.get(f) else 0 for f in db.ANGEBOT_VORGABE}
    werte["goodies"] = 1 if str(daten.get("goodies") or "") == "1" else 0
    werte["schnitte"] = 1 if str(daten.get("schnitte") or "") == "1" else 0
    if not werte["goodies"]:
        # Ohne Goodies stehen Shirt und Schnitt nicht im Formular; was dort
        # eingestellt war, bleibt für den Fall, dass sie wiederkommen.
        bisher = db.angebot_roh(v["id"])
        werte["shirt"], werte["schnitte"] = bisher["shirt"], bisher["schnitte"]
    db.angebot_setzen(v["id"], werte)
    return _zurueck("/helfer/goodies", "gespeichert")


def _goodie_werte(zeile) -> dict:
    return {"name": zeile["name"],
            "schwelle": zeile["ab_schichten"] or zeile["ab_stunden"],
            "schwelle_art": "schichten" if zeile["ab_schichten"] else "stunden",
            "mindestalter": zeile["mindestalter"], "alternative": zeile["alternative"]}


def _goodie_seite(request, sitzung, goodie, werte, fehler, status_code=200):
    return templates.TemplateResponse(
        "admin_goodie.html",
        _admin(request, sitzung, goodie=goodie, werte=werte, fehler=fehler,
               schwellen=planung.SCHWELLEN),
        status_code=status_code)


def _goodie_eingabe(daten) -> dict:
    """Was im Formular stand, um es nach einem Fehler wieder hinzustellen."""
    return {f: str(daten.get(f) or "") for f in
            ("name", "schwelle", "schwelle_art", "mindestalter", "alternative")}


@app.get("/helfer/goodie/neu")
async def goodie_neu(request: Request,
                     sitzung: auth.Sitzung = Depends(_sitzung),
                     v=Depends(_veranstaltung)):
    return _goodie_seite(request, sitzung, None,
                         {"name": "", "schwelle": "", "schwelle_art": "schichten",
                          "mindestalter": None, "alternative": ""}, {})


@app.post("/helfer/goodie/neu")
async def goodie_anlegen(request: Request,
                         sitzung: auth.Sitzung = Depends(_sitzung),
                         v=Depends(_veranstaltung)):
    daten = await _csrf_pflicht(request, sitzung)
    if daten is None:
        return Response("Ungültiger CSRF-Token", status_code=400)
    werte, fehler = planung.goodie_pruefen(dict(daten))
    if fehler:
        return _goodie_seite(request, sitzung, None, _goodie_eingabe(daten), fehler, 400)
    db.goodie_anlegen(v["id"], werte)
    return _zurueck("/helfer/goodies", "angelegt")


@app.get("/helfer/goodie/{goodie_id}")
async def goodie_formular(request: Request, goodie_id: int,
                          sitzung: auth.Sitzung = Depends(_sitzung)):
    zeile = db.goodie_laden(goodie_id)
    if zeile is None:
        return _fehlt(request)
    return _goodie_seite(request, sitzung, zeile, _goodie_werte(zeile), {})


@app.post("/helfer/goodie/{goodie_id}")
async def goodie_sichern(request: Request, goodie_id: int,
                         sitzung: auth.Sitzung = Depends(_sitzung)):
    daten = await _csrf_pflicht(request, sitzung)
    if daten is None:
        return Response("Ungültiger CSRF-Token", status_code=400)
    zeile = db.goodie_laden(goodie_id)
    if zeile is None:
        return _fehlt(request)
    werte, fehler = planung.goodie_pruefen(dict(daten))
    if fehler:
        return _goodie_seite(request, sitzung, zeile, _goodie_eingabe(daten), fehler, 400)
    db.goodie_aendern(goodie_id, werte)
    return _zurueck("/helfer/goodies", "gespeichert")


@app.post("/helfer/goodie/{goodie_id}/loeschen")
async def goodie_weg(request: Request, goodie_id: int,
                     sitzung: auth.Sitzung = Depends(_sitzung)):
    daten = await _csrf_pflicht(request, sitzung)
    if daten is None:
        return Response("Ungültiger CSRF-Token", status_code=400)
    db.goodie_loeschen(goodie_id)
    return _zurueck("/helfer/goodies", "geloescht")


# --- Helfer ----------------------------------------------------------------

@app.get("/helfer/shirts")
async def shirts(request: Request, hinweis: str = "", suche: str = "",
                 sitzung: auth.Sitzung = Depends(_sitzung),
                 v=Depends(_veranstaltung)):
    """Vor Ort: Shirts ausgeben. Bis Anmeldung und Check-in die Personen
    von der Ausgabe trennen, ist es die Helferliste mit ihrer Shirt-Spalte –
    unter dem Punkt, unter dem man sie am Ausgabetisch sucht."""
    return await helfer_liste(request, hinweis=hinweis, suche=suche,
                              sitzung=sitzung, v=v)


@app.get("/helfer/helfer")
async def helfer_liste(request: Request, hinweis: str = "", suche: str = "",
                       sitzung: auth.Sitzung = Depends(_sitzung),
                       v=Depends(_veranstaltung)):
    return templates.TemplateResponse(
        "admin_helfer.html",
        _admin(request, sitzung, hinweis=hinweis, helfer=db.helfer_liste(v["id"]),
               zaehler=db.zaehler(v["id"]), tshirt=db.tshirt_zaehler(),
               groessen=normalisieren.GROESSEN, suche=suche,
               unterschrieben=unterschriften.je_vorgang("tshirt"),
               tablet=bool(db.tablet_token())))


# --- Ausfuhr ---------------------------------------------------------------

# Die T-Shirt-Ausgabe gehoert hier hinein, Funk und Schluessel nicht - und
# der Unterschied liegt nicht am Geschmack, sondern an der Form der Daten:
# das T-Shirt haengt als EIN Feld an der Person, es gibt hoechstens eine
# Ausgabe je Helfer. Funkgeraete und Schluessel sind eigene Vorgaenge, davon
# beliebig viele je Person; sie hier anzuhaengen hiesse, die Zeile zu
# vervielfachen. Dafuer braeuchte es eigene Ausfuhren.
HELFER_SPALTEN = (
    "Name", "E-Mail", "Telefon", "Verpflegung",
    "Größe angekündigt", "Größe wie eingetippt",
    "T-Shirt ausgegeben", "ausgegeben am", "ausgegeben von",
    "Schichten", "Bemerkung", "angelegt am",
)


def _helfer_zeile(person) -> list:
    """Eine Zeile der Ausfuhr - genau eine je Person.

    Drei Groessenangaben nebeneinander, und jede sagt etwas anderes:
    „Damen L“ ist beim Bestellen eine Information, die „L“ allein nicht mehr
    hergibt - und was am Tisch tatsaechlich herausging, kann von beidem
    abweichen.
    """
    return [
        person["name"],
        person["email"],
        person["telefon"],
        {1: "vegetarisch", 0: "Fleisch"}.get(person["veggie"], ""),
        person["tshirt"] or "",
        person["tshirt_roh"] or "",
        person["tshirt_ausgegeben"] or "",
        (person["tshirt_ausgegeben_am"] or "")[:16],
        person["tshirt_kuerzel"] or "",
        person["schichten"],
        person["bemerkung"],
        (person["angelegt_am"] or "")[:16],
    ]


@app.get("/helfer/helfer/export.csv")
async def helfer_ausfuhr(
        request: Request,
        sitzung: auth.Sitzung = Depends(_sitzung),
        v=Depends(_veranstaltung)):
    """Alle Helfer als Datei - fuer die T-Shirt-Bestellung, eine Kontaktliste
    oder das Archiv nach der Veranstaltung.

    Ohne die Suche der Liste: die sitzt im Browser und filtert nur, was schon
    da ist. Ein Ausschnitt liesse sich in der Tabellenkalkulation ohnehin
    leichter ziehen als hier vorher festlegen.
    """
    puffer = io.StringIO(newline="")
    schreiber = csv.writer(puffer, delimiter=config.CSV_TRENNER,
                           quoting=csv.QUOTE_MINIMAL, lineterminator=chr(13) + chr(10))
    schreiber.writerow(HELFER_SPALTEN)
    for person in db.helfer_liste(v["id"]):
        schreiber.writerow(_helfer_zeile(person))

    # BOM voran, sonst zeigt Excel unter Windows Umlaute als Buchstabensalat.
    inhalt = ("﻿" + puffer.getvalue()).encode("utf-8")
    name = "helfer-" + db.jetzt_lokal().strftime("%Y-%m-%d") + ".csv"
    return Response(
        content=inhalt,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="' + name + '"',
                 # Personendaten gehoeren in keinen Zwischenspeicher.
                 "Cache-Control": "no-store"},
    )


# ACHTUNG, Reihenfolge: /helfer/helfer/neu muss VOR
# /helfer/helfer/{helfer_id} stehen. Starlette nimmt die erste Route, die
# passt – steht die parametrisierte vorn, landet "neu" als Wert in
# helfer_id und die Anfrage scheitert an der Zahlenprüfung.
@app.get("/helfer/helfer/neu")
async def helfer_neu(request: Request,
                     sitzung: auth.Sitzung = Depends(_sitzung)):
    leer = {"name": "", "email": "", "telefon": "", "veggie": "",
            "tshirt": "", "bemerkung": ""}
    return _helferformular(request, sitzung, leer, {})


@app.post("/helfer/helfer/neu")
async def helfer_anlegen_von_hand(
        request: Request,
        sitzung: auth.Sitzung = Depends(_sitzung)):
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
    return _zurueck("/helfer/helfer", "angelegt", sprung="helfer-" + str(nummer))


@app.get("/helfer/helfer/{helfer_id}")
async def helfer_detail(request: Request, helfer_id: int, hinweis: str = "",
                        sitzung: auth.Sitzung = Depends(_sitzung),
                        v=Depends(_veranstaltung)):
    person = db.helfer_laden(helfer_id)
    if person is None:
        return templates.TemplateResponse("admin_fehlt.html",
                                          _kontext(request), status_code=404)
    _eigen(sitzung, db.leitet_helfer, helfer_id)
    schichten = db.helfer_schichten(v["id"], helfer_id)
    if sitzung.ist_bereichsleitung:
        eigene = {b["id"] for b in db.bereiche(v["id"], sitzung.konto_id)}
        schichten = [s for s in schichten if s["bereich_id"] in eigene]
    pflegt = _pflegt_grenzen(sitzung)
    return templates.TemplateResponse(
        "admin_helfer_detail.html",
        _admin(request, sitzung, hinweis=hinweis, person=person,
               schichten=schichten, sieht_grenzen=_sieht_grenzen(sitzung),
               anmelder=db.helfer_laden(person["angemeldet_von"])
               if person["angemeldet_von"] else None,
               mitgebracht=db.mitangemeldete(helfer_id),
               grenzen=db.grenzen(v["id"], helfer_id, _leitung(sitzung))
               if _sieht_grenzen(sitzung) else [],
               grenz_ziele=_grenz_ziele(v["id"]) if pflegt else [],
               grenz_arten=db.GRENZ_ARTEN,
               verlauf=db.protokoll(helfer_id) if pflegt else []))


def _grenz_ziele(vid: int) -> list[dict]:
    """Je Bereich der ganze Bereich und darunter seine Schichten – für die
    Auswahl beim Setzen einer Einsatzgrenze."""
    alle = db.schichten(vid)
    return [{"bereich": b, "schichten": [s for s in alle if s["bereich_id"] == b["id"]]}
            for b in db.bereiche(vid)]


@app.post("/helfer/helfer/{helfer_id}/grenze")
async def grenze_setzen(request: Request, helfer_id: int,
                        sitzung: auth.Sitzung = Depends(_sitzung),
                        v=Depends(_veranstaltung)):
    """Eine Einsatzgrenze setzen (K-05). Nur die Grenze, kein Grund – es
    gibt dafür auch kein Feld (K-08)."""
    daten = await _csrf_pflicht(request, sitzung)
    if daten is None:
        return Response("Ungültiger CSRF-Token", status_code=400)
    if not _pflegt_grenzen(sitzung):
        raise kern_auth.KeinZugang("bereichsleitung")
    if db.helfer_laden(helfer_id) is None:
        return _fehlt(request)
    ziel = "/helfer/helfer/%d" % helfer_id
    roh = str(daten.get("ziel") or "")
    art = str(daten.get("art") or "")
    bereich_id = int(roh[1:]) if roh[:1] == "b" and roh[1:].isdigit() else None
    schicht_id = int(roh[1:]) if roh[:1] == "s" and roh[1:].isdigit() else None
    if art == "nur_zu_zweit" and schicht_id is not None:
        return _zurueck(ziel, "zweit-nur-bereich", sprung="grenzen")
    if not db.grenze_setzen(v["id"], helfer_id, art, bereich_id, schicht_id,
                            sitzung.kuerzel):
        return _zurueck(ziel, "grenze-ziel", sprung="grenzen")
    return _zurueck(ziel, "grenze-gesetzt", sprung="grenzen")


@app.post("/helfer/grenze/{grenze_id}/aufheben")
async def grenze_aufheben(request: Request, grenze_id: int,
                          sitzung: auth.Sitzung = Depends(_sitzung)):
    daten = await _csrf_pflicht(request, sitzung)
    if daten is None:
        return Response("Ungültiger CSRF-Token", status_code=400)
    if not _pflegt_grenzen(sitzung):
        raise kern_auth.KeinZugang("bereichsleitung")
    helfer_id = db.grenze_aufheben(grenze_id, sitzung.kuerzel)
    if helfer_id is None:
        return _zurueck("/helfer/helfer", "unbekannt")
    return _zurueck("/helfer/helfer/%d" % helfer_id, "grenze-aufgehoben", sprung="grenzen")


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
    # Der Monitor kennt keine Wahl: er zeigt die Vorgabe, die nächste
    # Veranstaltung, die noch nicht vorbei ist. Gibt es keine, bleibt er leer.
    aktuell = db.veranstaltung()
    vid = aktuell["id"] if aktuell else None
    stand = db.monitor_stand(vid, jetzt, config.MONITOR_VORSCHAU)
    # strftime('%A') käme im C-Locale als "Saturday" heraus, und ein Locale
    # auf dem Server zu setzen wäre für einen Wochentag zu viel Aufwand.
    stand["tag_lang"] = (config.WOCHENTAGE[jetzt.weekday()] + ", " +
                         jetzt.strftime("%d.%m.%Y"))
    return _kontext(
        request, token=token, stand=stand,
        # Nur der Tagesblick, wenn ein Tag angefragt ist – sonst None.
        tagesblick=db.tagesstand(vid, tag, jetzt) if tag else None,
        band=_band(vid, tag, jetzt) if tag else None,
        tagesleiste=db.monitor_tage(vid),
        heute=jetzt.strftime("%Y-%m-%d"),
        intervall=config.MONITOR_INTERVALL,
        warnschwelle=config.MONITOR_WARNUNG,
        overlay_sekunden=config.MONITOR_OVERLAY_SEKUNDEN,
        tagesblick_sekunden=config.MONITOR_TAGESBLICK_SEKUNDEN,
        tage=db.tage_der(aktuell) if aktuell else [])


def _band(vid, tag: str, jetzt) -> dict | None:
    """Das Programm-Band eines Tages, fertig gerechnet."""
    stand = db.tagesstand(vid, tag, jetzt)
    return band.bauen(
        tag, stand["programm"], stand["schichten"],
        # Die Jetzt-Linie gehoert nur auf den laufenden Tag. An einem anderen
        # stuende sie an einer Stelle, die dort nichts bedeutet.
        jetzt=jetzt if stand["ist_heute"] else None,
        farben={s["schluessel"]: s["farbe"] for s in config.serien()},
        aufgaben=[dict(a) for a in db.aufgaben(vid, tag=tag)])


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


@app.get("/helfer/monitor")
async def monitor_verwalten(
        request: Request, hinweis: str = "",
        sitzung: auth.Sitzung = Depends(_sitzung)):
    token = db.monitor_token()
    basis = config.BASIS_URL or str(request.base_url).rstrip("/")
    return templates.TemplateResponse(
        "admin_monitor.html",
        _admin(request, sitzung, hinweis=hinweis, token=token,
               adresse=(basis + "/monitor/" + token) if token else "",
               intervall=config.MONITOR_INTERVALL,
               vorschau=config.MONITOR_VORSCHAU))


@app.post("/helfer/monitor")
async def monitor_link(
        request: Request,
        sitzung: auth.Sitzung = Depends(_sitzung)):
    daten = await request.form()
    if not auth.csrf_pruefen(sitzung, str(daten.get("csrf") or "")):
        return Response("Ungültiger CSRF-Token", status_code=400)

    if str(daten.get("aktion")) == "widerrufen":
        db.monitor_token_loeschen()
        return _zurueck("/helfer/monitor", "widerrufen")
    db.monitor_token_neu()
    return _zurueck("/helfer/monitor", "neuer-link")


# --- Zeitplan der Rennserien -----------------------------------------------

def _zeitplan_seite(request: Request, sitzung, v, berichte=None, code: int = 200):
    serien = []
    for eintrag in config.serien():
        letzter = db.letzter_erfolg(eintrag["schluessel"])
        serien.append({
            **eintrag,
            "eintraege": db.programm(v["id"], serie=eintrag["schluessel"]),
            "letzter_erfolg": letzter["gelaufen_am"] if letzter else "",
        })
    return templates.TemplateResponse(
        "admin_zeitplan.html",
        _admin(request, sitzung, hinweis="", serien=serien, berichte=berichte,
               abrufe=db.abrufe(8), stunde=config.ZEITPLAN_STUNDE,
               tage=db.tage_der(v)), status_code=code)


@app.get("/helfer/zeitplan")
async def zeitplan_ansicht(
        request: Request,
        sitzung: auth.Sitzung = Depends(_sitzung),
        v=Depends(_veranstaltung)):
    return _zeitplan_seite(request, sitzung, v)


@app.post("/helfer/zeitplan/abrufen")
async def zeitplan_abrufen(
        request: Request,
        sitzung: auth.Sitzung = Depends(_sitzung),
        v=Depends(_veranstaltung)):
    daten = await request.form()
    if not auth.csrf_pruefen(sitzung, str(daten.get("csrf") or "")):
        return Response("Ungültiger CSRF-Token", status_code=400)

    # urllib blockiert; im Thread bleibt die Anwendung derweil ansprechbar.
    berichte = await asyncio.to_thread(
        zeitplan.alle_abrufen, v, sitzung.kuerzel or "von Hand")
    return _zeitplan_seite(request, sitzung, v, berichte=berichte)


# --- Aufgabenplan ----------------------------------------------------------

def _aufgabe_kontext(request: Request, sitzung, aufgabe, werte, fehler,
                     konflikt=None):
    return _admin(
        request, sitzung, hinweis="", aufgabe=aufgabe, werte=werte,
        fehler=fehler, konflikt=konflikt,
        phasen=eintraege.PHASEN, status_texte=eintraege.STATUS,
        tage=db.monitor_tage(_veranstaltung(request)["id"]),
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


@app.get("/helfer/aufgaben")
async def aufgaben(request: Request, phase: str = "", status: str = "",
                   hinweis: str = "",
                   sitzung: auth.Sitzung = Depends(_sitzung),
                   v=Depends(_veranstaltung)):
    liste = db.aufgaben(v["id"], phase=phase if phase in eintraege.PHASEN else "",
                        status=status if status in eintraege.STATUS else "")
    return templates.TemplateResponse(
        "admin_aufgaben.html",
        _admin(request, sitzung, hinweis=hinweis, aufgaben=liste,
               zaehler=db.aufgaben_zaehler(v["id"]), f_phase=phase, f_status=status,
               phasen=eintraege.PHASEN, status_texte=eintraege.STATUS))


@app.get("/helfer/aufgabe/neu")
async def aufgabe_neu(request: Request, tag: str = "",
                      sitzung: auth.Sitzung = Depends(_sitzung)):
    leer = {"titel": "", "phase": "event", "status": "offen",
            "datum": _tag_pruefen(tag), "beginn": "", "ende": "", "ort": "",
            "verantwortlich": "", "kontakt": "", "notiz": "", "version": 0}
    return templates.TemplateResponse(
        "admin_aufgabe.html",
        _aufgabe_kontext(request, sitzung, None, leer, {}))


@app.post("/helfer/aufgabe/neu")
async def aufgabe_anlegen(request: Request,
                          sitzung: auth.Sitzung = Depends(_sitzung),
                          v=Depends(_veranstaltung)):
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

    nummer = db.aufgabe_anlegen(v["id"], werte, sitzung.kuerzel)
    return _zurueck("/helfer/aufgaben", "angelegt",
                    sprung="aufgabe-" + str(nummer))


@app.get("/helfer/aufgabe/{aufgabe_id}")
async def aufgabe_formular(request: Request, aufgabe_id: int,
                           sitzung: auth.Sitzung = Depends(_sitzung)):
    zeile = db.aufgabe_laden(aufgabe_id)
    if zeile is None:
        return templates.TemplateResponse("admin_fehlt.html",
                                          _kontext(request), status_code=404)
    return templates.TemplateResponse(
        "admin_aufgabe.html",
        _aufgabe_kontext(request, sitzung, zeile, _aus_zeile(zeile), {}))


@app.post("/helfer/aufgabe/{aufgabe_id}")
async def aufgabe_sichern(request: Request, aufgabe_id: int,
                          sitzung: auth.Sitzung = Depends(_sitzung)):
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

    return _zurueck("/helfer/aufgaben", "gespeichert",
                    sprung="aufgabe-" + str(aufgabe_id))


@app.post("/helfer/aufgabe/{aufgabe_id}/status")
async def aufgabe_status(request: Request, aufgabe_id: int,
                         sitzung: auth.Sitzung = Depends(_sitzung)):
    daten = await _csrf_pflicht(request, sitzung)
    if daten is None:
        return Response("Ungültiger CSRF-Token", status_code=400)
    neu = str(daten.get("status") or "")
    if neu not in eintraege.STATUS:
        return _zurueck("/helfer/aufgaben", "unbekannt")
    db.aufgabe_status(aufgabe_id, neu, sitzung.kuerzel)
    return _zurueck("/helfer/aufgaben", "status",
                    phase=str(daten.get("f_phase") or ""),
                    status=str(daten.get("f_status") or ""),
                    sprung="aufgabe-" + str(aufgabe_id))


@app.post("/helfer/aufgabe/{aufgabe_id}/loeschen")
async def aufgabe_weg(request: Request, aufgabe_id: int,
                      sitzung: auth.Sitzung = Depends(_sitzung)):
    daten = await _csrf_pflicht(request, sitzung)
    if daten is None:
        return Response("Ungültiger CSRF-Token", status_code=400)
    db.aufgabe_loeschen(aufgabe_id)
    return _zurueck("/helfer/aufgaben", "geloescht")


# --- Programmpunkt von Hand ------------------------------------------------

@app.get("/helfer/programm/{programm_id}")
async def programm_formular(request: Request, programm_id: int,
                            sitzung: auth.Sitzung = Depends(_sitzung)):
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


@app.post("/helfer/programm/{programm_id}")
async def programm_sichern(request: Request, programm_id: int,
                           sitzung: auth.Sitzung = Depends(_sitzung)):
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

    return _zurueck("/helfer/zeitplan", "gespeichert")


@app.post("/helfer/programm/{programm_id}/freigeben")
async def programm_freigeben(request: Request, programm_id: int,
                             sitzung: auth.Sitzung = Depends(_sitzung)):
    daten = await _csrf_pflicht(request, sitzung)
    if daten is None:
        return Response("Ungültiger CSRF-Token", status_code=400)
    db.programm_freigeben(programm_id)
    return _zurueck("/helfer/zeitplan", "freigegeben")


# --- Programm-Band ---------------------------------------------------------

@app.get("/helfer/band")
async def band_ansicht(request: Request, tag: str = "",
                       sitzung: auth.Sitzung = Depends(_sitzung),
                       v=Depends(_veranstaltung)):
    jetzt = db.jetzt_lokal()
    tage = db.monitor_tage(v["id"])
    gewaehlt = _tag_pruefen(tag)
    if not gewaehlt and tage:
        # Ohne Angabe der heutige Tag, sonst der erste, an dem etwas ansteht.
        heute = jetzt.strftime("%Y-%m-%d")
        gewaehlt = heute if any(t["datum"] == heute for t in tage) else tage[0]["datum"]

    stand = db.tagesstand(v["id"], gewaehlt, jetzt) if gewaehlt else None
    return templates.TemplateResponse(
        "admin_band.html",
        _admin(request, sitzung, hinweis="", tage=tage, gewaehlt=gewaehlt,
               stand=stand, band=_band(v["id"], gewaehlt, jetzt) if gewaehlt else None))


# --- T-Shirt-Ausgabe und Helfer von Hand -----------------------------------

def _helfer_zurueck(request: Request, helfer_id: int, hinweis: str):
    """Zurück in die Liste, an dieselbe Zeile und mit demselben Suchbegriff.

    Ohne das landet man nach jedem Haken wieder oben in einer ungefilterten
    Liste von hundert Namen – bei einer Ausgabe, bei der Leute Schlange
    stehen, ist das der Unterschied zwischen benutzbar und nicht.
    """
    return _zurueck("/helfer/helfer", hinweis,
                    suche=str(request.query_params.get("suche") or ""),
                    sprung="helfer-" + str(helfer_id))


@app.post("/helfer/helfer/{helfer_id}/tshirt")
async def tshirt_ausgeben(request: Request, helfer_id: int,
                          sitzung: auth.Sitzung = Depends(_sitzung)):
    daten = await _csrf_pflicht(request, sitzung)
    if daten is None:
        return Response("Ungültiger CSRF-Token", status_code=400)
    if db.helfer_laden(helfer_id) is None:
        return _zurueck("/helfer/helfer", "unbekannt")

    groesse = str(daten.get("groesse") or "").strip()
    if groesse and groesse not in normalisieren.GROESSEN:
        return _zurueck("/helfer/helfer", "groesse",
                        suche=str(daten.get("suche") or ""),
                        sprung="helfer-" + str(helfer_id))

    db.tshirt_ausgeben(helfer_id, groesse, sitzung.kuerzel)
    _unterschrift_dazu("tshirt", helfer_id, "ausgabe", sitzung.kuerzel)
    return _zurueck("/helfer/helfer", "tshirt",
                    suche=str(daten.get("suche") or ""),
                    sprung="helfer-" + str(helfer_id))


@app.post("/helfer/helfer/{helfer_id}/tshirt/zurueck")
async def tshirt_zurueck(request: Request, helfer_id: int,
                         sitzung: auth.Sitzung = Depends(_sitzung)):
    daten = await _csrf_pflicht(request, sitzung)
    if daten is None:
        return Response("Ungültiger CSRF-Token", status_code=400)
    db.tshirt_zuruecknehmen(helfer_id)
    return _zurueck("/helfer/helfer", "tshirt-zurueck",
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


@app.get("/helfer/helfer/{helfer_id}/aendern")
async def helfer_formular(request: Request, helfer_id: int,
                          sitzung: auth.Sitzung = Depends(_sitzung)):
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


@app.post("/helfer/helfer/{helfer_id}/aendern")
async def helfer_sichern(request: Request, helfer_id: int,
                         sitzung: auth.Sitzung = Depends(_sitzung)):
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
    return _zurueck("/helfer/helfer/" + str(helfer_id), "gespeichert")


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


@app.get("/helfer/funk")
async def funk(request: Request, hinweis: str = "", offen: str = "",
               sitzung: auth.Sitzung = Depends(_sitzung),
               v=Depends(_veranstaltung)):
    # Einmal alles holen und in Python trennen: der Umschalter zeigt beide
    # Zahlen, und zwei Abfragen fuer ein paar Dutzend Zeilen waeren Aufwand
    # ohne Gegenwert.
    alle = db.ausleihen_liste(v["id"])
    noch_draussen = [z for z in alle if not z["zurueck_am"]]
    return templates.TemplateResponse(
        "admin_funk.html",
        _admin(request, sitzung, hinweis=hinweis,
               ausleihen=noch_draussen if offen else alle,
               anzahl_alle=len(alle), anzahl_offen=len(noch_draussen),
               nur_offen=bool(offen), zaehler=db.material_zaehler(v["id"]),
               material=db.MATERIAL, material_text=db.MATERIAL_TEXT,
               helfer=db.helfer_liste(v["id"]), tage=db.monitor_tage(v["id"]),
               heute=db.jetzt_lokal().strftime("%Y-%m-%d"),
               vorgaben=db.material_vorgaben(),
               unterschrieben=unterschriften.je_vorgang("material"),
               tablet=bool(db.tablet_token())))


@app.post("/helfer/funk/ausgeben")
async def funk_ausgeben(request: Request,
                        sitzung: auth.Sitzung = Depends(_sitzung),
                        v=Depends(_veranstaltung)):
    daten = await _csrf_pflicht(request, sitzung)
    if daten is None:
        return Response("Ungültiger CSRF-Token", status_code=400)

    helfer_id, woher = _person_aus_formular(daten, sitzung)
    if helfer_id is None:
        return _zurueck("/helfer/funk", "keiner")

    datum = _tag_pruefen(str(daten.get("datum") or ""))

    mengen = {stueck: daten.get(stueck) for stueck in db.MATERIAL}
    nummer = db.ausleihen(v["id"], helfer_id, mengen, datum,
                          str(daten.get("bemerkung") or ""), sitzung.kuerzel)
    if nummer is None:
        return _zurueck("/helfer/funk", "nichts")
    _unterschrift_dazu("material", nummer, "ausgabe", sitzung.kuerzel)
    return _zurueck("/helfer/funk", "neu-angelegt" if woher == "neu" else "ausgegeben")


@app.post("/helfer/ausleihe/{ausleihe_id}/zurueck")
async def ausleihe_zurueck(request: Request, ausleihe_id: int,
                           sitzung: auth.Sitzung = Depends(_sitzung)):
    daten = await _csrf_pflicht(request, sitzung)
    if daten is None:
        return Response("Ungültiger CSRF-Token", status_code=400)
    # Ohne Mengen im Formular kommt alles zurück – der häufige Fall braucht
    # einen Klick, der seltene ein Formular.
    mengen = None
    if str(daten.get("teilweise") or ""):
        mengen = {stueck: daten.get(stueck) for stueck in db.MATERIAL}
    db.ausleihe_zurueck(ausleihe_id, mengen, sitzung.kuerzel)
    # Keine Unterschrift bei der Ruecknahme - in der Praxis war das nicht zu
    # machen: bei der Ausgabe steht die Person ohnehin da und wartet, bei der
    # Rueckgabe legt sie das Geraet hin und ist weg. Wer unterschreibt, geht
    # eine Verpflichtung ein; die entsteht beim Empfangen, nicht beim
    # Zurueckgeben.
    return _zurueck("/helfer/funk", "zurueck",
                    offen=str(daten.get("offen") or ""))


@app.post("/helfer/ausleihe/{ausleihe_id}/loeschen")
async def ausleihe_weg(request: Request, ausleihe_id: int,
                       sitzung: auth.Sitzung = Depends(_sitzung)):
    daten = await _csrf_pflicht(request, sitzung)
    if daten is None:
        return Response("Ungültiger CSRF-Token", status_code=400)
    db.ausleihe_loeschen(ausleihe_id)
    return _zurueck("/helfer/funk", "geloescht")


# --- KFZ-Schlüssel ---------------------------------------------------------

@app.get("/helfer/schluessel")
async def schluessel(request: Request, hinweis: str = "", offen: str = "",
                     sitzung: auth.Sitzung = Depends(_sitzung),
                     v=Depends(_veranstaltung)):
    alle = db.schluessel_liste(v["id"])
    noch_draussen = [z for z in alle if not z["zurueck_am"]]
    return templates.TemplateResponse(
        "admin_schluessel.html",
        _admin(request, sitzung, hinweis=hinweis,
               schluessel=noch_draussen if offen else alle,
               anzahl_alle=len(alle), anzahl_offen=len(noch_draussen),
               nur_offen=bool(offen), fahrzeuge=db.fahrzeuge(),
               namen=db.namen_vorschlaege(v["id"]),
               unterschrieben=unterschriften.je_vorgang("schluessel"),
               tablet=bool(db.tablet_token())))


@app.post("/helfer/schluessel/ausgeben")
async def schluessel_ausgeben(request: Request,
                              sitzung: auth.Sitzung = Depends(_sitzung),
                              v=Depends(_veranstaltung)):
    daten = await _csrf_pflicht(request, sitzung)
    if daten is None:
        return Response("Ungültiger CSRF-Token", status_code=400)

    kennzeichen = str(daten.get("kennzeichen") or "")
    if not normalisieren.kennzeichen(kennzeichen):
        return _zurueck("/helfer/schluessel", "kein-kennzeichen")

    name = str(daten.get("name") or "")
    fahrzeug_id, neu = db.fahrzeug_sichern(kennzeichen, name)
    if fahrzeug_id is None:
        return _zurueck("/helfer/schluessel", "kein-kennzeichen")

    nummer = db.schluessel_ausgeben(v["id"], fahrzeug_id, name,
                                    str(daten.get("bemerkung") or ""),
                                    sitzung.kuerzel)
    _unterschrift_dazu("schluessel", nummer, "ausgabe", sitzung.kuerzel)
    return _zurueck("/helfer/schluessel",
                    "fahrzeug-neu" if neu else "schluessel-raus")


@app.post("/helfer/schluessel/{schluessel_id}/zurueck")
async def schluessel_zurueck(request: Request, schluessel_id: int,
                             sitzung: auth.Sitzung = Depends(_sitzung)):
    daten = await _csrf_pflicht(request, sitzung)
    if daten is None:
        return Response("Ungültiger CSRF-Token", status_code=400)
    # Wie beim Material: keine Unterschrift bei der Ruecknahme.
    db.schluessel_zurueck(schluessel_id, sitzung.kuerzel)
    return _zurueck("/helfer/schluessel", "zurueck",
                    offen=str(daten.get("offen") or ""))


@app.post("/helfer/schluessel/{schluessel_id}/loeschen")
async def schluessel_weg(request: Request, schluessel_id: int,
                         sitzung: auth.Sitzung = Depends(_sitzung)):
    daten = await _csrf_pflicht(request, sitzung)
    if daten is None:
        return Response("Ungültiger CSRF-Token", status_code=400)
    db.schluessel_loeschen(schluessel_id)
    return _zurueck("/helfer/schluessel", "geloescht")


@app.post("/helfer/fahrzeug/{fahrzeug_id}/loeschen")
async def fahrzeug_weg(request: Request, fahrzeug_id: int,
                       sitzung: auth.Sitzung = Depends(_sitzung)):
    daten = await _csrf_pflicht(request, sitzung)
    if daten is None:
        return Response("Ungültiger CSRF-Token", status_code=400)
    ausgang = db.fahrzeug_loeschen(fahrzeug_id)
    return _zurueck("/helfer/schluessel",
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


@app.get("/helfer/einstellungen")
async def einstellungen(request: Request, hinweis: str = "",
                        sitzung: auth.Sitzung = Depends(_sitzung)):
    return _einstellungsseite(request, sitzung, hinweis)


@app.post("/helfer/einstellungen")
async def einstellungen_speichern(
        request: Request,
        sitzung: auth.Sitzung = Depends(_sitzung)):
    daten = await _csrf_pflicht(request, sitzung)
    if daten is None:
        return Response("Ungültiger CSRF-Token", status_code=400)
    db.material_vorgaben_setzen({s: daten.get(s) for s in db.MATERIAL})
    return _zurueck("/helfer/einstellungen", "gespeichert")


# --- Nachfragen aus dem Backoffice -----------------------------------------

@app.get("/helfer/stand")
async def admin_stand(request: Request, seit: int = 0, art: str = "",
                      sitzung: auth.Sitzung = Depends(_sitzung)):
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


@app.get("/helfer/unterschriften")
async def unterschriften_verwalten(
        request: Request, hinweis: str = "",
        sitzung: auth.Sitzung = Depends(_sitzung)):
    token = db.tablet_token()
    basis = config.BASIS_URL or str(request.base_url).rstrip("/")
    return templates.TemplateResponse(
        "admin_unterschriften.html",
        _admin(request, sitzung, hinweis=hinweis, token=token,
               adresse=(basis + "/unterschrift/" + token) if token else "",
               offen=unterschriften.offen(), liste=unterschriften.liste(),
               zaehler=unterschriften.zaehler(),
               minuten=config.UNTERSCHRIFT_MINUTEN))


@app.post("/helfer/unterschriften/link")
async def unterschriften_link(
        request: Request,
        sitzung: auth.Sitzung = Depends(_sitzung)):
    daten = await _csrf_pflicht(request, sitzung)
    if daten is None:
        return Response("Ungültiger CSRF-Token", status_code=400)
    if str(daten.get("aktion")) == "widerrufen":
        db.tablet_token_loeschen()
        return _zurueck("/helfer/unterschriften", "widerrufen")
    db.tablet_token_neu()
    return _zurueck("/helfer/unterschriften", "neuer-link")


@app.post("/helfer/unterschrift/anfordern")
async def unterschrift_anfordern(
        request: Request,
        sitzung: auth.Sitzung = Depends(_sitzung)):
    daten = await _csrf_pflicht(request, sitzung)
    if daten is None:
        return Response("Ungültiger CSRF-Token", status_code=400)

    ziel = _weiter_pfad(str(daten.get("weiter") or "/helfer/unterschriften"))
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


@app.post("/helfer/unterschrift/abbrechen")
async def unterschrift_abbrechen(
        request: Request,
        sitzung: auth.Sitzung = Depends(_sitzung)):
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

@app.get("/helfer/import")
async def import_formular(request: Request, hinweis: str = "",
                          sitzung: auth.Sitzung = Depends(_sitzung)):
    return templates.TemplateResponse(
        "admin_import.html",
        _admin(request, sitzung, hinweis=hinweis, bericht=None, fehler="",
               abruf_moeglich=config.IMPORT_ABRUF_MOEGLICH,
               abruf_takt=_abruf_takt(), uhr_steht=bool(config.JETZT_FEST),
               letzter=db.letzter_import(nur_geglueckt=False),
               laeufe=db.importe()))


@app.post("/helfer/import")
async def import_ausfuehren(request: Request,
                            sitzung: auth.Sitzung = Depends(_sitzung),
                            v=Depends(_veranstaltung)):
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
        bericht = csv_import.importieren(v["id"], offen_roh, vergeben_roh, namen,
                                         sitzung.kuerzel)
    except csv_import.Fehler as fehler:
        return seite(str(fehler), code=400)

    return seite(bericht=bericht)


@app.post("/helfer/import/abrufen")
async def import_abrufen(request: Request,
                         sitzung: auth.Sitzung = Depends(_sitzung),
                         v=Depends(_veranstaltung)):
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
        bericht = await asyncio.to_thread(csv_import.abrufen, v["id"], sitzung.kuerzel)
    except csv_import.Fehler as fehler:
        return seite(str(fehler), code=400)

    return seite(bericht=bericht)


# --- Öffentliche Anmeldung (Lastenheft 2.2) ---------------------------------
#
# Auf dem öffentlichen Hostnamen des Helferbereichs, neben Monitor und
# Tablet. Jede Veranstaltung hat ihren Kurzlink: /aa-2027. Diese Routen
# stehen am Ende, damit /{adresse} nichts überdeckt, was vorher kommt.

# Mehr Leute auf einmal meldet niemand mit an, der nicht ein ganzer Verein
# ist – und der ruft besser an.
MAX_WEITERE = 6


def _tage_text(v) -> str:
    return selbstanmeldung.tage_text(v)


def _zustand(v) -> str:
    """offen, bald oder zu – nach Status und Anmeldezeitraum (V-01, V-02).
    In Planung und archiviert gibt es öffentlich gar nichts."""
    heute = db.jetzt_lokal().date()
    if v["status"] == "angekuendigt":
        return "bald"
    if v["status"] == "offen":
        if v["anmeldung_ab"] and heute < v["anmeldung_ab"]:
            return "bald"
        if v["anmeldung_bis"] and heute > v["anmeldung_bis"]:
            return "zu"
        return "offen"
    if v["status"] == "geschlossen":
        return "zu"
    return ""


class _Adresse(StringConvertor):
    """Der Kurzlink einer Veranstaltung – aber nie einer der festen ersten
    Pfadteile. Sonst passte '/monitor/' ohne Schrägstrich auf '/{adresse}',
    und Starlette leitete dorthin um, statt 404 zu geben."""
    regex = (r"(?!(?:helfer|monitor|unterschrift|static|gemeinsam|platz|bestaetigen"
             r"|kalender|email|eltern|datenschutz)(?![^/]))[^/]+")


register_url_convertor("adresse", _Adresse())


def _oeffentliche():
    return [v for v in db.VERANSTALTUNGEN.liste() if _zustand(v)]


def _nach_adresse(adresse: str):
    for v in _oeffentliche():
        if normalisieren.kurzadresse(v["kurz"]) == adresse:
            return v
    return None


def _oeffentlich(request: Request, v=None, **extra) -> dict:
    adresse = normalisieren.kurzadresse(v["kurz"]) if v else ""
    # Wohin die Formulare der Anmeldung gehen: öffentlich unter dem Kurzlink,
    # aus Mein Helferplatz unter dem persönlichen Link (2.4).
    extra.setdefault("basis", "/" + adresse)
    extra.setdefault("platz", None)
    return _kontext(request, va=v, va_tage=_tage_text(v) if v else "",
                    adresse=adresse, **extra)


def _nicht_da(request: Request):
    return templates.TemplateResponse(
        "anmeldung_uebersicht.html",
        _oeffentlich(request, liste=[]), status_code=404)


@app.get("/")
def oeffentlicher_start(request: Request):
    """Die öffentliche Startseite: welche Veranstaltung Helfer sucht. Ist es
    genau eine, gleich dorthin."""
    liste = [{"va": v, "adresse": normalisieren.kurzadresse(v["kurz"]),
              "tage": _tage_text(v),
              "zustand_text": {"offen": "Anmeldung offen", "bald": "Anmeldung öffnet bald",
                               "zu": "Anmeldung geschlossen"}[_zustand(v)]}
             for v in _oeffentliche()]
    if len(liste) == 1:
        return RedirectResponse("/" + liste[0]["adresse"], status_code=303)
    return templates.TemplateResponse("anmeldung_uebersicht.html",
                                      _oeffentlich(request, liste=liste))


@app.get("/{adresse:adresse}")
def oeffentliche_veranstaltung(request: Request, adresse: str, vorgemerkt: str = ""):
    v = _nach_adresse(adresse)
    if v is None:
        return _nicht_da(request)
    return templates.TemplateResponse(
        "anmeldung_start.html",
        _oeffentlich(request, v, zustand=_zustand(v), vorgemerkt=bool(vorgemerkt),
                     eingabe={}, fehler="",
                     ziele=[{**z, "lang": _tag_lang(z["datum"])} for z in db.tagesziele(v["id"])]
                     if _zustand(v) == "offen" else []))


@app.post("/{adresse:adresse}/interesse")
async def interesse(request: Request, adresse: str):
    """Interesse an einer angekündigten Veranstaltung vormerken (V-02). Die
    Mail bei Anmeldestart kommt mit Schritt 3.3."""
    v = _nach_adresse(adresse)
    if v is None or _zustand(v) != "bald":
        return _nicht_da(request)
    daten = await request.form()
    ziel = RedirectResponse(f"/{adresse}?vorgemerkt=1", status_code=303)
    if normalisieren.text(daten.get("webseite")):
        return ziel
    email = normalisieren.text(daten.get("email")).lower()[:120]
    vorname = normalisieren.text(daten.get("vorname"))[:60]
    fehler = ""
    if not selbstanmeldung._EMAIL.match(email):
        fehler = "Bitte eine vollständige Mailadresse."
    elif not daten.get("einverstanden"):
        fehler = "Bitte das Häkchen setzen – sonst dürfen wir dir nicht schreiben."
    if fehler:
        return templates.TemplateResponse(
            "anmeldung_start.html",
            _oeffentlich(request, v, zustand="bald", vorgemerkt=False, fehler=fehler,
                         eingabe={"email": email, "vorname": vorname}),
            status_code=400)
    db.interesse_vormerken(v["id"], email, vorname)
    return ziel


def _auswahl(v, schicht_roh, fenster_roh, warte_roh=()):
    """Die gewählten Schichten (nur öffentliche, noch nicht begonnene) und
    Springer-Zeiten aus dem Formular. `w` heißt: ist sie voll, dann auf die
    Warteliste (R-04)."""
    alle = {s["id"]: s for s in db.oeffentliche_schichten(v["id"])}
    ids, warte = [], set()
    for roh in schicht_roh:
        if str(roh).isdigit() and int(roh) in alle and int(roh) not in ids:
            ids.append(int(roh))
    for roh in warte_roh:
        if str(roh).isdigit() and int(roh) in alle and int(roh) not in ids:
            ids.append(int(roh))
            warte.add(int(roh))
    gewaehlte = sorted(({**alle[i], "warteliste": i in warte} for i in ids),
                       key=lambda s: s["beginn"])
    namen = {k: n for k, n, *_ in selbstanmeldung.TAGESZEITEN}
    fenster = [{"schluessel": k, "beginn": von, "ende": bis,
                "text": _tag(k.split("|")[0]) + " " + namen[k.split("|")[1]]}
               for k, von, bis in selbstanmeldung.springer_fenster(fenster_roh, db.tage_der(v))]
    return gewaehlte, fenster


def _auswahl_query(gewaehlte, fenster) -> str:
    return urlencode([("w" if s["warteliste"] else "s", s["id"]) for s in gewaehlte] +
                     [("z", f["schluessel"]) for f in fenster])


def _warte(gewaehlte) -> set[int]:
    return {s["id"] for s in gewaehlte if s["warteliste"]}


@app.get("/{adresse:adresse}/schichten")
def oeffentliche_schichten(request: Request, adresse: str, hinweis: str = ""):
    v = _nach_adresse(adresse)
    if v is None or _zustand(v) != "offen":
        return _nicht_da(request) if v is None else RedirectResponse(f"/{adresse}", 303)
    schichten = db.oeffentliche_schichten(v["id"])
    auswahl = {int(x) for x in request.query_params.getlist("s") if x.isdigit()}
    warte_auswahl = {int(x) for x in request.query_params.getlist("w") if x.isdigit()}
    return templates.TemplateResponse(
        "anmeldung_schichten.html",
        _oeffentlich(request, v, schichten=schichten, auswahl=auswahl,
                     warte_auswahl=warte_auswahl,
                     bereichsnamen=sorted({s["bereich"] for s in schichten}, key=str.lower),
                     fenster_gewaehlt=set(request.query_params.getlist("z")),
                     tage=[{"datum": t.isoformat(), "lang": _tag_lang(t.isoformat())}
                           for t in db.tage_der(v)],
                     tageszeiten=selbstanmeldung.TAGESZEITEN,
                     hinweis={"leer": "Wähle mindestens eine Schicht – oder trag dich "
                              "unten als Springer ein."}.get(hinweis, "")))


def _noetig(gewaehlte) -> list[str]:
    """Die Voraussetzungen der gewählten Schichten, jede einmal."""
    voraussetzungen = []
    for s in gewaehlte:
        for zeile in planung.voraussetzungen(s.get("voraussetzungen") or ""):
            if zeile not in voraussetzungen:
                voraussetzungen.append(zeile)
    return voraussetzungen


def _formular(daten):
    """Was im Formular stand – auch um es nach einem Fehler oder nach
    „+ Weitere Person“ wieder hinzustellen. Liefert Aktion, die Eingaben
    (neu nummeriert), die weiteren Personen und die Häkchen."""
    try:
        anzahl = max(0, min(MAX_WEITERE, int(str(daten.get("weitere") or "0"))))
    except ValueError:
        anzahl = 0
    eingabe = {k: str(w) for k, w in daten.items() if not k.startswith("p")}
    personen_roh = [{k[len(f"p{i}-"):]: str(w) for k, w in daten.items()
                     if k.startswith(f"p{i}-")} for i in range(anzahl)]
    liste = {"voraussetzung": daten.getlist("voraussetzung")}
    aktion = str(daten.get("aktion") or "")
    if aktion == "dazu" and anzahl < MAX_WEITERE:
        personen_roh.append({})
    elif aktion.startswith("weg-") and aktion[4:].isdigit():
        weg = int(aktion[4:])
        personen_roh = [p for i, p in enumerate(personen_roh) if i != weg]
    werte = dict(eingabe)
    for i, person in enumerate(personen_roh):
        werte.update({f"p{i}-{k}": w for k, w in person.items()})
    return aktion, werte, personen_roh, liste


def _angaben_seite(request, v, gewaehlte, fenster, eingabe, liste, weitere,
                   fehler=None, gruende=None, status_code=200, rueckfrage=False,
                   platz=None, basis=None):
    voraussetzungen = _noetig(gewaehlte)
    extra = {"basis": basis} if basis else {}
    return templates.TemplateResponse(
        "anmeldung_angaben.html",
        _oeffentlich(request, v, gewaehlte=gewaehlte, fenster=fenster,
                     auswahl_query=_auswahl_query(gewaehlte, fenster),
                     eingabe=eingabe, eingabe_liste=liste, weitere=weitere,
                     max_weitere=MAX_WEITERE, angebot=db.angebot(v["id"]),
                     groessen=normalisieren.GROESSEN, schnitte=selbstanmeldung.SCHNITTE,
                     verpflegung=selbstanmeldung.VERPFLEGUNG, voraussetzungen=voraussetzungen,
                     fehler=fehler or {}, gruende=gruende or [], rueckfrage=rueckfrage,
                     platz=platz, **extra),
        status_code=status_code)


@app.get("/{adresse:adresse}/angaben")
def angaben(request: Request, adresse: str):
    v = _nach_adresse(adresse)
    if v is None or _zustand(v) != "offen":
        return _nicht_da(request) if v is None else RedirectResponse(f"/{adresse}", 303)
    gewaehlte, fenster = _auswahl(v, request.query_params.getlist("s"),
                                  request.query_params.getlist("z"),
                                  request.query_params.getlist("w"))
    if not gewaehlte and not fenster:
        return RedirectResponse(f"/{adresse}/schichten?hinweis=leer", status_code=303)
    return _angaben_seite(request, v, gewaehlte, fenster, {}, {"voraussetzung": []}, [])


@app.post("/{adresse:adresse}/angaben")
async def angaben_absenden(request: Request, adresse: str):
    """Die Anmeldung. Die Arbeit läuft in einem Thread: sie spricht viel mit
    der Datenbank, und im Hauptstrang hielte jede Anmeldung alle anderen auf
    – bei einem Hilferuf kommen viele auf einmal (Lastenheft 2.10). Dass
    niemand doppelt auf einen Platz kommt, regeln die Sperren in
    db.anmelden, nicht die Reihenfolge hier."""
    daten = await request.form()
    return await asyncio.to_thread(_angaben_absenden, request, adresse, daten)


def _angaben_absenden(request: Request, adresse: str, daten):
    v = _nach_adresse(adresse)
    if v is None or _zustand(v) != "offen":
        return _nicht_da(request) if v is None else RedirectResponse(f"/{adresse}", 303)
    if normalisieren.text(daten.get("webseite")):
        return RedirectResponse(f"/{adresse}", status_code=303)
    gewaehlte, fenster = _auswahl(v, daten.getlist("s"), daten.getlist("z"),
                                  daten.getlist("w"))
    if not gewaehlte and not fenster:
        return RedirectResponse(f"/{adresse}/schichten?hinweis=leer", status_code=303)

    # Weitere Person dazu oder weg – das Formular kommt nur neu, gespeichert
    # wird nichts.
    aktion, werte, personen_roh, liste = _formular(daten)
    if aktion not in ("anmelden", "bin-ich", "neu-anlegen"):
        return _angaben_seite(request, v, gewaehlte, fenster, werte, liste, personen_roh)

    stichtag = v["beginn"]
    angebot = db.angebot(v["id"])
    ich, fehler = selbstanmeldung.person_pruefen(daten, "ich-", angebot, stichtag, True)
    personen = [ich]
    for i in range(len(personen_roh)):
        werte, f = selbstanmeldung.person_pruefen(daten, f"p{i}-", angebot, stichtag, False)
        personen.append(werte)
        fehler.update(f)
    if set(_noetig(gewaehlte)) - set(liste["voraussetzung"]):
        fehler["voraussetzungen"] = "Bitte bestätigen – sonst können wir dich dort nicht einsetzen."
    if fehler:
        return _angaben_seite(request, v, gewaehlte, fenster, werte, liste,
                              personen_roh, fehler=fehler, status_code=400)

    # Wer schon da ist, wird nicht ein zweites Mal angelegt (A-11, I-05): er
    # bekommt seinen Link, die Auswahl steht darin schon. Auf der Seite steht
    # nichts über ihn – sonst sähe jeder, der Name und Adresse kennt, wofür
    # jemand eingetragen ist.
    art, treffer = db.erkennen(ich)
    if art == "bekannt" or (art == "vielleicht" and aktion == "bin-ich"):
        for person in treffer:
            _link_mail(request, person, v, _auswahl_query(gewaehlte, fenster))
        return templates.TemplateResponse(
            "anmeldung_post.html", _oeffentlich(request, v, art=art, mitbringen=bool(personen_roh)))
    if art == "vielleicht" and aktion != "neu-anlegen":
        return _angaben_seite(request, v, gewaehlte, fenster, werte, liste, personen_roh,
                              rueckfrage=True)

    try:
        ergebnis = db.anmelden(v["id"], personen, [s["id"] for s in gewaehlte],
                               [(f["schluessel"], f["beginn"], f["ende"]) for f in fenster],
                               bemerkung=str(daten.get("bemerkung") or "").strip()[:1000],
                               warteliste=_warte(gewaehlte))
    except db.AnmeldeFehler as ausnahme:
        return _angaben_seite(request, v, gewaehlte, fenster, werte, liste,
                              personen_roh, gruende=ausnahme.gruende, status_code=409)
    _bestaetigungsmail(request, v, ergebnis["anmelder"])
    if daten.get("stamm"):
        db.stamm_einwilligung(ergebnis["anmelder"], ergebnis["anmelder"], True)
    for helfer_id in ergebnis["personen"]:
        versand.eltern_mail(db.helfer_laden(helfer_id), _basis(request))
    zeichen = selbstanmeldung.zeichen(config.APP_SECRET_KEY, v["id"], ergebnis["anmelder"])
    return RedirectResponse(f"/{adresse}/danke?p={ergebnis['anmelder']}&t={zeichen}",
                            status_code=303)


def _noch_eine(v, personen) -> dict:
    """G-03: Vorschläge für die nächste Schicht – und wofür sie reicht."""
    ids = [e["person"]["id"] for e in personen]
    eigene = len(personen[0]["schichten"]) if personen else 0
    return {"vorschlaege": db.schicht_vorschlaege(v["id"], ids) if _zustand(v) == "offen" else [],
            "goodie": db.naechstes_goodie(v["id"], eigene), "gruppe": len(ids) > 1}


def _danke_seite(request, v, ergebnis, p, t, fehler="", status_code=200, hinweis="",
                 gruende=()):
    return templates.TemplateResponse(
        "anmeldung_danke.html",
        _oeffentlich(request, v, anmeldung=ergebnis, p=p, t=t, fehler=fehler,
                     code_gesperrt=ergebnis["anmelder"]["code_versuche"] >= zugang.CODE_VERSUCHE,
                     noch=_noch_eine(v, ergebnis["personen"]), hinweis=hinweis,
                     gruende=list(gruende)),
        status_code=status_code)


def _danke_laden(adresse: str, p: str, t: str):
    v = _nach_adresse(adresse)
    if v is None or not p.isdigit() or not selbstanmeldung.zeichen_stimmt(
            config.APP_SECRET_KEY, t, v["id"], int(p)):
        return None, None
    return v, db.anmeldung_laden(v["id"], int(p))


@app.get("/{adresse:adresse}/danke")
def danke(request: Request, adresse: str, p: str = "", t: str = "", hinweis: str = ""):
    v, ergebnis = _danke_laden(adresse, p, t)
    if ergebnis is None:
        return _nicht_da(request)
    return _danke_seite(request, v, ergebnis, p, t,
                        hinweis="Eingetragen – danke, das hilft uns sehr!" if hinweis == "noch" else "")


@app.post("/{adresse:adresse}/noch")
async def noch_eine_schicht(request: Request, adresse: str, p: str = "", t: str = ""):
    """G-03: einen Vorschlag von der Dankeseite gleich eintragen – für alle,
    die zusammen angemeldet sind. Nur, was die Seite vorgeschlagen hat; die
    Adresse ist damit noch nicht bestätigt."""
    v, ergebnis = _danke_laden(adresse, p, t)
    if ergebnis is None or _zustand(v) != "offen":
        return _nicht_da(request)
    daten = await request.form()
    gewuenscht = str(daten.get("s") or "")
    angeboten = {s["id"] for s in _noch_eine(v, ergebnis["personen"])["vorschlaege"]}
    if not gewuenscht.isdigit() or int(gewuenscht) not in angeboten:
        return _danke_seite(request, v, ergebnis, p, t, status_code=409, gruende=[
            "Diese Schicht ist gerade nicht frei – in der Liste findest du andere, die Hilfe brauchen."])
    person = ergebnis["anmelder"]
    try:
        db.dazunehmen(v["id"], person["id"], [e["person"]["id"] for e in ergebnis["personen"]],
                      [], [int(gewuenscht)], [], bestaetigt=False)
    except db.AnmeldeFehler as ausnahme:
        return _danke_seite(request, v, ergebnis, p, t, status_code=409, gruende=ausnahme.gruende)
    if person["email_bestaetigt_am"]:
        neu = db.anmeldung_laden(v["id"], person["id"])
        db.mail_einreihen(person["id"], mail.dazu(
            neu["anmelder"], selbstanmeldung.va_text(v), neu["personen"],
            _links(request, person)["platz"]))
    return RedirectResponse(f"/{adresse}/danke?p={p}&t={t}&hinweis=noch", status_code=303)


@app.post("/{adresse:adresse}/danke")
async def danke_code(request: Request, adresse: str, p: str = "", t: str = ""):
    """Der Code aus der Mail, für wen sie auf einem anderen Gerät ankommt
    (7.4). Nach fünf falschen gilt nur noch der Link."""
    v, ergebnis = _danke_laden(adresse, p, t)
    if ergebnis is None:
        return _nicht_da(request)
    person = ergebnis["anmelder"]
    platz = "/platz/" + zugang.token(zugang.PLATZ, person)
    if person["email_bestaetigt_am"]:
        return RedirectResponse(platz, status_code=303)
    if person["code_versuche"] >= zugang.CODE_VERSUCHE:
        return _danke_seite(request, v, ergebnis, p, t, status_code=429)
    daten = await request.form()
    if zugang.code_stimmt(person, str(daten.get("code") or "")):
        _bestaetigt(request, person)
        return RedirectResponse(platz + "?hinweis=bestaetigt", status_code=303)
    db.code_falsch(person["id"])
    v, ergebnis = _danke_laden(adresse, p, t)
    return _danke_seite(request, v, ergebnis, p, t, status_code=400,
                        fehler="Der Code stimmt nicht – schau noch einmal in die Mail.")


# --- Mein Helferplatz, Bestätigen, Kalender (Lastenheft 2.4) ----------------
#
# Ohne Konto und ohne Passwort: jeder Weg hängt an einem persönlichen Link
# (zugang.py). Formulare auf diesen Seiten brauchen deshalb kein CSRF-Token –
# wer den Link nicht hat, kann auch nichts abschicken.

def _basis(request: Request) -> str:
    """Für Links in Mails: die öffentliche Adresse, sonst aus der Anfrage."""
    return config.BASIS_URL or str(request.base_url).rstrip("/")


def _person_mit(zweck: str, roh: str):
    """Die Person zu einem persönlichen Link – None, wenn er nicht stimmt."""
    nummer = zugang.nummer(roh)
    person = db.helfer_laden(nummer) if nummer is not None else None
    if person is None or not zugang.stimmt(zweck, roh, person):
        return None
    return person


def _links(request: Request, person) -> dict:
    basis = _basis(request)
    kalender = basis + "/kalender/" + zugang.token(zugang.KALENDER, person) + ".ics"
    return {"platz": basis + "/platz/" + zugang.token(zugang.PLATZ, person),
            "bestaetigen": basis + "/bestaetigen/" + zugang.token(zugang.BESTAETIGEN, person),
            "kalender": kalender, "webcal": "webcal://" + kalender.split("://", 1)[-1]}


def _bestaetigungsmail(request: Request, v, anmelder_id: int) -> None:
    """Gleich nach der Anmeldung: Link und Code (I-03)."""
    ergebnis = db.anmeldung_laden(v["id"], anmelder_id)
    person = ergebnis["anmelder"]
    db.mail_einreihen(anmelder_id, mail.bestaetigen(
        person, selbstanmeldung.va_text(v), ergebnis["personen"],
        _links(request, person)["bestaetigen"], zugang.code(person)))


def _bestaetigt(request: Request, person) -> None:
    """Die Adresse ist bestätigt – dann kommt die Mail mit dem persönlichen
    Link und dem Kalender-Abo (A-10), je Veranstaltung, die noch kommt."""
    if not db.bestaetigen(person["id"]):
        return
    person = db.helfer_laden(person["id"])
    links = _links(request, person)
    for v in _kommende(db.teilnahmen([person["id"]])):
        ergebnis = db.anmeldung_laden(v["id"], person["id"])
        db.mail_einreihen(person["id"], mail.bestaetigt(
            person, selbstanmeldung.va_text(v), ergebnis["personen"],
            links["platz"], links["kalender"]))


def _link_mail(request: Request, person, v=None, auswahl: str = "") -> None:
    """Der Link zu Mein Helferplatz (A-11) – mit der eben getroffenen Auswahl,
    wenn es eine gibt."""
    links = _links(request, person)
    dazu = ""
    if v is not None and auswahl:
        dazu = (links["platz"] + "/" + normalisieren.kurzadresse(v["kurz"])
                + "/angaben?" + auswahl)
    db.mail_einreihen(person["id"], mail.link(person, links["platz"], dazu))


def _kommende(vids) -> list:
    """Die Veranstaltungen, die noch nicht vorbei sind, nach Beginn."""
    heute = db.jetzt_lokal().date()
    liste = [db.VERANSTALTUNGEN.laden(vid) for vid in vids]
    return sorted((v for v in liste if v is not None and v["status"] != "archiviert"
                   and v["ende"] >= heute), key=lambda v: v["beginn"])


_PLATZ_HINWEISE = {
    "bestaetigt": "Danke – deine Adresse ist bestätigt. Du bist dabei!",
    "dazu": "Eingetragen. Eine Mail mit allem ist unterwegs.",
    "abgesagt": "Abgesagt – danke, dass du Bescheid sagst! Das hilft uns sehr.",
    "getauscht": "Getauscht. Eine Mail mit allem ist unterwegs.",
    "abgemeldet": "Abgemeldet – danke, dass du Bescheid sagst. Vielleicht beim nächsten Mal!",
    "angenommen": "Prima – der Platz gehört dir.",
    "abgelehnt": "Danke für die Antwort – wir geben den Platz weiter.",
    "vorbei": "Dieses Angebot gilt leider nicht mehr.",
    "warteliste-weg": "Du stehst nicht mehr auf der Warteliste.",
    "springer-weg": "Die Springer-Zeit ist abgesagt – danke für Bescheid.",
    "angaben": "Gespeichert.",
    "adresse": "Wir haben eine Mail an die neue Adresse geschickt – bitte bestätige sie dort.",
    "adresse-bestaetigt": "Die neue Adresse ist bestätigt.",
    "geloescht": "Gelöscht.",
    "wartet": "Gelöscht wird, sobald alles Ausgeliehene zurück ist.",
    "eltern": "Die Mail an die Eltern ist noch einmal unterwegs.",
}


@app.get("/platz/{tok}")
def platz(request: Request, tok: str, hinweis: str = ""):
    """Mein Helferplatz (A-09): alle Schichten, Treffpunkt, Ansprechpartner;
    weitere Schichten dazunehmen."""
    person = _person_mit(zugang.PLATZ, tok)
    if person is None:
        return _nicht_da(request)
    ids = [person["id"]] + [m["id"] for m in db.mitangemeldete(person["id"])]
    veranstaltungen = []
    for v in _kommende(db.teilnahmen(ids)):
        ergebnis = db.anmeldung_laden(v["id"], person["id"])
        bereiche = {s["bereich_id"] for e in ergebnis["personen"] for s in e["schichten"]}
        veranstaltungen.append({
            "va": v, "tage": _tage_text(v), "adresse": normalisieren.kurzadresse(v["kurz"]),
            "zustand": _zustand(v), "personen": ergebnis["personen"],
            "leitungen": db.leitungen(sorted(bereiche)),
            # G-03: direkt nach dem Eintragen, nicht bei jedem Besuch.
            "noch": _noch_eine(v, ergebnis["personen"][:1])
            if hinweis in ("dazu", "bestaetigt") else None})
    dabei = {x["va"]["id"] for x in veranstaltungen}
    weitere = [{"va": v, "tage": _tage_text(v), "adresse": normalisieren.kurzadresse(v["kurz"])}
               for v in _oeffentliche() if _zustand(v) == "offen" and v["id"] not in dabei]
    return templates.TemplateResponse(
        "platz.html",
        _oeffentlich(request, None, person=person, token=tok, veranstaltungen=veranstaltungen,
                     weitere=weitere, links=_links(request, person),
                     mit=db.mitangemeldete(person["id"]),
                     hinweis=_PLATZ_HINWEISE.get(hinweis, "")))


@app.post("/platz/{tok}/bestaetigen")
async def platz_bestaetigen(request: Request, tok: str):
    person = _person_mit(zugang.PLATZ, tok)
    if person is None:
        return _nicht_da(request)
    _bestaetigt(request, person)
    return RedirectResponse(f"/platz/{tok}?hinweis=bestaetigt", status_code=303)


@app.get("/bestaetigen/{tok}")
def bestaetigen_seite(request: Request, tok: str):
    """Der Link aus der Mail öffnet nur eine Seite mit einem Knopf – Mailscanner
    rufen Links vorab auf, eingelöst wird erst beim Klick (7.4)."""
    person = _person_mit(zugang.BESTAETIGEN, tok)
    if person is None:
        return _nicht_da(request)
    if person["email_bestaetigt_am"]:
        return RedirectResponse("/platz/" + zugang.token(zugang.PLATZ, person), status_code=303)
    return templates.TemplateResponse("anmeldung_bestaetigen.html",
                                      _oeffentlich(request, None, person=person, token=tok))


@app.post("/bestaetigen/{tok}")
async def bestaetigen(request: Request, tok: str):
    person = _person_mit(zugang.BESTAETIGEN, tok)
    if person is None:
        return _nicht_da(request)
    _bestaetigt(request, person)
    return RedirectResponse("/platz/" + zugang.token(zugang.PLATZ, person) + "?hinweis=bestaetigt",
                            status_code=303)


def _platz_va(tok: str, adresse: str):
    person = _person_mit(zugang.PLATZ, tok)
    v = _nach_adresse(adresse)
    if person is None or v is None:
        return None, None
    return person, v


@app.get("/platz/{tok}/{adresse:adresse}/schichten")
def platz_schichten(request: Request, tok: str, adresse: str, hinweis: str = ""):
    """Die Schichtliste aus Mein Helferplatz: ohne das, was hinter einer
    Einsatzgrenze liegt (K-06), mit dem, wofür man schon eingetragen ist."""
    person, v = _platz_va(tok, adresse)
    if person is None:
        return _nicht_da(request)
    if _zustand(v) != "offen":
        return RedirectResponse(f"/platz/{tok}", status_code=303)
    gesperrt = db.gesperrt(v["id"], person["id"])
    schichten = [s for s in db.oeffentliche_schichten(v["id"]) if s["id"] not in gesperrt]
    ergebnis = db.anmeldung_laden(v["id"], person["id"])
    eigene: dict[int, list[str]] = {}
    meine = []
    for e in ergebnis["personen"]:
        wer = "du" if e["person"]["id"] == person["id"] else (e["person"]["vorname"]
                                                             or e["person"]["name"])
        for s in e["schichten"]:
            eigene.setdefault(s["id"], []).append(wer)
            if e["person"]["id"] == person["id"]:
                meine.append(s)
    konflikte = {}
    for s in schichten:
        for m in meine:
            if m["id"] != s["id"] and selbstanmeldung.ueberschneiden(
                    m["beginn"], m["ende"], s["beginn"], s["ende"]):
                konflikte[s["id"]] = m["bereich"]
    auswahl = {int(x) for x in request.query_params.getlist("s") if x.isdigit()}
    warte_auswahl = {int(x) for x in request.query_params.getlist("w") if x.isdigit()}
    return templates.TemplateResponse(
        "anmeldung_schichten.html",
        _oeffentlich(request, v, schichten=schichten, auswahl=auswahl,
                     warte_auswahl=warte_auswahl,
                     bereichsnamen=sorted({s["bereich"] for s in schichten}, key=str.lower),
                     fenster_gewaehlt=set(request.query_params.getlist("z")),
                     tage=[{"datum": t.isoformat(), "lang": _tag_lang(t.isoformat())}
                           for t in db.tage_der(v)],
                     tageszeiten=selbstanmeldung.TAGESZEITEN,
                     basis=f"/platz/{tok}/{adresse}", platz={"token": tok, "person": person},
                     eigene={k: ", ".join(w) for k, w in eigene.items()}, konflikte=konflikte,
                     hinweis={"leer": "Wähle mindestens eine Schicht – oder trag dich "
                              "unten als Springer ein."}.get(hinweis, "")))


def _dazu_seite(request, v, tok, person, gewaehlte, fenster, werte, liste, weitere, wer,
                **extra):
    return _angaben_seite(
        request, v, gewaehlte, fenster, werte, liste, weitere,
        platz={"token": tok, "person": person, "mit": db.mitangemeldete(person["id"]),
               "wer": wer},
        basis=f"/platz/{tok}/{normalisieren.kurzadresse(v['kurz'])}", **extra)


@app.get("/platz/{tok}/{adresse:adresse}/angaben")
def platz_angaben(request: Request, tok: str, adresse: str):
    person, v = _platz_va(tok, adresse)
    if person is None:
        return _nicht_da(request)
    if _zustand(v) != "offen":
        return RedirectResponse(f"/platz/{tok}", status_code=303)
    gewaehlte, fenster = _auswahl(v, request.query_params.getlist("s"),
                                  request.query_params.getlist("z"),
                                  request.query_params.getlist("w"))
    if not gewaehlte and not fenster:
        return RedirectResponse(f"/platz/{tok}/{adresse}/schichten?hinweis=leer",
                                status_code=303)
    return _dazu_seite(request, v, tok, person, gewaehlte, fenster, {},
                       {"voraussetzung": []}, [], [person["id"]])


@app.post("/platz/{tok}/{adresse:adresse}/angaben")
async def platz_angaben_absenden(request: Request, tok: str, adresse: str):
    """Schichten dazunehmen (A-09): für sich, für Mitangemeldete, für neue,
    die mitkommen."""
    person, v = _platz_va(tok, adresse)
    if person is None:
        return _nicht_da(request)
    if _zustand(v) != "offen":
        return RedirectResponse(f"/platz/{tok}", status_code=303)
    daten = await request.form()
    gewaehlte, fenster = _auswahl(v, daten.getlist("s"), daten.getlist("z"),
                                  daten.getlist("w"))
    if not gewaehlte and not fenster:
        return RedirectResponse(f"/platz/{tok}/{adresse}/schichten?hinweis=leer",
                                status_code=303)
    aktion, werte, personen_roh, liste = _formular(daten)
    wer = [int(x) for x in daten.getlist("wer") if str(x).isdigit()]
    if aktion != "eintragen":
        return _dazu_seite(request, v, tok, person, gewaehlte, fenster, werte, liste,
                           personen_roh, wer)

    angebot = db.angebot(v["id"])
    neue, fehler = [], {}
    for i in range(len(personen_roh)):
        werte_i, f = selbstanmeldung.person_pruefen(daten, f"p{i}-", angebot, v["beginn"], False)
        neue.append(werte_i)
        fehler.update(f)
    if not wer and not neue:
        fehler["wer"] = "Wähle aus, wer kommt."
    if set(_noetig(gewaehlte)) - set(liste["voraussetzung"]):
        fehler["voraussetzungen"] = "Bitte bestätigen – sonst können wir dich dort nicht einsetzen."
    if fehler:
        return _dazu_seite(request, v, tok, person, gewaehlte, fenster, werte, liste,
                           personen_roh, wer, fehler=fehler, status_code=400)
    try:
        dazu = db.dazunehmen(v["id"], person["id"], wer, neue, [s["id"] for s in gewaehlte],
                             [(f["schluessel"], f["beginn"], f["ende"]) for f in fenster],
                             bemerkung=str(daten.get("bemerkung") or "").strip()[:1000],
                             warteliste=_warte(gewaehlte))
        for helfer_id in dazu["personen"]:
            versand.eltern_mail(db.helfer_laden(helfer_id), _basis(request))
    except db.AnmeldeFehler as ausnahme:
        return _dazu_seite(request, v, tok, person, gewaehlte, fenster, werte, liste,
                           personen_roh, wer, gruende=ausnahme.gruende, status_code=409)
    ergebnis = db.anmeldung_laden(v["id"], person["id"])
    db.mail_einreihen(person["id"], mail.dazu(
        ergebnis["anmelder"], selbstanmeldung.va_text(v), ergebnis["personen"],
        _links(request, person)["platz"]))
    return RedirectResponse(f"/platz/{tok}?hinweis=dazu", status_code=303)


@app.post("/{adresse:adresse}/link")
async def link_anfordern(request: Request, adresse: str):
    """„Schon angemeldet?“ – den Link zu Mein Helferplatz noch einmal
    schicken (7.4). Die Seite sagt immer dasselbe: ob eine Adresse bekannt
    ist, verrät sie nicht."""
    v = _nach_adresse(adresse)
    if v is None:
        return _nicht_da(request)
    daten = await request.form()
    antwort = templates.TemplateResponse("anmeldung_post.html",
                                         _oeffentlich(request, v, art="angefordert"))
    if normalisieren.text(daten.get("webseite")):
        return antwort
    email = normalisieren.text(daten.get("email")).lower()[:120]
    if not selbstanmeldung._EMAIL.match(email):
        return templates.TemplateResponse(
            "anmeldung_start.html",
            _oeffentlich(request, v, zustand=_zustand(v), vorgemerkt=False, eingabe={},
                         fehler="", link_fehler="Bitte eine vollständige Mailadresse.",
                         link_eingabe=email), status_code=400)
    for person in db.nach_email(email):
        if person["angemeldet_von"] is None:
            _link_mail(request, person)
    return antwort


@app.get("/kalender/{datei}")
def kalender(request: Request, datei: str):
    """Das Kalender-Abo (A-10). Das Programm fragt es regelmäßig ab."""
    person = _person_mit(zugang.KALENDER, datei.removesuffix(".ics"))
    if person is None:
        return Response("", status_code=404)
    return Response(ical.kalender(db.kalender(person["id"]), person),
                    media_type="text/calendar; charset=utf-8",
                    headers={"Cache-Control": "no-store"})


# --- Selbstbedienung (Lastenheft 2.5) -----------------------------------------
#
# Alles in Mein Helferplatz, ohne Frist (S-01 bis S-06): absagen, tauschen,
# abmelden, Angaben ändern, löschen – für sich und für die, die man
# mitangemeldet hat. Jede Absage geht sofort an die Bereichsleitung, wenn sie
# kurzfristig ist oder die Schicht unter ihr Minimum fällt (S-07); ein frei
# gewordener Platz geht an die Warteliste (R-04).

def _nach_abgabe(request: Request, abgaben) -> None:
    """Was jeder Absage folgt: Bescheid an die Bereichsleitung, Angebote an
    die Warteliste."""
    versand.absage_mails(abgaben)
    versand.angebot_mails([a for abgabe in abgaben for a in abgabe["angebote"]],
                          _basis(request))


def _frage(request: Request, tok: str, titel: str, text: str, ziel: str, knopf: str,
           grund: bool = False, liste=(), personen=(), status_code: int = 200):
    """Die Rückfrage vor allem, was sich nicht zurücknehmen lässt."""
    return templates.TemplateResponse(
        "platz_frage.html",
        _oeffentlich(request, None, token=tok, titel=titel, text=text, ziel=ziel,
                     knopf=knopf, mit_grund=grund, liste=list(liste), personen=list(personen)),
        status_code=status_code)


@app.get("/platz/{tok}/absagen/{einteilung_id}")
def platz_absagen_frage(request: Request, tok: str, einteilung_id: int):
    person = _person_mit(zugang.PLATZ, tok)
    e = db.einteilung_fuer(person["id"], einteilung_id) if person else None
    if e is None:
        return _nicht_da(request)
    wer = db.helfer_laden(e["helfer_id"])
    return _frage(request, tok, "Schicht absagen?",
                  ("Du sagst ab" if wer["id"] == person["id"] else f"{wer['vorname'] or wer['name']} sagt ab")
                  + f": {e['text']}. Danke, dass du Bescheid sagst – auch kurzfristig ist "
                  "das besser, als nicht zu kommen.",
                  f"/platz/{tok}/absagen/{einteilung_id}", "Ja, absagen", grund=True)


@app.post("/platz/{tok}/absagen/{einteilung_id}")
async def platz_absagen(request: Request, tok: str, einteilung_id: int):
    """S-01: jederzeit, auch kurz vorher und während der Veranstaltung."""
    person = _person_mit(zugang.PLATZ, tok)
    if person is None:
        return _nicht_da(request)
    daten = await request.form()
    grund = normalisieren.text(daten.get("grund"))[:300]
    ergebnis = db.stornieren(person["id"], einteilung_id, grund)
    if ergebnis is None:
        return _nicht_da(request)
    _nach_abgabe(request, [ergebnis])
    v = db.VERANSTALTUNGEN.laden(ergebnis["schicht"]["veranstaltung_id"])
    wer = ergebnis["person"]
    zeile = ergebnis["schicht"]["text"] + ("" if wer["id"] == person["id"]
                                           else f" ({wer['vorname'] or wer['name']})")
    db.mail_einreihen(person["id"], mail.abgesagt(
        person, selbstanmeldung.va_text(v), [zeile], _links(request, person)["platz"]))
    return RedirectResponse(f"/platz/{tok}?hinweis=abgesagt", status_code=303)


@app.post("/platz/{tok}/angebot/{einteilung_id}")
async def platz_angebot(request: Request, tok: str, einteilung_id: int):
    """R-04: Ja oder Nein zum Platz von der Warteliste."""
    person = _person_mit(zugang.PLATZ, tok)
    if person is None:
        return _nicht_da(request)
    daten = await request.form()
    if daten.get("antwort") == "ja":
        hinweis = "angenommen" if db.angebot_annehmen(person["id"], einteilung_id) else "vorbei"
    else:
        e = db.einteilung_fuer(person["id"], einteilung_id)
        if e is None or e["bestaetigen_bis"] is None:
            hinweis = "vorbei"
        else:
            _nach_abgabe(request, [db.stornieren(person["id"], einteilung_id)])
            hinweis = "abgelehnt"
    return RedirectResponse(f"/platz/{tok}?hinweis={hinweis}", status_code=303)


@app.post("/platz/{tok}/warteliste/{warteliste_id}/weg")
async def platz_warteliste_weg(request: Request, tok: str, warteliste_id: int):
    person = _person_mit(zugang.PLATZ, tok)
    if person is None or not db.warteliste_verlassen(person["id"], warteliste_id):
        return _nicht_da(request)
    return RedirectResponse(f"/platz/{tok}?hinweis=warteliste-weg", status_code=303)


@app.post("/platz/{tok}/springer/{fenster_id}/weg")
async def platz_springer_weg(request: Request, tok: str, fenster_id: int):
    person = _person_mit(zugang.PLATZ, tok)
    if person is None or not db.springer_absagen(person["id"], fenster_id):
        return _nicht_da(request)
    return RedirectResponse(f"/platz/{tok}?hinweis=springer-weg", status_code=303)


def _alternativen(e, person_id: int) -> list[dict]:
    """Wogegen sich eine Schicht tauschen lässt (S-02): zuerst am selben Tag
    im selben Bereich, dann am selben Tag, dann alles Weitere. Ohne volle
    und ohne das, was hinter einer Einsatzgrenze liegt."""
    gesperrt = db.gesperrt(e["veranstaltung_id"], person_id)
    liste = [s for s in db.oeffentliche_schichten(e["veranstaltung_id"])
             if s["id"] != e["schicht_id"] and s["id"] not in gesperrt and s["lage"] != "voll"]
    for s in liste:
        s["naehe"] = (0 if s["datum"] == e["datum"] and s["bereich_id"] == e["bereich_id"]
                      else 1 if s["datum"] == e["datum"] else 2)
    return sorted(liste, key=lambda s: (s["naehe"], s["beginn"]))


def _tauschen_seite(request, tok, e, gruende=(), status_code=200, gewaehlt=None, noetig=()):
    return templates.TemplateResponse(
        "platz_tauschen.html",
        _oeffentlich(request, None, token=tok, einteilung=e,
                     alternativen=_alternativen(e, e["helfer_id"]), gruende=list(gruende),
                     gewaehlt=gewaehlt, noetig=list(noetig)),
        status_code=status_code)


@app.get("/platz/{tok}/tauschen/{einteilung_id}")
def platz_tauschen_seite(request: Request, tok: str, einteilung_id: int):
    person = _person_mit(zugang.PLATZ, tok)
    e = db.einteilung_fuer(person["id"], einteilung_id) if person else None
    if e is None:
        return _nicht_da(request)
    return _tauschen_seite(request, tok, e)


@app.post("/platz/{tok}/tauschen/{einteilung_id}")
async def platz_tauschen(request: Request, tok: str, einteilung_id: int):
    """S-02: die neue zuerst, dann die alte frei – geht die neue nicht,
    bleibt die alte."""
    person = _person_mit(zugang.PLATZ, tok)
    e = db.einteilung_fuer(person["id"], einteilung_id) if person else None
    if e is None:
        return _nicht_da(request)
    daten = await request.form()
    neu = str(daten.get("s") or "")
    if not neu.isdigit():
        return _tauschen_seite(request, tok, e, ["Bitte eine Schicht wählen."], 400)
    # Was die neue Schicht verlangt, wird bestätigt – wie beim Anmelden.
    ziel = next((s for s in _alternativen(e, e["helfer_id"]) if s["id"] == int(neu)), None)
    noetig = planung.voraussetzungen(ziel["voraussetzungen"] or "") if ziel else []
    if noetig and not daten.get("voraussetzung_ok"):
        return _tauschen_seite(
            request, tok, e, [f"Für {ziel['bereich']} brauchst du: {', '.join(noetig)} – "
                              "bitte bestätige das unten."], 400, gewaehlt=ziel["id"], noetig=noetig)
    try:
        ergebnis = db.umbuchen(e["veranstaltung_id"], person["id"], einteilung_id, int(neu))
    except db.AnmeldeFehler as ausnahme:
        return _tauschen_seite(request, tok, e, ausnahme.gruende, 409)
    _nach_abgabe(request, [ergebnis])
    v = db.VERANSTALTUNGEN.laden(e["veranstaltung_id"])
    db.mail_einreihen(person["id"], mail.getauscht(
        person, selbstanmeldung.va_text(v), e["text"], ergebnis["neu"]["text"],
        _links(request, person)["platz"]))
    return RedirectResponse(f"/platz/{tok}?hinweis=getauscht", status_code=303)


@app.get("/platz/{tok}/{adresse:adresse}/abmelden")
def platz_abmelden_frage(request: Request, tok: str, adresse: str):
    person, v = _platz_va(tok, adresse)
    if person is None:
        return _nicht_da(request)
    personen = [person] + list(db.mitangemeldete(person["id"]))
    return _frage(request, tok, "Ganz abmelden?",
                  f"Alle Schichten, Wartelisten und Springer-Zeiten bei {v['name']} werden "
                  "abgesagt. Ein Grund ist freiwillig – er hilft uns beim Planen.",
                  f"/platz/{tok}/{adresse}/abmelden", "Ja, abmelden", grund=True,
                  personen=personen)


@app.post("/platz/{tok}/{adresse:adresse}/abmelden")
async def platz_abmelden(request: Request, tok: str, adresse: str):
    """S-03: alle Schichten auf einmal."""
    person, v = _platz_va(tok, adresse)
    if person is None:
        return _nicht_da(request)
    daten = await request.form()
    wer = [int(x) for x in daten.getlist("wer") if str(x).isdigit()] or [person["id"]]
    namen = {p["id"]: p["vorname"] or p["name"] for p in [person, *db.mitangemeldete(person["id"])]}
    abgaben = db.abmelden(v["id"], person["id"], wer,
                          normalisieren.text(daten.get("grund"))[:300])
    _nach_abgabe(request, abgaben)
    db.mail_einreihen(person["id"], mail.abgemeldet(
        person, selbstanmeldung.va_text(v), [namen[w] for w in wer if w in namen]))
    return RedirectResponse(f"/platz/{tok}?hinweis=abgemeldet", status_code=303)


def _angebot_fuer(person_ids) -> dict:
    """Shirt und Essen fragen, wenn eine der kommenden Veranstaltungen sie
    anbietet."""
    angebot = {"shirt": 0, "schnitte": 0, "verpflegung": 0}
    for v in _kommende(db.teilnahmen(person_ids)):
        for k, w in db.angebot(v["id"]).items():
            if k in angebot and w:
                angebot[k] = 1
    return angebot


def _angaben_aendern_seite(request, tok, person, eingabe, fehler=None, status_code=200):
    mit = db.mitangemeldete(person["id"])
    ids = [person["id"]] + [m["id"] for m in mit]
    bemerkungen = []
    for v in _kommende(db.teilnahmen([person["id"]])):
        bemerkungen.append({"va": v, "feld": f"bemerkung-{v['id']}"})
    return templates.TemplateResponse(
        "platz_angaben.html",
        _oeffentlich(request, None, token=tok, person=person, mit=mit, eingabe=eingabe,
                     fehler=fehler or {}, angebot=_angebot_fuer(ids),
                     groessen=normalisieren.GROESSEN, schnitte=selbstanmeldung.SCHNITTE,
                     verpflegung=selbstanmeldung.VERPFLEGUNG, bemerkungen=bemerkungen),
        status_code=status_code)


@app.get("/platz/{tok}/angaben")
def platz_angaben_aendern_seite(request: Request, tok: str):
    person = _person_mit(zugang.PLATZ, tok)
    if person is None:
        return _nicht_da(request)
    eingabe = selbstanmeldung.vorbelegen(person, "ich-")
    for m in db.mitangemeldete(person["id"]):
        eingabe.update(selbstanmeldung.vorbelegen(m, f"m{m['id']}-"))
    for v in _kommende(db.teilnahmen([person["id"]])):
        eingabe[f"bemerkung-{v['id']}"] = db.bemerkung(v["id"], person["id"])
    if person["stamm_einwilligung_am"]:
        eingabe["stamm"] = "1"
    return _angaben_aendern_seite(request, tok, person, eingabe)


@app.post("/platz/{tok}/angaben")
async def platz_angaben_aendern(request: Request, tok: str):
    """S-04: Telefon, Shirt, Verpflegung, Bemerkung – und eine neue Adresse,
    die erst gilt, wenn sie bestätigt ist. S-06: für Mitangemeldete dasselbe,
    und mit eigener Adresse stehen sie auf eigenen Füßen."""
    person = _person_mit(zugang.PLATZ, tok)
    if person is None:
        return _nicht_da(request)
    daten = await request.form()
    mit = db.mitangemeldete(person["id"])
    angebot = _angebot_fuer([person["id"]] + [m["id"] for m in mit])
    eingabe = {k: str(w) for k, w in daten.items()}
    fehler: dict[str, str] = {}
    aenderungen = []
    for wer, praefix, mit_telefon in [(person, "ich-", True)] + [(m, f"m{m['id']}-", False) for m in mit]:
        werte, f = selbstanmeldung.angaben_pruefen(daten, praefix, angebot, mit_telefon)
        fehler.update(f)
        aenderungen.append((wer, werte))
    neue_adressen = []
    for wer, praefix in [(person, "ich-")] + [(m, f"m{m['id']}-") for m in mit]:
        email = normalisieren.text(daten.get(praefix + "email_neu")).lower()[:120]
        if not email or email == wer["email"]:
            continue
        if not selbstanmeldung._EMAIL.match(email):
            fehler[praefix + "email_neu"] = "Diese Mailadresse sieht nicht vollständig aus."
        else:
            neue_adressen.append((wer, praefix, email))
    if fehler:
        return _angaben_aendern_seite(request, tok, person, eingabe, fehler, 400)
    for wer, werte in aenderungen:
        geaendert = {k: w for k, w in werte.items() if wer[k] != w}
        if geaendert:
            db.angaben_aendern(person["id"], wer["id"], geaendert)
    for v in _kommende(db.teilnahmen([person["id"]])):
        feld = f"bemerkung-{v['id']}"
        if feld in daten:
            db.bemerkung_setzen(v["id"], person["id"], person["id"],
                                str(daten.get(feld) or "").strip())
    # D-03, D-05: in den Helferstamm – oder wieder heraus, so einfach wie hinein.
    db.stamm_einwilligung(person["id"], person["id"], bool(daten.get("stamm")))
    hinweis = "angaben"
    for wer, praefix, email in neue_adressen:
        grund = db.email_vormerken(person["id"], wer["id"], email)
        if grund:
            return _angaben_aendern_seite(request, tok, person, eingabe,
                                          {praefix + "email_neu": grund}, 409)
        wer = db.helfer_laden(wer["id"])
        db.mail_einreihen(wer["id"], mail.neue_adresse(
            wer, _basis(request) + "/email/" + zugang.token(zugang.EMAIL, wer)))
        hinweis = "adresse"
    return RedirectResponse(f"/platz/{tok}?hinweis={hinweis}", status_code=303)


def _person_mit_neuer_adresse(roh: str):
    person = _person_mit(zugang.EMAIL, roh)
    return person if person is not None and person["email_neu"] else None


@app.get("/email/{tok}")
def email_bestaetigen_seite(request: Request, tok: str):
    """Wie beim ersten Bestätigen: nur eine Seite mit Knopf (7.4)."""
    person = _person_mit_neuer_adresse(tok)
    if person is None:
        return _nicht_da(request)
    return templates.TemplateResponse(
        "anmeldung_bestaetigen.html",
        _oeffentlich(request, None, person={**person, "email": person["email_neu"]},
                     token=tok, ziel=f"/email/{tok}"))


@app.post("/email/{tok}")
async def email_bestaetigen(request: Request, tok: str):
    person = _person_mit_neuer_adresse(tok)
    if person is None or not db.email_uebernehmen(person["id"]):
        return _nicht_da(request)
    person = db.helfer_laden(person["id"])
    return RedirectResponse("/platz/" + zugang.token(zugang.PLATZ, person)
                            + "?hinweis=adresse-bestaetigt", status_code=303)


@app.get("/platz/{tok}/loeschen")
def platz_loeschen_frage(request: Request, tok: str, wer: str = ""):
    person = _person_mit(zugang.PLATZ, tok)
    if person is None:
        return _nicht_da(request)
    mit = list(db.mitangemeldete(person["id"]))
    if wer.isdigit() and int(wer) in {m["id"] for m in mit}:
        andere = next(m for m in mit if m["id"] == int(wer))
        return _frage(request, tok, f"Daten von {andere['vorname'] or andere['name']} löschen?",
                      "Künftige Schichten werden abgesagt, dann ist alles weg.",
                      f"/platz/{tok}/loeschen?wer={wer}", "Ja, löschen")
    liste = ["deine Angaben und deine Schichten – künftige werden abgesagt"]
    if mit:
        liste.append("ebenso die von " + ", ".join(m["vorname"] or m["name"] for m in mit))
    liste.append("dein Link zu Mein Helferplatz gilt danach nicht mehr")
    return _frage(request, tok, "Deine Daten löschen?",
                  "Das lässt sich nicht zurücknehmen. Gelöscht werden:",
                  f"/platz/{tok}/loeschen", "Ja, alles löschen", liste=liste)


@app.post("/platz/{tok}/loeschen")
async def platz_loeschen(request: Request, tok: str, wer: str = ""):
    """S-05: alles auf einmal – außer, es ist noch etwas ausgeliehen."""
    person = _person_mit(zugang.PLATZ, tok)
    if person is None:
        return _nicht_da(request)
    mit = list(db.mitangemeldete(person["id"]))
    if wer.isdigit():
        ids = [int(wer)] if int(wer) in {m["id"] for m in mit} else []
    else:
        ids = [m["id"] for m in mit] + [person["id"]]
    if not ids:
        return _nicht_da(request)
    ergebnis = db.loeschen(person["id"], ids)
    _nach_abgabe(request, ergebnis["abgaben"])
    selbst_weg = any(p["id"] == person["id"] for p in ergebnis["geloescht"])
    selbst_wartet = any(p["id"] == person["id"] for p in ergebnis["wartet"])
    if selbst_weg or selbst_wartet:
        db.mail_einreihen(None if selbst_weg else person["id"],
                          mail.geloescht(person, wartet=selbst_wartet))
    if selbst_weg:
        return templates.TemplateResponse("platz_geloescht.html", _oeffentlich(request, None))
    hinweis = "wartet" if ergebnis["wartet"] else "geloescht"
    return RedirectResponse(f"/platz/{tok}?hinweis={hinweis}", status_code=303)


# --- Änderungen seit gestern (S-08) ------------------------------------------

@app.get("/helfer/aenderungen")
async def aenderungen(request: Request, stunden: int = 24,
                      sitzung: auth.Sitzung = Depends(_sitzung),
                      v=Depends(_veranstaltung)):
    stunden = stunden if stunden in (24, 72, 168) else 24
    return templates.TemplateResponse(
        "admin_aenderungen.html",
        _admin(request, sitzung, stunden=stunden,
               **db.aenderungen(v["id"], _leitung(sitzung), stunden)))


# --- Druckansichten und Notfallmappe (Lastenheft 2.8) --------------------------
#
# L-01 bis L-04: jederzeit aktuell, ohne Erzeugen und Warten – eine Seite,
# die der Browser druckt. Vier Ansichten, nicht mehr: Schicht, Bereich (je
# Tag oder alle), Tag, Person; dazu die Notfallmappe eines Tages. Eine
# Bereichsleitung druckt nur ihre Bereiche. Einsatzgrenzen stehen auf keinem
# Ausdruck (K-07).

def _druck(request: Request, sitzung, v, titel: str, schichten, mappe: bool = False,
           datum: str = "", person=None):
    bereiche = sorted({s["bereich_id"] for s in schichten})
    gruppen = []
    for s in schichten:
        if not gruppen or gruppen[-1]["bereich_id"] != s["bereich_id"]:
            gruppen.append({"bereich_id": s["bereich_id"], "bereich": s["bereich"],
                            "schichten": []})
        gruppen[-1]["schichten"].append(s)
    return templates.TemplateResponse(
        "druck.html",
        _kontext(request, va=v, titel=titel, gruppen=gruppen, mappe=mappe, person=person,
                 leitungen=db.leitungen(bereiche), angebot=db.angebot(v["id"]),
                 springer=db.springer_am(v["id"], datum) if mappe else [],
                 tag_lang=_tag_lang(datum) if datum else "",
                 stand=db.jetzt_lokal().strftime("%d.%m.%Y %H:%M")))


@app.get("/helfer/druck")
async def druck_auswahl(request: Request, sitzung: auth.Sitzung = Depends(_sitzung),
                        v=Depends(_veranstaltung)):
    """Was es zu drucken gibt – je Tag die Liste und die Notfallmappe, je
    Bereich und Tag."""
    return templates.TemplateResponse(
        "admin_druck.html",
        _admin(request, sitzung, tage=[{"datum": t, "lang": _tag_lang(t)} for t in db.tage(v["id"])],
               bereichsliste=db.bereiche(v["id"], _leitung(sitzung))))


def _datum(roh: str) -> str:
    try:
        return date.fromisoformat(roh).isoformat()
    except ValueError:
        return ""


@app.get("/helfer/druck/schicht/{schicht_id}")
async def druck_schicht(request: Request, schicht_id: int,
                        sitzung: auth.Sitzung = Depends(_sitzung), v=Depends(_veranstaltung)):
    _eigen(sitzung, db.leitet_schicht, schicht_id)
    schichten = db.druckliste(v["id"], schicht_id=schicht_id)
    if not schichten:
        return _fehlt(request)
    return _druck(request, sitzung, v, "Schichtliste", schichten)


@app.get("/helfer/druck/bereich/{bereich_id}")
async def druck_bereich(request: Request, bereich_id: int, tag: str = "",
                        sitzung: auth.Sitzung = Depends(_sitzung), v=Depends(_veranstaltung)):
    _eigen(sitzung, db.leitet_bereich, bereich_id)
    bereich = db.bereich_laden(bereich_id)
    if bereich is None or bereich["veranstaltung_id"] != v["id"]:
        return _fehlt(request)
    datum = _datum(tag)
    return _druck(request, sitzung, v, bereich["name"] + (" · " + _tag_lang(datum) if datum else ""),
                  db.druckliste(v["id"], bereich_id=bereich_id, datum=datum))


@app.get("/helfer/druck/tag/{tag}")
async def druck_tag(request: Request, tag: str,
                    sitzung: auth.Sitzung = Depends(_sitzung), v=Depends(_veranstaltung)):
    datum = _datum(tag)
    if not datum:
        return _fehlt(request)
    return _druck(request, sitzung, v, _tag_lang(datum),
                  db.druckliste(v["id"], datum=datum, leitung=_leitung(sitzung)))


@app.get("/helfer/druck/mappe/{tag}")
async def druck_mappe(request: Request, tag: str,
                      sitzung: auth.Sitzung = Depends(_sitzung), v=Depends(_veranstaltung)):
    """L-03: alle Listen eines Tages, nach Bereichen getrennt, mit
    Telefonnummern – am Vorabend drucken, falls am Tag nichts geht."""
    datum = _datum(tag)
    if not datum:
        return _fehlt(request)
    return _druck(request, sitzung, v, "Notfallmappe · " + _tag_lang(datum),
                  db.druckliste(v["id"], datum=datum, leitung=_leitung(sitzung)),
                  mappe=True, datum=datum)


@app.get("/helfer/druck/person/{helfer_id}")
async def druck_person(request: Request, helfer_id: int,
                       sitzung: auth.Sitzung = Depends(_sitzung), v=Depends(_veranstaltung)):
    person = db.helfer_laden(helfer_id)
    if person is None:
        return _fehlt(request)
    _eigen(sitzung, db.leitet_helfer, helfer_id)
    schichten = db.helfer_schichten(v["id"], helfer_id)
    if sitzung.ist_bereichsleitung:
        eigene = {b["id"] for b in db.bereiche(v["id"], sitzung.konto_id)}
        schichten = [s for s in schichten if s["bereich_id"] in eigene]
    leitungen = db.leitungen(sorted({s["bereich_id"] for s in schichten}))
    return templates.TemplateResponse(
        "druck_person.html",
        _kontext(request, va=v, person=person, schichten=schichten, leitungen=leitungen,
                 angebot=db.angebot(v["id"]), stand=db.jetzt_lokal().strftime("%d.%m.%Y %H:%M")))


# --- Datenschutz und Einverständnis der Eltern (Lastenheft 2.9) --------------

@app.get("/datenschutz")
def datenschutz(request: Request):
    """D-01, D-02: der ausführliche Hinweis, auf den jedes Formular verweist.
    Vor dem Start fachkundig prüfen lassen (D-09)."""
    return templates.TemplateResponse(
        "anmeldung_datenschutz.html",
        _oeffentlich(request, None, verantwortlich=config.VERANTWORTLICH,
                     frist=config.BESTAETIGEN_FRIST_STUNDEN))


def _kind_mit(roh: str):
    kind = _person_mit(zugang.ELTERN, roh)
    return kind if kind is not None and kind["eltern_email"] else None


def _eltern_seite(request: Request, tok: str, kind, bestaetigt: bool = False):
    eintraege = []
    anmelder_id = kind["angemeldet_von"] or kind["id"]
    for v in _kommende(db.teilnahmen([kind["id"]])):
        ergebnis = db.anmeldung_laden(v["id"], anmelder_id)
        eintraege += [{"va": v, **e} for e in ergebnis["personen"] if e["person"]["id"] == kind["id"]]
    return templates.TemplateResponse(
        "anmeldung_eltern.html",
        _oeffentlich(request, None, kind=kind, token=tok, eintraege=eintraege,
                     bestaetigt=bestaetigt or bool(kind["eltern_bestaetigt_am"])))


@app.get("/eltern/{tok}")
def eltern_seite(request: Request, tok: str):
    """D-06: Was das Kind vorhat – und ein Knopf. Wie beim Bestätigen löst
    erst der Klick etwas aus, nicht schon der Aufruf (7.4)."""
    kind = _kind_mit(tok)
    if kind is None:
        return _nicht_da(request)
    return _eltern_seite(request, tok, kind)


@app.post("/eltern/{tok}")
async def eltern_einverstanden(request: Request, tok: str):
    kind = _kind_mit(tok)
    if kind is None:
        return _nicht_da(request)
    db.eltern_bestaetigen(kind["id"])
    return _eltern_seite(request, tok, db.helfer_laden(kind["id"]), bestaetigt=True)


@app.post("/platz/{tok}/eltern/{helfer_id}")
async def platz_eltern_erneut(request: Request, tok: str, helfer_id: int):
    """Die Mail an die Eltern noch einmal – für eigene Minderjährige."""
    person = _person_mit(zugang.PLATZ, tok)
    kind = db.helfer_laden(helfer_id) if person else None
    if kind is None or (kind["id"] != person["id"] and kind["angemeldet_von"] != person["id"]):
        return _nicht_da(request)
    versand.eltern_mail(kind, _basis(request))
    return RedirectResponse(f"/platz/{tok}?hinweis=eltern", status_code=303)
