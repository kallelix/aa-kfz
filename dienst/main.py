"""Setzt die drei Anwendungen zu einem ASGI-Dienst zusammen."""

from __future__ import annotations

import contextlib
import logging
import os
import sys
from pathlib import Path

from starlette.applications import Starlette
from starlette.routing import Host
from starlette.staticfiles import StaticFiles

WURZEL = Path(__file__).resolve().parents[1]
if str(WURZEL) not in sys.path:
    sys.path.insert(0, str(WURZEL))

protokoll = logging.getLogger("uvicorn.error")


def _hosts() -> dict[str, str]:
    """Welcher Hostname zu welchem Bereich gehört.

    Ohne Angabe bleibt der Bereich über den Hostnamen nicht erreichbar – dann
    hilft nur noch die Pfadverteilung unten. Für die Entwicklung reicht das,
    im Betrieb gehören alle vier gesetzt.
    """
    return {
        "kennzeichen": os.environ.get("HOST_KENNZEICHEN", "").strip(),
        "presse": os.environ.get("HOST_PRESSE", "").strip(),
        "helfer": os.environ.get("HOST_HELFER", "").strip(),
        "admin": os.environ.get("HOST_ADMIN", "").strip(),
    }


# Die drei erst hier laden: sie lesen beim Import ihre Konfiguration, und die
# hängt an den Umgebungsvariablen, die die Unit setzt.
from kennzeichen.app.main import app as kennzeichen_app  # noqa: E402
from presse.app.main import app as presse_app  # noqa: E402
from helfer.app.main import app as helfer_app  # noqa: E402
from kennzeichen.app import config as kennzeichen_config  # noqa: E402
from kern import auth as kern_auth  # noqa: E402
from kern import konten_app  # noqa: E402

# Ab hier zeigen die Bereiche "Mein Konto" und "Konten" im Kopf: im Dienst
# gibt es die Verwaltung, in einem allein gestarteten Bereich nicht.
kern_auth.VERWALTUNG = True

BEREICHE = {
    "kennzeichen": kennzeichen_app,
    "presse": presse_app,
    "helfer": helfer_app,
}

# Startseite, Kontenverwaltung und das eigene Konto. Die Einladungen gehen
# über das Postfach des Kennzeichen-Bereichs: es schreibt schon heute an die
# Orga, und die Konten gehören zu keinem Bereich allein.
KONTEN = konten_app.bauen(kennzeichen_config, mail_config=kennzeichen_config)


class AdminVerteiler:
    """Wählt den Bereich am ersten Pfadstück.

    Kein Mount: die Anwendungen tragen ihren Bereich schon im Pfad – ihre
    Routen heißen /kennzeichen/…, /presse/…, /helfer/…. Ein Mount würde das
    Stück abschneiden und die Anwendung fände ihre eigene Route nicht mehr.
    Hier wird der Pfad also unverändert durchgereicht.
    """

    def __init__(self, bereiche: dict, konten) -> None:
        self.bereiche = bereiche
        # /static gehoert dem Backoffice als ganzem: ein Stilblatt und ein
        # Wappen fuer alle drei Bereiche. Was nur einen Bereich betrifft,
        # liegt unter /<bereich>/static und kommt von dessen Anwendung.
        self.static = StaticFiles(directory=str(WURZEL / "kern" / "static"))
        # Alles andere - die Startseite, /konten, /konto - gehoert der
        # Kontenverwaltung.
        self.konten = konten

    async def __call__(self, scope, receive, send) -> None:
        pfad = scope.get("path", "/")
        erstes = pfad.strip("/").split("/")[0] if pfad.strip("/") else ""
        anwendung = self.bereiche.get(erstes)
        if anwendung is not None:
            await anwendung(scope, receive, send)
        elif erstes == "static":
            # Wie ein Mount: StaticFiles zieht root_path vom Pfad ab.
            await self.static(dict(scope, root_path=scope.get("root_path", "") + "/static"),
                              receive, send)
        else:
            await self.konten(scope, receive, send)


admin_verteiler = AdminVerteiler(BEREICHE, KONTEN)


class NachPfad:
    """Rückfall für die Entwicklung: kein Hostname gesetzt.

    Dann liegt alles unter einer Adresse – die öffentlichen Seiten unter
    /oeffentlich/<bereich>, die Backoffices wie gehabt unter /<bereich>.
    Nur zum Ausprobieren; im Betrieb verteilen die Hostnamen.
    """

    def __init__(self, bereiche: dict, verteiler) -> None:
        self.bereiche = bereiche
        self.verteiler = verteiler

    async def __call__(self, scope, receive, send) -> None:
        pfad = scope.get("path", "/")
        teile = pfad.strip("/").split("/")
        if teile and teile[0] == "oeffentlich" and len(teile) > 1:
            anwendung = self.bereiche.get(teile[1])
            if anwendung is not None:
                rest = "/" + "/".join(teile[2:])
                scope = dict(scope, path=rest, raw_path=rest.encode())
                await anwendung(scope, receive, send)
                return
        await self.verteiler(scope, receive, send)


@contextlib.asynccontextmanager
async def lifespan(app):
    """Startet und beendet alle drei.

    Ein zusammengesetzter ASGI-Dienst ruft die Lebensläufe der Teile NICHT
    von selbst auf – ohne das hier liefe keine Datenbankmigration, kein
    Zeitplan-Abruf und kein Helferabgleich.
    """
    async with contextlib.AsyncExitStack() as stapel:
        for name, anwendung in BEREICHE.items():
            protokoll.info("starte Bereich %s", name)
            await stapel.enter_async_context(
                anwendung.router.lifespan_context(anwendung))
        yield


def _routen():
    hosts = _hosts()
    routen = []
    for name, anwendung in BEREICHE.items():
        if hosts[name]:
            routen.append(Host(hosts[name], app=anwendung, name=name))
    if hosts["admin"]:
        routen.append(Host(hosts["admin"], app=admin_verteiler, name="admin"))
    if not routen:
        protokoll.warning(
            "Kein HOST_… gesetzt - alles laeuft ueber Pfade. Fuer die "
            "Entwicklung in Ordnung, im Betrieb gehoeren die vier gesetzt.")
    # Was zu keinem Hostnamen passt, geht ueber die Pfade. Damit ist der
    # Dienst auch ohne Namensaufloesung zu bedienen.
    routen.append(Host("{host}", app=NachPfad(BEREICHE, admin_verteiler)))
    return routen


app = Starlette(routes=_routen(), lifespan=lifespan)
