"""Erinnerung vor der Schicht und Danke danach (Lastenheft 3.5: C-02, G-07).

    python helfer/tests/test_erinnerung.py

Zwei Tage vor der ersten Schicht kommt eine Erinnerung – mit Treffpunkt,
Bereichsleitung und Nummer, Hinweisen und dem Link zu Mein Helferplatz; wer
ohne eigene Adresse mitangemeldet ist, steht in der Mail dessen, der ihn
angemeldet hat. Nach der Veranstaltung schickt die Orga den Dank: wie viele
Stunden, die Fotos, die nächste Veranstaltung. Jede Mail genau einmal.
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


db_url = testdb.wegwerf("helfer_erinnerung")
os.environ.update({"DATABASE_URL": db_url, "APP_SECRET_KEY": "test-schluessel",
                   "JETZT_FEST": "2027-06-30 10:00", "BASIS_URL": "https://helfer.example.org"})

from app import config, db, versand  # noqa: E402

db.init()
VA = db.VERANSTALTUNGEN.anlegen({"name": "Die absolute Abfahrt 2027", "kurz": "AA 2027",
                                 "beginn": "2027-07-01", "ende": "2027-07-04",
                                 "ort": "Ilmenau", "status": "offen"})
XCO = db.VERANSTALTUNGEN.anlegen({"name": "XCO Ilmenau 2027", "kurz": "XCO 2027",
                                  "beginn": "2027-08-14", "ende": "2027-08-15",
                                  "ort": "Ilmenau", "status": "angekuendigt"})
STRECKE = db.bereich_anlegen(VA, {"name": "Strecke", "beschreibung": "", "treffpunkt": "Zelt am Ziel",
                                  "mindestalter": None, "voraussetzungen": "", "intern": 0})
KONTO = testdb.abfrage(db_url, "kern", "INSERT INTO konto (email, name, kuerzel, rolle, telefon)"
                       " VALUES ('rita@example.org', 'Rita Leitung', 'RL', 'orga', '+491701112233')"
                       " RETURNING id")[0][0]
testdb.abfrage(db_url, "helfer", "INSERT INTO bereich_leitung (bereich_id, konto_id) VALUES (?, ?)",
               (STRECKE, KONTO))


def schicht(tag, hinweis=""):
    return db.schicht_anlegen(VA, STRECKE, {
        "datum": tag, "beginn": f"{tag} 08:00", "ende": f"{tag} 12:00", "minimum": 1,
        "soll": 8, "reserve": 0, "mindestalter": None, "ort": "", "hinweis": hinweis, "intern": 0})


FR = schicht("2027-07-02", "Warme Jacke mitbringen")
SA = schicht("2027-07-03")


def sql(text, *parameter):
    return testdb.abfrage(db_url, "helfer", text, parameter)


def person(name, email=True, **mehr):
    nummer, _ = db.helfer_von_hand({"name": name, "email": name.split()[0].lower() + "@example.org"
                                    if email else ""})
    werte = {"vorname": name.split()[0], **mehr}
    sql("UPDATE helfer SET " + ", ".join(k + " = ?" for k in werte) + " WHERE id = ?",
        *werte.values(), nummer)
    return nummer


LENA = person("Lena Mutter", email_bestaetigt_am="2027-05-01 10:00")
KAI = person("Kai Mutter", email=False, angemeldet_von=LENA)
MAX = person("Max Samstag")
OTTO = person("Otto Offen")
PIA = person("Pia Angebot")
SAM = person("Sam Springer")
for helfer_id, schicht_id in ((LENA, FR), (LENA, SA), (KAI, FR), (MAX, SA), (OTTO, FR)):
    db.einteilen(schicht_id, helfer_id)
# Otto hat sich selbst angemeldet und noch nicht bestätigt; Pia hat nur ein
# Angebot von der Warteliste, noch nicht angenommen.
sql("INSERT INTO teilnahme (veranstaltung_id, helfer_id, quelle, angemeldet_am)"
    " VALUES (?, ?, 'selbst', '2027-06-29 10:00')", VA, OTTO)
sql("INSERT INTO einteilung (schicht_id, helfer_id, quelle, art, eingeteilt_am, bestaetigen_bis)"
    " VALUES (?, ?, 'selbst', 'platz', '2027-06-29 10:00', '2027-07-01 10:00')", FR, PIA)
sql("INSERT INTO verfuegbarkeit (veranstaltung_id, helfer_id, beginn, ende, springer, angelegt_am)"
    " VALUES (?, ?, '2027-07-02 06:00', '2027-07-02 13:00', 1, '2027-06-01 10:00')", VA, SAM)


def mails(typ):
    return {z["helfer_id"]: z for z in sql("SELECT * FROM mail_out WHERE typ = ? ORDER BY id", typ)}


print("Erinnerung (C-02)")
pruefe(versand.erinnern() == 2, "zwei Erinnerungen: Lena für sich und Kai, Sam als Springer")
m = mails("vorher")
pruefe(sorted(m) == sorted([LENA, SAM]),
       "Max erst später, Otto unbestätigt, Pia nur ein Angebot, Kai ohne eigene Adresse")
lena = m.get(LENA, {"body": ""})["body"]
pruefe("Übermorgen geht es los" in lena and "Du:" in lena and "Kai:" in lena
       and "Treffpunkt: Zelt am Ziel" in lena, "Lenas Mail: übermorgen, sie und Kai, mit Treffpunkt")
pruefe("15 Minuten vor Beginn" in lena and "Strecke: Rita Leitung, +491701112233" in lena,
       "mit der Bitte um 15 Minuten und der Bereichsleitung samt Nummer")
pruefe("Denk dran:" in lena and "Strecke: Warme Jacke mitbringen" in lena
       and "https://helfer.example.org/platz/" in lena, "mit dem Hinweis und dem Link zu Mein Helferplatz")
pruefe("Springer" in m.get(SAM, {"body": ""})["body"], "Sams Mail nennt seine Springer-Zeit")
pruefe(versand.erinnern() == 0, "und nur einmal")
config.JETZT_FEST = "2027-07-01 10:00"
pruefe(versand.erinnern() == 1 and MAX in mails("vorher"), "einen Tag später ist Max dran")
pruefe("Übermorgen geht es los" in mails("vorher")[MAX]["body"], "auch für ihn übermorgen")

hafen = freier_hafen()
prozess = subprocess.Popen(
    [str(PYTHON), "-m", "app"], cwd=str(WURZEL),
    env={**os.environ, "BIND": f"127.0.0.1:{hafen}", "ADMIN_PASSWORD_HASH": HASH,
         "JETZT_FEST": "2027-07-04 20:00",
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

    def anfrage(methode, pfad, daten=None):
        verbindung = http.client.HTTPConnection("127.0.0.1", hafen, timeout=10)
        koerper = urllib.parse.urlencode(daten, doseq=True).encode() if daten else None
        kopf = {"Content-Type": "application/x-www-form-urlencoded"} if koerper else {}
        if glas:
            kopf["Cookie"] = "; ".join(k + "=" + w for k, w in glas.items())
        verbindung.request(methode, pfad, body=koerper, headers=kopf)
        antwort = verbindung.getresponse()
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

    print("Danke (G-07)")
    status, _, seite = anfrage("GET", "/helfer/danke")
    csrf = re.search(r'name="csrf" value="([^"]+)"', seite).group(1)
    pruefe(status == 200 and "Noch nicht bedankt (3)" in seite and 'href="/helfer/danke"' in seite,
           "drei Mails: Lena (mit Kai), Max, Sam – unter Leute")
    status, ort, _ = anfrage("POST", "/helfer/danke", {"csrf": csrf, "fotos": "ftp://alt"})
    pruefe("hinweis=danke-fotos" in ort and not mails("danke"), "ein Foto-Link ohne https geht nicht")
    abfrage = urllib.parse.urlencode({"fotos": "https://fotos.example.org/aa2027",
                                      "wort": "Ihr wart großartig."})
    _, _, seite = anfrage("GET", "/helfer/danke?" + abfrage)
    pruefe("https://fotos.example.org/aa2027" in seite and "Ihr wart großartig." in seite
           and "Mails schicken" in seite, "die Vorschau zeigt Fotos und Wort, darunter der Knopf")
    status, ort, _ = anfrage("POST", "/helfer/danke", {"csrf": csrf,
                                                       "fotos": "https://fotos.example.org/aa2027",
                                                       "wort": "Ihr wart großartig."})
    m = mails("danke")
    pruefe("hinweis=gedankt" in ort and sorted(m) == sorted([LENA, MAX, SAM]), "drei Danke-Mails")
    lena = m.get(LENA, {"body": ""})["body"]
    pruefe("So viel habt ihr geholfen:" in lena and "Du: 8 Stunden" in lena
           and "Kai: 4 Stunden" in lena, "Lena: sie 8 Stunden, Kai 4")
    pruefe("https://fotos.example.org/aa2027" in lena and "Ihr wart großartig." in lena
           and "Die nächste Veranstaltung: XCO Ilmenau 2027" in lena
           and "https://helfer.example.org/xco-2027" in lena, "mit Fotos, Wort und dem XCO")
    pruefe("Du hast 4 Stunden geholfen." in m.get(MAX, {"body": ""})["body"], "Max: 4 Stunden")
    pruefe("Du warst als Springer da" in m.get(SAM, {"body": ""})["body"], "Sam: als Springer")
    anfrage("POST", "/helfer/danke", {"csrf": csrf})
    _, _, seite = anfrage("GET", "/helfer/danke")
    pruefe(len(mails("danke")) == 3 and "Noch nicht bedankt (0)" in seite
           and "3 haben die Mail schon" in seite, "ein zweiter Klick schickt nichts doppelt")

    print("Erst nach der Veranstaltung")
    anfrage("GET", "/helfer/veranstaltung?id=%d" % XCO)
    status, ort, _ = anfrage("POST", "/helfer/danke", {"csrf": csrf})
    pruefe("hinweis=danke-zu" in ort, "beim XCO, der noch kommt, geht es nicht")
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
