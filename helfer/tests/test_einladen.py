"""Einladen bei Anmeldestart (Lastenheft 3.3: C-08).

    python helfer/tests/test_einladen.py

Wer Interesse vorgemerkt hat, bekommt eine Mail, sobald die Anmeldung offen
ist – einmal, danach ist die Adresse weg. Den Helferstamm lädt die Orga mit
einem Klick ein: wer eingewilligt hat und noch nicht dabei ist, bekommt
seinen Link direkt zu den Schichten. Niemand bekommt zwei Einladungen.
"""

import http.client
import os
import re
import socket
import subprocess
import sys
import time
import urllib.parse
from html import unescape
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WURZEL))
sys.path.insert(0, str(WURZEL.parent))
from kern import testdb  # noqa: E402

PYTHON = WURZEL.parent / ".venv" / "Scripts" / "python.exe"
if not PYTHON.exists():
    PYTHON = WURZEL.parent / ".venv" / "bin" / "python"
if not PYTHON.exists():
    PYTHON = Path(sys.executable)

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


db_url = testdb.wegwerf("helfer_einladen")
os.environ.update({"DATABASE_URL": db_url, "APP_SECRET_KEY": "test-schluessel",
                   "JETZT_FEST": "2027-06-01 10:00", "BASIS_URL": "https://helfer.example.org"})

from app import db, versand  # noqa: E402

db.init()


def veranstaltung(name, kurz, beginn, ende, ab):
    return db.VERANSTALTUNGEN.anlegen({"name": name, "kurz": kurz, "beginn": beginn,
                                       "ende": ende, "ort": "Ilmenau", "status": "offen",
                                       "anmeldung_ab": ab})


VA = veranstaltung("Die absolute Abfahrt 2027", "AA 2027", "2027-07-01", "2027-07-04", "2027-06-01")
XCO = veranstaltung("XCO Ilmenau 2027", "XCO 2027", "2027-08-14", "2027-08-15", "2027-06-15")
BEREICH = db.bereich_anlegen(VA, {"name": "Strecke", "beschreibung": "", "treffpunkt": "",
                                  "mindestalter": None, "voraussetzungen": "", "intern": 0})
SCHICHT = db.schicht_anlegen(VA, BEREICH, {
    "datum": "2027-07-02", "beginn": "2027-07-02 08:00", "ende": "2027-07-02 12:00",
    "minimum": 1, "soll": 4, "reserve": 0, "mindestalter": None, "ort": "", "hinweis": "",
    "intern": 0})


def sql(text, *parameter):
    return testdb.abfrage(db_url, "helfer", text, parameter)


def person(name, email, **mehr):
    nummer, _ = db.helfer_von_hand({"name": name, "email": email})
    if mehr:
        sql("UPDATE helfer SET " + ", ".join(k + " = ?" for k in mehr) + " WHERE id = ?",
            *mehr.values(), nummer)
    return nummer


STAMM = "2026-08-30 18:00"
LENA = person("Lena Stamm", "lena@example.org", vorname="Lena", stamm_einwilligung_am=STAMM)
SCHON = person("Max Dabei", "max@example.org", stamm_einwilligung_am=STAMM)
EINGETEILT = person("Ida Eingeteilt", "ida@example.org", stamm_einwilligung_am=STAMM)
OHNE = person("Ole Ohne", "ole@example.org")
GEHT = person("Gerd Geht", "gerd@example.org", stamm_einwilligung_am=STAMM,
              loeschen_beantragt_am="2027-05-01 10:00")
sql("INSERT INTO teilnahme (veranstaltung_id, helfer_id, angemeldet_am) VALUES (?, ?, ?)",
    VA, SCHON, "2027-05-01 10:00")
db.einteilen(SCHICHT, EINGETEILT)

db.interesse_vormerken(VA, "anna@example.org", "Anna")
db.interesse_vormerken(XCO, "bert@example.org", "")


def mails(typ):
    return sql("SELECT * FROM mail_out WHERE typ = ? ORDER BY id", typ)


print("Vorgemerkte (C-08)")
pruefe(versand.anmeldestart() == 1, "eine Mail – die Abfahrt ist offen, der XCO noch nicht")
m = mails("anmeldestart")
pruefe(len(m) == 1 and m[0]["empfaenger"] == "anna@example.org"
       and "Hallo Anna," in m[0]["body"] and "https://helfer.example.org/aa-2027" in m[0]["body"],
       "an Anna, mit dem Link zur Anmeldung")
pruefe([z["email"] for z in sql("SELECT email FROM interesse")] == ["bert@example.org"],
       "Annas Adresse ist danach weg, Berts wartet noch")
pruefe(versand.anmeldestart() == 0 and len(mails("anmeldestart")) == 1, "und nur einmal")

hafen = freier_hafen()
prozess = subprocess.Popen(
    [str(PYTHON), "-m", "app"], cwd=str(WURZEL),
    env={**os.environ, "BIND": f"127.0.0.1:{hafen}", "ADMIN_PASSWORD_HASH": HASH,
         "COOKIE_SECURE": "0", "ZEITPLAN_SERIEN": "", "PYTHONIOENCODING": "utf-8"},
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

try:
    for _ in range(100):
        try:
            with socket.create_connection(("127.0.0.1", hafen), timeout=0.2):
                break
        except OSError:
            time.sleep(0.1)
    else:
        raise RuntimeError("Server ist nicht hochgekommen")

    glas = {}

    def anfrage(methode, pfad, daten=None, mit_glas=True):
        verbindung = http.client.HTTPConnection("127.0.0.1", hafen, timeout=10)
        koerper = urllib.parse.urlencode(daten, doseq=True).encode() if daten else None
        kopf = {"Content-Type": "application/x-www-form-urlencoded"} if koerper else {}
        if glas and mit_glas:
            kopf["Cookie"] = "; ".join(k + "=" + w for k, w in glas.items())
        verbindung.request(methode, pfad, body=koerper, headers=kopf)
        antwort = verbindung.getresponse()
        if mit_glas:
            for gesetzt in antwort.headers.get_all("Set-Cookie") or []:
                name, _, wert = gesetzt.split(";")[0].partition("=")
                glas[name] = wert
        ergebnis = (antwort.status, antwort.getheader("Location", ""),
                    unescape(antwort.read().decode("utf-8")))
        verbindung.close()
        return ergebnis

    anfrage("POST", "/helfer/login", {"passwort": "test-passwort-123", "kuerzel": "KK",
                                      "weiter": "/helfer"})
    anfrage("GET", "/helfer/veranstaltung?id=%d" % VA)

    print("Helferstamm einladen")
    status, _, seite = anfrage("GET", "/helfer/einladen")
    csrf = re.search(r'name="csrf" value="([^"]+)"', seite).group(1)
    pruefe(status == 200 and 'href="/helfer/einladen"' in seite, "Einladen steht unter Leute")
    pruefe("Noch nicht eingeladen (1)" in seite and "Lena Stamm" in seite
           and not any(n in seite for n in ("Max Dabei", "Ida Eingeteilt", "Ole Ohne", "Gerd Geht")),
           "nur Lena: Max und Ida sind schon dabei, Ole hat nicht eingewilligt, Gerd geht")
    pruefe("1 Person einladen" in seite and "Hallo Lena," in seite
           and "(Link zu den Schichten)" in seite, "ein Knopf, und die Mail zum Ansehen")

    status, ort, _ = anfrage("POST", "/helfer/einladen", {"csrf": csrf})
    pruefe(status == 303 and "hinweis=eingeladen" in ort, "eingeladen")
    m = mails("einladung")
    link = re.search(r"https://helfer\.example\.org(/platz/[^/\s]+/aa-2027/schichten)",
                     m[0]["body"]) if m else None
    pruefe(len(m) == 1 and m[0]["empfaenger"] == "lena@example.org"
           and m[0]["helfer_id"] == LENA and link, "Lena bekommt ihre Mail, mit Link zu den Schichten")
    status, _, seite = anfrage("GET", link.group(1), mit_glas=False) if link else (0, "", "")
    pruefe(status == 200 and "Schichten dazunehmen" in seite and "Strecke" in seite,
           "der Link führt ohne Anmelden zu den Schichten")
    pruefe("/platz/" in m[0]["body"].split("abstellen")[-1] if m else False,
           "und sagt, wo man die Einladungen abstellt")

    anfrage("POST", "/helfer/einladen", {"csrf": csrf})
    pruefe(len(mails("einladung")) == 1, "ein zweiter Klick schickt nichts doppelt")
    _, _, seite = anfrage("GET", "/helfer/einladen")
    pruefe("Noch nicht eingeladen (0)" in seite and "1 hat schon eine Einladung" in seite,
           "danach ist niemand mehr offen")

    print("Erst wenn die Anmeldung offen ist")
    anfrage("GET", "/helfer/veranstaltung?id=%d" % XCO)
    status, _, seite = anfrage("GET", "/helfer/einladen")
    pruefe("Lena Stamm" in seite and "Einladen geht, sobald die Anmeldung offen ist" in seite
           and "einladen</button>" not in seite, "beim XCO steht Lena auf der Liste, aber ohne Knopf")
    status, ort, _ = anfrage("POST", "/helfer/einladen", {"csrf": csrf})
    pruefe("hinweis=einladen-zu" in ort and len(mails("einladung")) == 1,
           "und auch per POST geht es nicht")
finally:
    prozess.terminate()
    try:
        prozess.wait(timeout=10)
    except subprocess.TimeoutExpired:
        prozess.kill()

print()
if fehler:
    print("FEHLGESCHLAGEN (" + str(len(fehler)) + "):")
    for eintrag in fehler:
        print("  - " + eintrag)
else:
    print("alle Pruefungen bestanden")
sys.exit(1 if fehler else 0)
