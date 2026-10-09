"""Stufen, Reserve, Springer und kurzfristige Absagen in Übersicht und
Monitor (Lastenheft 2.7).

    python helfer/tests/test_stufen.py

Rot unter Minimum, gelb unter Soll, grün ab Soll – und die Reserve zählt nie
als fehlend (R-02). Die Springer, die jetzt können, und wie viele bald
dazukommen (R-06, T-04). Kurzfristige Absagen auf dem Monitor, ohne Namen
(S-07). Die Uhr steht dafür mitten in der Veranstaltung.
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


db_url = testdb.wegwerf("helfer_stufen")
os.environ.update({"DATABASE_URL": db_url, "APP_SECRET_KEY": "test-schluessel",
                   "JETZT_FEST": "2027-07-02 09:00", "MONITOR_WARNUNG": "1"})

from app import db  # noqa: E402

db.init()
VA = db.VERANSTALTUNGEN.anlegen({"name": "Die absolute Abfahrt 2027", "kurz": "AA 2027",
                                 "beginn": "2027-07-01", "ende": "2027-07-04",
                                 "ort": "Ilmenau", "status": "offen"})
LEER = {"beschreibung": "", "treffpunkt": "", "mindestalter": None, "voraussetzungen": "",
        "intern": 0}
B = {name: db.bereich_anlegen(VA, {**LEER, "name": name})
     for name in ("Rotweg", "Gelbweg", "Gruenweg", "Kurzweg")}


def schicht(bereich, von, bis, soll, minimum, reserve=0):
    return db.schicht_anlegen(VA, B[bereich], {
        "datum": "2027-07-02", "beginn": f"2027-07-02 {von}", "ende": f"2027-07-02 {bis}",
        "minimum": minimum, "soll": soll, "reserve": reserve, "mindestalter": None,
        "ort": "", "hinweis": "", "intern": 0})


ROT = schicht("Rotweg", "08:00", "12:00", 3, 3)
GELB = schicht("Gelbweg", "08:00", "12:00", 3, 1)
GRUEN = schicht("Gruenweg", "10:00", "12:00", 1, 1, reserve=1)
KURZ = schicht("Kurzweg", "10:30", "14:00", 2, 2)


def person(name):
    nummer, _ = db.helfer_von_hand({"name": name, "email": name.split()[0].lower() + "@example.org"})
    return nummer


leute = {name: person(name) for name in
         ("Anna Berg", "Bert Berg", "Cleo Berg", "Dora Berg", "Emil Berg", "Fritz Berg",
          "Gerd Berg", "Hanna Berg", "Ida Berg", "Jonas Berg")}
db.einteilen(ROT, leute["Anna Berg"])
db.einteilen(GELB, leute["Bert Berg"])
db.einteilen(GELB, leute["Cleo Berg"])
db.einteilen(GRUEN, leute["Dora Berg"])
testdb.abfrage(db_url, "helfer", "INSERT INTO einteilung (schicht_id, helfer_id, quelle, art,"
               " eingeteilt_am) VALUES (%d, %d, 'hand', 'reserve', '2027-06-01 10:00:00')"
               % (GRUEN, leute["Emil Berg"]))
db.einteilen(KURZ, leute["Fritz Berg"])
KURZ_HANNA = db.einteilen(KURZ, leute["Hanna Berg"])
# Ida kann jetzt einspringen, Jonas ab Mittag, Gerd ist zwar Springer, aber
# gerade eingeteilt.
for name, von, bis in (("Ida Berg", "06:00", "13:00"), ("Jonas Berg", "11:00", "18:00"),
                       ("Gerd Berg", "06:00", "13:00")):
    testdb.abfrage(db_url, "helfer", "INSERT INTO verfuegbarkeit (veranstaltung_id, helfer_id,"
                   " beginn, ende, springer, angelegt_am) VALUES (%d, %d, '2027-07-02 %s',"
                   " '2027-07-02 %s', 1, '2027-06-01 10:00:00')" % (VA, leute[name], von, bis))
db.einteilen(ROT, leute["Gerd Berg"])
# Hanna sagt kurzfristig ab – Kurzweg fällt unter sein Minimum.
abgabe = db.stornieren(leute["Hanna Berg"], KURZ_HANNA, "krank")
TOKEN = db.monitor_token(anlegen=True)

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

    def anfrage(methode, pfad, daten=None, glas=None):
        glas = {} if glas is None else glas
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
        ergebnis = (antwort.status, unescape(antwort.read().decode("utf-8")))
        verbindung.close()
        return ergebnis

    def kachel(seite, schicht_id):
        """Das <li> einer Schicht auf dem Monitor."""
        treffer = re.search(r'<li class="([^"]*)">\s*<button[^>]*data-schicht="%d"' % schicht_id, seite)
        return " ".join(treffer.group(1).split()) if treffer else None

    pruefe(abgabe["kurzfristig"] and abgabe["unter_minimum"],
           "Vorher: Hannas Absage ist kurzfristig, Kurzweg unter Minimum")

    print("Übersicht (R-02, R-06)")
    admin = {}
    anfrage("POST", "/helfer/login", {"passwort": "test-passwort-123", "kuerzel": "KK",
                                      "weiter": "/helfer"}, admin)
    status, seite = anfrage("GET", "/helfer", glas=admin)
    pruefe(status == 200 and re.search(r"Unter Minimum</p>\s*<p class=\"zaehler-zahl\">2</p>", seite)
           and "zaehler-rot" in seite, "eine Kachel: zwei Schichten unter Minimum")
    pruefe('<progress class="balken"' in seite and 'style="width' not in seite,
           "der Balken als <progress>, ohne style-Attribut")
    zeilen = re.findall(r'href="/helfer/schicht/(\d+)">[^<]+</a></td>\s*(?:\{[^}]*\}\s*)?'
                        r'<td class="rechts"><span class="marke marke-(\w+)"', seite)
    pruefe(zeilen and zeilen[0][1] == "luecke"
           and (str(GELB), "knapp") in zeilen and (str(ROT), "luecke") in zeilen,
           "Lücken: rot zuerst, gelb als knapp – gefunden " + str(zeilen))
    pruefe("Springer jetzt (1)" in seite and "Ida Berg" in seite
           and "kommen 1 dazu" in seite and "Gerd Berg" not in seite.split("Springer jetzt")[1][:400],
           "Springer jetzt: Ida – Gerd ist eingeteilt, Jonas kommt bald")
    status, seite = anfrage("GET", "/helfer/schichten", glas=admin)
    pruefe("hat-luecke stufe-rot" in seite and "hat-luecke stufe-gelb" in seite,
           "die Schichtliste färbt rot und gelb")

    print("Monitor (R-02, T-04, S-07)")
    status, seite = anfrage("GET", "/monitor/" + TOKEN + "/inhalt")
    pruefe(status == 200 and kachel(seite, ROT) == "schicht schicht-luecke"
           and kachel(seite, GELB) == "schicht schicht-knapp",
           "jetzt im Dienst: Rotweg rot, Gelbweg gelb")
    pruefe(kachel(seite, GRUEN) == "" and "1</span>" in seite and "/1 +1" in seite,
           "Gruenweg grün, mit Reserve +1 – die zählt nicht als fehlend")
    pruefe("Kurzfristig abgesagt:" in seite and "Kurzweg 10:30–14:00" in seite
           and "unter Minimum" in seite and "Hanna" not in seite and "krank" not in seite,
           "die kurzfristige Absage steht oben – ohne Namen und ohne Grund")
    pruefe("Springer jetzt:" in seite and "Ida Berg" in seite and "1 weitere" in seite,
           "Springer jetzt, und wie viele bald kommen")
    status, seite = anfrage("GET", "/monitor/" + TOKEN + "/inhalt?tag=2027-07-02")
    pruefe(kachel(seite, ROT) == "schicht-luecke" and kachel(seite, GELB) == "schicht-knapp",
           "der Tagesblick färbt genauso")
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
