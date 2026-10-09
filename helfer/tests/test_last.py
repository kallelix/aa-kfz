"""Lasttest (Lastenheft 2.10): viele auf dieselben Plätze, Tauschen
gegeneinander.

    python helfer/tests/test_last.py

Zwei Ebenen:

- **Datenbank**: 200 Anmeldungen auf dieselben zehn Plätze aus 50 Threads,
  jeder mit eigener Verbindung – echte Gleichzeitigkeit, wie sie mehrere
  Server-Prozesse erzeugen würden. Mehr Threads nicht: PostgreSQL nimmt in
  der Grundeinstellung höchstens 100 Verbindungen an.
- **HTTP**: 200 Anfragen gleichzeitig an den Server, wie er im Betrieb läuft
  (ein Prozess). Gemessen wird, wie lange die letzte wartet.

Dazu Tauschen gegeneinander: viele wollen in dieselben wenigen Plätze, und
Paare tauschen in Gegenrichtung – das ist der Fall, in dem zwei Transaktionen
aufeinander warten können (Deadlock).
"""

import http.client
import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
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
THREADS = 50

fehler = []


def pruefe(bedingung, text):
    print(("  ok   " if bedingung else "  FEHL ") + text)
    if not bedingung:
        fehler.append(text)


def freier_hafen():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


db_url = testdb.wegwerf("helfer_last")
os.environ.update({"DATABASE_URL": db_url, "APP_SECRET_KEY": "test-schluessel",
                   "JETZT_FEST": "2027-06-01 10:00"})

from app import db  # noqa: E402

db.init()
VA = db.VERANSTALTUNGEN.anlegen({"name": "Die absolute Abfahrt 2027", "kurz": "AA 2027",
                                 "beginn": "2027-07-01", "ende": "2027-07-04",
                                 "ort": "Ilmenau", "status": "offen"})
db.angebot_setzen(VA, {"goodies": 0, "shirt": 0, "schnitte": 0, "verpflegung": 0, "party": 0})
BEREICH = db.bereich_anlegen(VA, {"name": "Streckenposten", "beschreibung": "", "treffpunkt": "",
                                  "mindestalter": None, "voraussetzungen": "", "intern": 0})


def schicht(tag, von, bis, soll):
    return db.schicht_anlegen(VA, BEREICH, {
        "datum": tag, "beginn": f"{tag} {von}", "ende": f"{tag} {bis}", "minimum": 1,
        "soll": soll, "reserve": 0, "mindestalter": None, "ort": "", "hinweis": "",
        "intern": 0})


ZEHN = schicht("2027-07-02", "08:00", "12:00", 10)
ZEHN_HTTP = schicht("2027-07-03", "08:00", "12:00", 10)
VIELE = schicht("2027-07-04", "08:00", "12:00", 30)
WENIGE = schicht("2027-07-04", "13:00", "17:00", 5)
LINKS = schicht("2027-07-01", "08:00", "12:00", 10)
RECHTS = schicht("2027-07-01", "13:00", "17:00", 10)


def person(name):
    return {"vorname": name, "nachname": "Last", "name": name + " Last",
            "email": name.lower() + "@example.org", "telefon": "", "volljaehrig": 1,
            "geburtsdatum": None, "alter": None, "tshirt": None, "tshirt_roh": "",
            "veggie": None}


def zahl(schicht_id):
    return testdb.abfrage(db_url, "helfer", "SELECT COUNT(*) AS n FROM einteilung"
                          " WHERE schicht_id = %d" % schicht_id)[0]["n"]


def gleichzeitig(aufgabe, werte):
    """Führt `aufgabe` für alle Werte aus THREADS Threads aus und sammelt,
    was herauskommt: 'ok', 'abgewiesen' oder die Ausnahme als Text."""
    def lauf(wert):
        try:
            aufgabe(wert)
            return "ok"
        except db.AnmeldeFehler:
            return "abgewiesen"
        except Exception as ausnahme:  # noqa: BLE001 – genau das wollen wir sehen
            return f"{type(ausnahme).__name__}: {ausnahme}"
    with ThreadPoolExecutor(THREADS) as pool:
        return list(pool.map(lauf, werte))


print("Datenbank: 200 auf dieselben zehn Plätze")
beginn = time.perf_counter()
ergebnisse = gleichzeitig(lambda i: db.anmelden(VA, [person(f"A{i}")], [ZEHN], []), range(200))
dauer = time.perf_counter() - beginn
andere = sorted({e for e in ergebnisse if e not in ("ok", "abgewiesen")})
pruefe(ergebnisse.count("ok") == 10 and ergebnisse.count("abgewiesen") == 190 and not andere,
       f"genau 10 drin, 190 abgewiesen, sonst nichts ({dauer:.1f} s)"
       + (" – " + "; ".join(andere)[:300] if andere else ""))
pruefe(zahl(ZEHN) == 10, "und genau zehn Einteilungen in der Datenbank")

print("Datenbank: dreißig wollen in fünf Plätze tauschen")
leute = []
for i in range(30):
    leute.append(db.anmelden(VA, [person(f"T{i}")], [VIELE], [])["anmelder"])
einteilungen = {h: testdb.abfrage(db_url, "helfer", "SELECT id FROM einteilung WHERE helfer_id = %d"
                                  % h)[0]["id"] for h in leute}
ergebnisse = gleichzeitig(lambda h: db.umbuchen(VA, h, einteilungen[h], WENIGE), leute)
andere = sorted({e for e in ergebnisse if e not in ("ok", "abgewiesen")})
pruefe(ergebnisse.count("ok") == 5 and not andere,
       "fünf haben getauscht, die anderen sind abgewiesen"
       + (" – " + "; ".join(andere)[:300] if andere else ""))
pruefe(zahl(WENIGE) == 5 and zahl(VIELE) == 25,
       "fünf drüben, fünfundzwanzig geblieben – niemand doppelt, niemand verloren")

print("Datenbank: Tauschen in Gegenrichtung")
links = [db.anmelden(VA, [person(f"L{i}")], [LINKS], [])["anmelder"] for i in range(9)]
rechts = [db.anmelden(VA, [person(f"R{i}")], [RECHTS], [])["anmelder"] for i in range(9)]
for runde in range(3):
    paare = []
    for h in links + rechts:
        zeile = testdb.abfrage(db_url, "helfer", "SELECT id, schicht_id FROM einteilung"
                               " WHERE helfer_id = %d" % h)[0]
        paare.append((h, zeile["id"], RECHTS if zeile["schicht_id"] == LINKS else LINKS))
    ergebnisse = gleichzeitig(lambda p: db.umbuchen(VA, p[0], p[1], p[2]), paare)
    andere = sorted({e for e in ergebnisse if e not in ("ok", "abgewiesen")})
    je_person = testdb.abfrage(db_url, "helfer", "SELECT helfer_id, COUNT(*) AS n FROM einteilung"
                               " WHERE schicht_id IN (%d, %d) GROUP BY helfer_id" % (LINKS, RECHTS))
    pruefe(not andere and len(je_person) == 18 and all(z["n"] == 1 for z in je_person)
           and zahl(LINKS) <= 10 and zahl(RECHTS) <= 10,
           f"Runde {runde + 1}: kein Deadlock, jede Person genau einmal, nirgends mehr als zehn "
           f"({ergebnisse.count('ok')} getauscht)" + (" – " + "; ".join(andere)[:300] if andere else ""))

print("HTTP: 200 gleichzeitig an den Server")
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
    # Einmal warmlaufen, damit der erste Zugriff nicht in die Messung fällt.
    verbindung = http.client.HTTPConnection("127.0.0.1", hafen, timeout=30)
    verbindung.request("GET", "/aa-2027/schichten")
    verbindung.getresponse().read()
    verbindung.close()

    start = threading.Barrier(200)

    def anmelden_http(i):
        daten = urllib.parse.urlencode([
            ("s", ZEHN_HTTP), ("ich-vorname", f"H{i}"), ("ich-nachname", "Last"),
            ("ich-email", f"h{i}@example.org"), ("ich-volljaehrig", "ja"),
            ("weitere", 0), ("aktion", "anmelden")]).encode()
        verbindung = http.client.HTTPConnection("127.0.0.1", hafen, timeout=120)
        start.wait()
        beginn = time.perf_counter()
        try:
            verbindung.request("POST", "/aa-2027/angaben", body=daten,
                               headers={"Content-Type": "application/x-www-form-urlencoded"})
            antwort = verbindung.getresponse()
            antwort.read()
            return antwort.status, time.perf_counter() - beginn
        except Exception as ausnahme:  # noqa: BLE001
            return type(ausnahme).__name__, time.perf_counter() - beginn
        finally:
            verbindung.close()

    with ThreadPoolExecutor(200) as pool:
        antworten = list(pool.map(anmelden_http, range(200)))
    stati = [s for s, _ in antworten]
    zeiten = sorted(z for _, z in antworten)
    pruefe(stati.count(303) == 10 and stati.count(409) == 190,
           f"10 angemeldet, 190 freundlich abgewiesen – {sorted(set(map(str, stati)))}")
    pruefe(zahl(ZEHN_HTTP) == 10, "genau zehn in der Datenbank")
    pruefe(zeiten[-1] < 60,
           f"die letzte Antwort nach {zeiten[-1]:.1f} s (Median {zeiten[len(zeiten) // 2]:.1f} s)")
    start_liste = threading.Barrier(200)

    def liste_http(_):
        verbindung = http.client.HTTPConnection("127.0.0.1", hafen, timeout=120)
        start_liste.wait()
        beginn = time.perf_counter()
        try:
            verbindung.request("GET", "/aa-2027/schichten")
            antwort = verbindung.getresponse()
            antwort.read()
            return antwort.status, time.perf_counter() - beginn
        except Exception as ausnahme:  # noqa: BLE001
            return type(ausnahme).__name__, time.perf_counter() - beginn
        finally:
            verbindung.close()

    with ThreadPoolExecutor(200) as pool:
        antworten = list(pool.map(liste_http, range(200)))
    zeiten = sorted(z for _, z in antworten)
    pruefe(all(s == 200 for s, _ in antworten) and zeiten[-1] < 60,
           f"200 laden gleichzeitig die Liste: die letzte nach {zeiten[-1]:.1f} s "
           f"(Median {zeiten[len(zeiten) // 2]:.1f} s)")
    verbindung = http.client.HTTPConnection("127.0.0.1", hafen, timeout=30)
    verbindung.request("GET", "/aa-2027/schichten")
    seite = verbindung.getresponse().read().decode("utf-8")
    verbindung.close()
    pruefe(f'name="w" value="{ZEHN_HTTP}"' in seite, "die Liste zeigt die Schicht danach als voll")
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
