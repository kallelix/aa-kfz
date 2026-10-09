"""Anmeldung fürs Backoffice: persönliche Konten, Sitzung im Keks.

Gemeinsam für alle Anwendungen im Repo. Vorher lag diese Datei dreimal Wort
für Wort gleich da; ausgerechnet die sicherheitskritische Schicht dreifach zu
pflegen hieß, jede Korrektur dreimal machen zu müssen – oder sie zweimal zu
vergessen.

Zwei Wege hinein, nie beide zugleich:

* **Konten** (kern/konten.py): Mailadresse und eigenes Passwort. Im Keks
  steht ein Zufallswert, die Sitzung selbst in der Datenbank – sperren oder
  ein neues Passwort wirken sofort.
* **Das gemeinsame Passwort** aus ADMIN_PASSWORD_HASH, mit Kürzel nach Wahl.
  Gilt nur, solange es noch keinen Admin mit eigenem Passwort gibt: es ist
  der Weg, auf dem der erste Admin an die Kontenverwaltung kommt. Danach
  wird es abgewiesen, auch ein noch gültiger Keks davon.

Warum eine Klasse und kein Modul: die drei Anwendungen laufen in EINEM
Prozess und haben verschiedene Bereiche und Sitzungsdauern. Jede hält sich
eine eigene Instanz – heißt sie ``auth``, bleibt jede Aufrufstelle so, wie
sie war: ``auth.sitzung_erforderlich``, ``auth.Sitzung``, ``auth.csrf_pruefen``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from datetime import timedelta

import bcrypt
from fastapi import Request, Response

from kern.konten import Konten

# Ob die Kontenverwaltung (/konten, /konto) erreichbar ist. Sie hängt am
# gemeinsamen Dienst; läuft ein Bereich für sich allein, gibt es sie nicht,
# und die Verweise darauf blieben ins Leere. dienst/main.py setzt das.
VERWALTUNG = False


class NichtAngemeldet(Exception):
    """Löst die Umleitung zur Anmeldeseite aus (siehe kern/anmeldung.py)."""

    def __init__(self, ziel: str = "/") -> None:
        self.ziel = ziel


class NichtEingerichtet(Exception):
    """Weder ein gemeinsames Passwort noch ein Admin-Konto – das Backoffice
    ist nicht benutzbar."""


class KeinZugang(Exception):
    """Angemeldet, aber das Konto darf das nicht: fremder Bereich, oder es
    darf nur lesen."""

    def __init__(self, grund: str) -> None:
        self.grund = grund


@dataclass(frozen=True)
class Sitzung:
    kuerzel: str
    laeuft_ab: int
    token: str
    # Ohne Konto: angemeldet mit dem gemeinsamen Passwort. Das darf alles –
    # es ist der Weg, auf dem die ersten Konten entstehen.
    konto_id: int | None = None
    name: str = ""
    rolle: str = "admin"
    bereiche: tuple = ()
    verwaltung: bool = False

    def darf(self, bereich: str) -> bool:
        return self.rolle == "admin" or bereich in self.bereiche

    @property
    def darf_aendern(self) -> bool:
        return self.rolle != "lesend"

    @property
    def ist_admin(self) -> bool:
        return self.rolle == "admin"


def hash_erzeugen(klartext: str) -> str:
    """Ohne Konfiguration und deshalb hier: ``python -m kern.passwort`` ruft es."""
    return bcrypt.hashpw(klartext.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def _b64(rohdaten: bytes) -> str:
    return base64.urlsafe_b64encode(rohdaten).decode("ascii").rstrip("=")


def _entb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class Auth:
    """Alles, was an Schlüssel, Konten und Passwort einer Anwendung hängt.

    ``config`` ist das Konfigurationsmodul der jeweiligen Anwendung. Gelesen
    werden ADMIN_PASSWORD_HASH, APP_SECRET_KEY, SESSION_STUNDEN,
    COOKIE_SECURE, LOGIN_VERSUCHE, LOGIN_FENSTER_SEKUNDEN und DATABASE_URL.
    ``bereich`` ist der Schlüssel des Bereichs (kennzeichen, presse, helfer);
    ohne ihn prüft ``sitzung_erforderlich`` keinen Bereich.
    """

    # Damit auth.Sitzung und auth.NichtAngemeldet weiter am Objekt hängen und
    # keine Aufrufstelle etwas davon merkt.
    Sitzung = Sitzung
    NichtAngemeldet = NichtAngemeldet
    NichtEingerichtet = NichtEingerichtet
    KeinZugang = KeinZugang
    hash_erzeugen = staticmethod(hash_erzeugen)

    def __init__(self, config, bereich: str | None = None,
                 cookie_name: str | None = None, cookie_pfad: str = "/") -> None:
        self.config = config
        self.bereich = bereich
        # Ein Name und ein Pfad "/" fuer alle drei: das Backoffice liegt
        # unter EINER Adresse, und wer sich einmal anmeldet, soll in allen
        # drei Bereichen sein. Fuer das gemeinsame Passwort haengt das daran,
        # dass die drei denselben APP_SECRET_KEY benutzen.
        self.COOKIE_NAME = cookie_name or getattr(
            config, "COOKIE_NAME", "abfahrt_sitzung")
        self.COOKIE_PFAD = cookie_pfad
        # Ohne Datenbank (Einheitentests) nur das gemeinsame Passwort.
        self.konten = (Konten(lambda: config.DATABASE_URL)
                       if hasattr(config, "DATABASE_URL") else None)
        # Im Speicher, je Anwendung eigen.
        self._fehlversuche: dict[str, list[float]] = {}

    def init(self) -> None:
        """Legt das Schema kern an, falls nötig. Beim Start jedes Bereichs."""
        if self.konten is not None:
            self.konten.init()

    # --- Welcher Weg gilt ------------------------------------------------------

    def kontenmodus(self) -> bool:
        """Ob es einen Admin mit eigenem Passwort gibt – dann gelten nur noch
        Konten."""
        return self.konten is not None and self.konten.gibt_es_admin()

    def eingerichtet(self) -> bool:
        return bool(self.config.ADMIN_PASSWORD_HASH) or self.kontenmodus()

    # --- Gemeinsames Passwort ----------------------------------------------------

    def passwort_pruefen(self, klartext: str) -> bool:
        if not self.config.ADMIN_PASSWORD_HASH:
            return False
        try:
            return bcrypt.checkpw(
                klartext.encode("utf-8"),
                self.config.ADMIN_PASSWORD_HASH.encode("utf-8"),
            )
        except ValueError:
            # Unbrauchbarer Hash in der Env oder Nullbyte im Passwort.
            return False

    def _signieren(self, nutzlast: str) -> str:
        signatur = hmac.new(
            self.config.APP_SECRET_KEY.encode("utf-8"),
            nutzlast.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        return _b64(signatur)

    def token_erzeugen(self, kuerzel: str) -> str:
        """Keks fürs gemeinsame Passwort: signiert, ohne Datenbank. Trägt
        einen Punkt – daran unterscheidet ihn ``sitzung_lesen`` von einem
        Konto-Keks, der nur aus Zeichen ohne Punkt besteht."""
        daten = {
            "k": kuerzel,
            "exp": int(time.time()) + self.config.SESSION_STUNDEN * 3600,
        }
        nutzlast = _b64(json.dumps(daten, separators=(",", ":")).encode("utf-8"))
        return f"{nutzlast}.{self._signieren(nutzlast)}"

    def token_pruefen(self, token: str | None) -> Sitzung | None:
        if not token or token.count(".") != 1:
            return None
        nutzlast, signatur = token.split(".")
        if not hmac.compare_digest(self._signieren(nutzlast), signatur):
            return None
        try:
            daten = json.loads(_entb64(nutzlast))
            laeuft_ab = int(daten["exp"])
        except (ValueError, KeyError, TypeError):
            return None
        if laeuft_ab <= int(time.time()):
            return None
        return Sitzung(kuerzel=str(daten.get("k", "")), laeuft_ab=laeuft_ab,
                       token=token, verwaltung=VERWALTUNG)

    # --- Anmelden und abmelden ---------------------------------------------------

    def anmelden(self, email: str, passwort: str, kuerzel: str = "") -> str | None:
        """Der Keks für eine gelungene Anmeldung, sonst None."""
        if self.kontenmodus():
            konto = self.konten.anmelden(email, passwort)
            if konto is None:
                return None
            return self.konten.sitzung_anlegen(
                konto["id"], timedelta(hours=self.config.SESSION_STUNDEN))
        if self.passwort_pruefen(passwort):
            return self.token_erzeugen(kuerzel)
        return None

    def abmelden(self, request: Request) -> None:
        token = request.cookies.get(self.COOKIE_NAME) or ""
        if token and "." not in token and self.konten is not None:
            self.konten.sitzung_beenden(token)

    # --- CSRF ---------------------------------------------------------------

    def csrf_token(self, sitzungstoken: str) -> str:
        """An die Sitzung gebunden – ohne gültiges Cookie ist er wertlos."""
        return self._signieren("csrf:" + sitzungstoken)

    def csrf_pruefen(self, sitzung: Sitzung, uebermittelt: str | None) -> bool:
        return hmac.compare_digest(self.csrf_token(sitzung.token),
                                   uebermittelt or "")

    # --- Cookie -------------------------------------------------------------

    def _secure(self, request: Request) -> bool:
        if self.config.COOKIE_SECURE in ("1", "true", "ja"):
            return True
        if self.config.COOKIE_SECURE in ("0", "false", "nein"):
            return False
        # auto: der Proxy meldet über X-Forwarded-Proto, was der Browser sieht.
        return request.url.scheme == "https"

    def keks_sicher(self, request: Request) -> bool:
        """Ob ein Keks das Secure-Flag bekommt – für Kekse der Bereiche, die
        nicht die Sitzung sind (etwa die gewählte Veranstaltung)."""
        return self._secure(request)

    def cookie_setzen(self, antwort: Response, request: Request,
                      token: str) -> None:
        antwort.set_cookie(
            self.COOKIE_NAME,
            token,
            max_age=self.config.SESSION_STUNDEN * 3600,
            httponly=True,
            samesite="lax",
            secure=self._secure(request),
            path=self.COOKIE_PFAD,
        )

    def cookie_loeschen(self, antwort: Response) -> None:
        antwort.delete_cookie(self.COOKIE_NAME, path=self.COOKIE_PFAD)

    # --- Zugriffsschutz -----------------------------------------------------

    def sitzung_lesen(self, request: Request) -> Sitzung | None:
        token = request.cookies.get(self.COOKIE_NAME)
        if not token:
            return None
        if "." in token:
            # Gemeinsames Passwort. Gibt es inzwischen einen Admin mit
            # eigenem Konto, ist dieser Weg zu – auch für Kekse von vorher.
            sitzung = self.token_pruefen(token)
            if sitzung is None or self.kontenmodus():
                return None
            return sitzung
        if self.konten is None:
            return None
        konto = self.konten.sitzung_lesen(token)
        if konto is None:
            return None
        return Sitzung(
            kuerzel=konto["kuerzel"],
            laeuft_ab=int(konto["sitzung_bis"].timestamp()),
            token=token,
            konto_id=konto["id"],
            name=konto["name"],
            rolle=konto["rolle"],
            bereiche=tuple(konto["bereiche"]),
            verwaltung=VERWALTUNG,
        )

    def angemeldet(self, request: Request) -> Sitzung:
        """Irgendeine gültige Sitzung, ohne Blick auf Bereich und Rolle – für
        das eigene Konto, das auch ein Lesekonto ändern darf."""
        sitzung = self.sitzung_lesen(request)
        if sitzung is None:
            if not self.eingerichtet():
                raise NichtEingerichtet()
            ziel = request.url.path
            if request.url.query:
                ziel = f"{ziel}?{request.url.query}"
            raise NichtAngemeldet(ziel)
        return sitzung

    def sitzung_erforderlich(self, request: Request) -> Sitzung:
        sitzung = self.angemeldet(request)
        if self.bereich and not sitzung.darf(self.bereich):
            raise KeinZugang("bereich")
        # Wer nur lesen darf, schickt nichts ab. Hier an einer Stelle statt
        # an jeder der vielen Routen, die etwas ändern - die sind alle POST.
        if request.method not in ("GET", "HEAD") and not sitzung.darf_aendern:
            raise KeinZugang("lesend")
        return sitzung

    def admin_erforderlich(self, request: Request) -> Sitzung:
        sitzung = self.sitzung_erforderlich(request)
        if not sitzung.ist_admin:
            raise KeinZugang("admin")
        return sitzung

    # --- Rate Limit für den Login ------------------------------------------

    def _aufraeumen(self, schluessel: str, jetzt: float) -> list[float]:
        grenze = jetzt - self.config.LOGIN_FENSTER_SEKUNDEN
        uebrig = [t for t in self._fehlversuche.get(schluessel, []) if t > grenze]
        if uebrig:
            self._fehlversuche[schluessel] = uebrig
        else:
            self._fehlversuche.pop(schluessel, None)
        return uebrig

    def login_gesperrt(self, ip: str, email: str = "") -> bool:
        """Zählt nur Fehlversuche, je IP und je Mailadresse – sonst ließe
        sich ein Konto aus wechselnden Netzen durchprobieren. Im Speicher, pro
        Prozess – reicht hier."""
        jetzt = time.monotonic()
        schluessel = [ip] + (["mail:" + email.strip().lower()] if email.strip() else [])
        return any(len(self._aufraeumen(s, jetzt)) >= self.config.LOGIN_VERSUCHE
                   for s in schluessel)

    def login_fehlversuch(self, ip: str, email: str = "") -> None:
        jetzt = time.monotonic()
        for s in [ip] + (["mail:" + email.strip().lower()] if email.strip() else []):
            self._aufraeumen(s, jetzt)
            self._fehlversuche.setdefault(s, []).append(jetzt)

    def login_zuruecksetzen(self, ip: str, email: str = "") -> None:
        self._fehlversuche.pop(ip, None)
        if email.strip():
            self._fehlversuche.pop("mail:" + email.strip().lower(), None)
