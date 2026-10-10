"""Freunde mitbringen (Lastenheft 4.5: G-06).

    python helfer/tests/test_freunde.py

Nach dem Eintragen ein Knopf „Freunde mitbringen“: ein WhatsApp-Link mit
fertigem Text und dem kurzen Link auf genau diese Schicht. Wer darüber
kommt, zählt bei der Person mit, die ihn geteilt hat.
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


db_url = testdb.wegwerf("helfer_freunde")
os.environ.update({"DATABASE_URL": db_url, "APP_SECRET_KEY": "test-schluessel",
                   "JETZT_FEST": "2027-06-01 10:00", "BASIS_URL": "https://helfer.example.org"})

from app import db, hilferuf, zugang  # noqa: E402

db.init()
VA = db.VERANSTALTUNGEN.anlegen({"name": "Die absolute Abfahrt 2027", "kurz": "AA 2027",
                                 "beginn": "2027-07-01", "ende": "2027-07-04",
                                 "ort": "Ilmenau", "status": "offen"})
db.angebot_setzen(VA, {"goodies": 0, "shirt": 0, "schnitte": 0, "verpflegung": 0, "party": 0})
B = db.bereich_anlegen(VA, {"name": "Strecke", "beschreibung": "", "treffpunkt": "Zelt",
                            "mindestalter": None, "voraussetzungen": "", "intern": 0})
S1 = db.schicht_anlegen(VA, B, {"datum": "2027-07-02", "beginn": "2027-07-02 08:00",
                                "ende": "2027-07-02 12:00", "minimum": 1, "soll": 9, "reserve": 0,
                                "mindestalter": None, "ort": "", "hinweis": "", "intern": 0})


def sql(text, *parameter):
    return testdb.abfrage(db_url, "helfer", text, parameter)


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

    def anfrage(methode, pfad, daten=None, mit_glas=False):
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

    def anmelden(vorname, email, auswahl, weitere=()):
        daten = [*auswahl, ("ich-vorname", vorname), ("ich-nachname", "Berg"),
                 ("ich-email", email), ("ich-volljaehrig", "ja"), ("weitere", str(len(weitere))),
                 ("aktion", "anmelden")]
        for i, name in enumerate(weitere):
            daten += [(f"p{i}-vorname", name), (f"p{i}-nachname", "Berg"),
                      (f"p{i}-volljaehrig", "ja")]
        return anfrage("POST", "/aa-2027/angaben", daten)

    print("Der Knopf (G-06)")
    status, ort, _ = anmelden("Anna", "anna@example.org", [("s", S1)])
    _, _, seite = anfrage("GET", ort)
    ANNA = sql("SELECT id FROM helfer WHERE email = 'anna@example.org'")[0][0]
    knopf = re.search(r'<a href="(https://wa\.me/\?text=[^"]+)"[^>]*>Freunde mitbringen</a>', seite)
    pruefe(knopf is not None, "die Bestätigung hat je Schicht den Knopf „Freunde mitbringen“")
    text = urllib.parse.unquote(knopf.group(1).split("text=", 1)[1]) if knopf else ""
    zeichen = zugang.token(zugang.FREUND, db.helfer_laden(ANNA))
    kurz = f"https://helfer.example.org/s/{hilferuf.kurz(S1)}?f={zeichen}"
    pruefe("Ich helfe bei Die absolute Abfahrt 2027 mit: Fr 02.07. 08:00–12:00, Strecke." in text
           and kurz in text, "ein fertiger Text mit dem kurzen Link auf genau diese Schicht")

    print("Über den Link")
    status, ort, _ = anfrage("GET", kurz.replace("https://helfer.example.org", ""))
    pruefe(status == 303 and ort == f"/aa-2027/schichten?s={S1}&f={zeichen}#s{S1}",
           "der Link führt in die Liste, die Schicht angekreuzt, das Zeichen reist mit")
    _, _, seite = anfrage("GET", ort.split("#")[0])
    pruefe(f'name="f" value="{zeichen}"' in seite, "die Liste gibt es an die Angaben weiter")
    _, _, seite = anfrage("GET", f"/aa-2027/angaben?s={S1}&f={zeichen}")
    pruefe(f'type="hidden" name="f" value="{zeichen}"' in seite, "und die Angaben an die Anmeldung")
    status, ort, _ = anmelden("Ben", "ben@example.org", [("s", S1), ("f", zeichen)], ["Bo"])
    ben, bo = (sql("SELECT eingeladen_von FROM helfer WHERE vorname = ?", n)[0][0] for n in ("Ben", "Bo"))
    pruefe(status == 303 and ben == ANNA and bo == ANNA,
           "Ben und Bo, den er mitbrachte, zählen bei Anna")
    anmelden("Cleo", "cleo@example.org", [("s", S1), ("f", "1." + "0" * 32)])
    pruefe(sql("SELECT eingeladen_von FROM helfer WHERE vorname = 'Cleo'")[0][0] is None,
           "ein gefälschtes Zeichen zählt nirgends – die Anmeldung geht trotzdem durch")

    print("Zu sehen")
    tok = zugang.token(zugang.PLATZ, db.helfer_laden(ANNA))
    _, _, seite = anfrage("GET", f"/platz/{tok}")
    pruefe("Du hast 2 Freunde mitgebracht – Ben, Bo. Danke!" in seite
           and ">Freunde mitbringen</a>" in seite, "Mein Helferplatz: wer kam, und der Knopf")
    anfrage("POST", "/helfer/login", {"passwort": "test-passwort-123", "kuerzel": "KK",
                                      "weiter": "/helfer"}, mit_glas=True)
    BEN = sql("SELECT id FROM helfer WHERE vorname = 'Ben'")[0][0]
    _, _, seite = anfrage("GET", f"/helfer/helfer/{BEN}", mit_glas=True)
    pruefe("<dt>Kam über</dt>" in seite and "Anna Berg" in seite, "im Backoffice: Ben kam über Anna")
    _, _, seite = anfrage("GET", f"/helfer/helfer/{ANNA}", mit_glas=True)
    pruefe("<dt>Hat mitgebracht</dt>" in seite and "Ben Berg" in seite and "Bo Berg" in seite,
           "und Anna hat Ben und Bo mitgebracht")

    print("Zusammenführen")
    ANNA2 = db.helfer_von_hand({"name": "Anna Berg", "email": "anna.berg@example.org"})[0]
    DORA = db.helfer_von_hand({"name": "Dora Berg", "email": "dora@example.org"})[0]
    sql("UPDATE helfer SET eingeladen_von = ? WHERE id = ?", ANNA2, DORA)
    db.zusammenfuehren(ANNA, ANNA2, "KK")
    pruefe(sql("SELECT eingeladen_von FROM helfer WHERE id = ?", DORA)[0][0] == ANNA,
           "wen der zweite Eintrag mitgebracht hat, zählt danach beim ersten")
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
