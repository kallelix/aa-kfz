"""Verhalten hinter dem Reverse Proxy (Schritt 10).

Startet den Server selbst – zweimal, mit unterschiedlichem
`FORWARDED_ALLOW_IPS` – und prüft, was in `remote_ip` landet und wann das
Session-Cookie `Secure` bekommt.

    python tests/test_proxy.py

Braucht keinen laufenden Server und keine Konfiguration; legt sich eigene
Wegwerf-Datenbanken an.
"""

import http.client
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.parse
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
PYTHON = WURZEL / ".venv" / "Scripts" / "python.exe"
if not PYTHON.exists():
    PYTHON = WURZEL / ".venv" / "bin" / "python"
if not PYTHON.exists():
    PYTHON = Path(sys.executable)

# bcrypt-Hash von "test-passwort-123"
HASH = "$2b$12$jWSkTX2jwE2Afm795IqpuuLOLzUGEL8Qruhfa67JQvzJd4fn.6fnm"

fehler = []


def pruefe(bedingung, text):
    print(("  ok   " if bedingung else "  FEHL ") + text)
    if not bedingung:
        fehler.append(text)


def freier_hafen():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Server:
    """Startet `python -m app` mit eigener Umgebung und raeumt wieder auf."""

    def __init__(self, **umgebung):
        self.verzeichnis = Path(tempfile.mkdtemp(prefix="abfahrt-proxy-"))
        self.hafen = freier_hafen()
        self.db = self.verzeichnis / "test.db"
        self.umgebung = {
            **os.environ,
            "DB_PATH": str(self.db),
            "BIND": f"127.0.0.1:{self.hafen}",
            "ADMIN_PASSWORD_HASH": HASH,
            "APP_SECRET_KEY": "test-schluessel",
            "SMTP_HOST": "",
            "MAIL_FROM": "",
            "PYTHONIOENCODING": "utf-8",
            **umgebung,
        }

    def __enter__(self):
        self.prozess = subprocess.Popen(
            [str(PYTHON), "-m", "app"],
            cwd=str(WURZEL),
            env=self.umgebung,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for _ in range(100):
            try:
                with socket.create_connection(("127.0.0.1", self.hafen), timeout=0.2):
                    return self
            except OSError:
                time.sleep(0.1)
        raise RuntimeError("Server ist nicht hochgekommen")

    def __exit__(self, *_):
        self.prozess.terminate()
        try:
            self.prozess.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.prozess.kill()

    def anfrage(self, methode, pfad, daten=None, kopfzeilen=None):
        verbindung = http.client.HTTPConnection("127.0.0.1", self.hafen, timeout=10)
        koerper = urllib.parse.urlencode(daten or {}, encoding="utf-8") if daten else None
        alle = dict(kopfzeilen or {})
        if koerper is not None:
            alle["Content-Type"] = "application/x-www-form-urlencoded"
        verbindung.request(methode, pfad, body=koerper, headers=alle)
        antwort = verbindung.getresponse()
        ergebnis = (antwort.status, antwort.getheader("Location", ""),
                    antwort.getheader("Set-Cookie", ""), antwort.read().decode("utf-8"))
        verbindung.close()
        return ergebnis

    def letzte_ip(self):
        con = sqlite3.connect(self.db)
        try:
            return con.execute("SELECT remote_ip FROM antrag ORDER BY id DESC LIMIT 1").fetchone()[0]
        finally:
            con.close()


ANTRAG = {
    "vorname": "Max", "nachname": "Mustermann", "funktion": "Aufbau",
    "kategorie": "camping", "kennzeichen": "B-MM 1", "telefon": "030 111",
}


# --- Proxy wird vertraut -----------------------------------------------------
print("Proxy wird vertraut (FORWARDED_ALLOW_IPS=127.0.0.1)")
with Server(FORWARDED_ALLOW_IPS="127.0.0.1", COOKIE_SECURE="auto") as s:
    s.anfrage("POST", "/", ANTRAG, {"X-Forwarded-For": "203.0.113.7"})
    pruefe(s.letzte_ip() == "203.0.113.7",
           "echte Client-IP wird protokolliert, nicht die des Proxys: " + str(s.letzte_ip()))

    # So sieht es aus, wenn der Client selbst eine IP mitschickt und nginx die
    # echte per $proxy_add_x_forwarded_for hinten anhaengt.
    s.anfrage("POST", "/", ANTRAG, {"X-Forwarded-For": "9.9.9.9, 203.0.113.8"})
    pruefe(s.letzte_ip() == "203.0.113.8",
           "vom Client erfundener Eintrag setzt sich nicht durch: " + str(s.letzte_ip()))

    s.anfrage("POST", "/", ANTRAG, {"X-Forwarded-For": "198.51.100.4, 127.0.0.1"})
    pruefe(s.letzte_ip() == "198.51.100.4",
           "vertraute Zwischenstationen werden uebersprungen: " + str(s.letzte_ip()))

    # Cookie: Secure nur, wenn der Browser HTTPS gesehen hat.
    _, _, keks, _ = s.anfrage("POST", "/admin/login",
                              {"passwort": "test-passwort-123", "weiter": "/admin"},
                              {"X-Forwarded-Proto": "https"})
    pruefe("Secure" in keks, "mit X-Forwarded-Proto: https bekommt das Cookie Secure")
    pruefe("httponly" in keks.lower() and "samesite=lax" in keks.lower(),
           "HttpOnly und SameSite stehen ebenfalls dran")
    pruefe("Path=/admin" in keks, "Cookie gilt nur unter /admin: " + keks)

    _, _, keks, _ = s.anfrage("POST", "/admin/login",
                              {"passwort": "test-passwort-123", "weiter": "/admin"},
                              {"X-Forwarded-Proto": "http"})
    pruefe("Secure" not in keks, "ohne HTTPS kein Secure – sonst waere lokal keine Anmeldung moeglich")

# --- Proxy wird nicht vertraut -----------------------------------------------
print("Proxy wird nicht vertraut (FORWARDED_ALLOW_IPS zeigt woandershin)")
with Server(FORWARDED_ALLOW_IPS="10.0.0.10", COOKIE_SECURE="auto") as s:
    s.anfrage("POST", "/", ANTRAG, {"X-Forwarded-For": "203.0.113.7"})
    pruefe(s.letzte_ip() == "127.0.0.1",
           "fremde X-Forwarded-For werden ignoriert: " + str(s.letzte_ip()))

    _, _, keks, _ = s.anfrage("POST", "/admin/login",
                              {"passwort": "test-passwort-123", "weiter": "/admin"},
                              {"X-Forwarded-Proto": "https"})
    pruefe("Secure" not in keks, "auch das Protokoll wird nicht geglaubt")

# --- COOKIE_SECURE erzwungen -------------------------------------------------
print("COOKIE_SECURE=1")
with Server(FORWARDED_ALLOW_IPS="127.0.0.1", COOKIE_SECURE="1") as s:
    _, _, keks, _ = s.anfrage("POST", "/admin/login",
                              {"passwort": "test-passwort-123", "weiter": "/admin"})
    pruefe("Secure" in keks, "erzwungenes Secure gilt auch ohne Proxy-Kopfzeile")

# --- IP_SPEICHERN=0 ----------------------------------------------------------
print("IP_SPEICHERN=0")
with Server(FORWARDED_ALLOW_IPS="127.0.0.1", IP_SPEICHERN="0") as s:
    s.anfrage("POST", "/", ANTRAG, {"X-Forwarded-For": "203.0.113.7"})
    pruefe(s.letzte_ip() is None, "es wird gar keine IP gespeichert")

# --- Einstiegspunkt liest BIND ----------------------------------------------
print("Einstiegspunkt")
with Server(FORWARDED_ALLOW_IPS="127.0.0.1") as s:
    status, _, _, seite = s.anfrage("GET", "/")
    pruefe(status == 200 and "Durchfahrtsberechtigung" in seite,
           "python -m app lauscht auf der Adresse aus BIND")

print()
if fehler:
    print("FEHLGESCHLAGEN (" + str(len(fehler)) + "):")
    for eintrag in fehler:
        print("  - " + eintrag)
else:
    print("alle Pruefungen bestanden")
sys.exit(1 if fehler else 0)
