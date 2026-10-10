"""Stempelkarte, Belohnungsstufen und Abzeichen (Lastenheft 4.3: G-01, G-02, G-05).

    python helfer/tests/test_anerkennung.py

Je Schicht ein Stempel; in den Kreisen, was es auf welcher Stufe gibt –
unter der Altersgrenze die Alternative –, darunter der nächste Schritt.
Ohne Goodies bleibt der Dank. Abzeichen würdigen etwas Echtes: eine Schicht
gerettet, früh aufgestanden, nachts da gewesen, das dritte Jahr dabei.
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


db_url = testdb.wegwerf("helfer_anerkennung")
os.environ.update({"DATABASE_URL": db_url, "APP_SECRET_KEY": "test-schluessel",
                   "JETZT_FEST": "2027-06-01 10:00"})

from app import db, zugang  # noqa: E402

db.init()


def veranstaltung(name, kurz, beginn, ende, status="offen"):
    return db.VERANSTALTUNGEN.anlegen({"name": name, "kurz": kurz, "beginn": beginn,
                                       "ende": ende, "ort": "Ilmenau", "status": status})


VA = veranstaltung("Die absolute Abfahrt 2027", "AA 2027", "2027-07-01", "2027-07-04")
OHNE = veranstaltung("XCO 2027", "XCO 2027", "2027-08-14", "2027-08-15")
db.angebot_setzen(VA, {"goodies": 1, "shirt": 1, "schnitte": 0, "verpflegung": 0, "party": 0})
db.angebot_setzen(OHNE, {"goodies": 0, "shirt": 0, "schnitte": 0, "verpflegung": 0, "party": 0})
for werte in ({"name": "Bier am Bierwagen", "ab_schichten": 2, "ab_stunden": None,
               "mindestalter": 16, "alternative": "Eistüte"},
              {"name": "ILRC-Cap", "ab_schichten": 4, "ab_stunden": None, "mindestalter": None,
               "alternative": ""},
              {"name": "Gutschein After-Hour", "ab_schichten": None, "ab_stunden": 8,
               "mindestalter": None, "alternative": ""}):
    db.goodie_anlegen(VA, werte)
LEER = {"beschreibung": "", "treffpunkt": "Zelt", "mindestalter": None, "voraussetzungen": "",
        "intern": 0}


def schicht(vid, bereich, tag, von, bis, minimum=1, ende_tag=None):
    return db.schicht_anlegen(vid, bereich, {
        "datum": tag, "beginn": f"{tag} {von}", "ende": f"{ende_tag or tag} {bis}",
        "minimum": minimum, "soll": 6, "reserve": 0, "mindestalter": None, "ort": "",
        "hinweis": "", "intern": 0})


STRECKE = db.bereich_anlegen(VA, {**LEER, "name": "Strecke"})
FRUEH = schicht(VA, STRECKE, "2027-07-02", "06:00", "10:00")
NACHT = schicht(VA, STRECKE, "2027-07-02", "22:00", "02:00", minimum=0, ende_tag="2027-07-03")
TAG = schicht(VA, STRECKE, "2027-07-03", "10:00", "14:00", minimum=2)
XCO_B = db.bereich_anlegen(OHNE, {**LEER, "name": "Strecke"})
XCO_S = schicht(OHNE, XCO_B, "2027-08-14", "10:00", "14:00")


def sql(text, *parameter):
    return testdb.abfrage(db_url, "helfer", text, parameter)


def person(name, **mehr):
    return {"vorname": name.split()[0], "nachname": name.split()[1], "name": name,
            "email": name.split()[0].lower() + "@example.org", "telefon": "",
            "volljaehrig": 1, "geburtsdatum": None, "alter": 30, "tshirt": None,
            "tshirt_roh": "", "veggie": None, **mehr}


# Anna trägt sich selbst ein – in die Frühschicht und die Tagschicht, die
# noch unter ihrem Minimum ist.
ANNA = db.anmelden(VA, [person("Anna Berg")], [FRUEH, TAG], [])["anmelder"]
# Bert ist 15 und schon jemand da: keine Rettung.
db.einteilen(TAG, db.helfer_von_hand({"name": "Vorab Da", "email": "da@example.org"})[0])
db.einteilen(TAG, db.helfer_von_hand({"name": "Noch Wer", "email": "wer@example.org"})[0])
BERT = db.anmelden(VA, [person("Bert Jung", volljaehrig=0, geburtsdatum="2012-01-01", alter=15)],
                   [TAG, NACHT], [])["anmelder"]

print("Stempelkarte (G-01, G-02)")
karte = db.stempelkarte(VA, ANNA)
pruefe(karte["schichten"] == 2 and [f["voll"] for f in karte["felder"]] == [True, True, False, False],
       "zwei Stempel, vier Kreise bis zum letzten Goodie")
pruefe([f["kurz"] for f in karte["felder"]] == ["Helfershirt", "Bier", "", "ILRC-Cap"],
       "in den Kreisen: Shirt ab der ersten, Bier ab der zweiten, Cap ab der vierten – "
       + str([f["kurz"] for f in karte["felder"]]))
pruefe(karte["satz"] == "Noch 2 Schichten bis ILRC-Cap.", "und was als Nächstes kommt: " + karte["satz"])
pruefe(karte["nach_stunden"] == [{"text": "Gutschein After-Hour", "ab": 8, "erreicht": True}],
       "nach Stunden: acht geschafft")
bert = db.stempelkarte(VA, BERT)
pruefe(bert["felder"][1]["kurz"] == "Eistüte", "Bert ist 15 – für ihn die Eistüte")
db.einteilen(XCO_S, ANNA)
xco = db.stempelkarte(OHNE, ANNA)
pruefe(not xco["goodies"] and xco["satz"] == "" and [f["kurz"] for f in xco["felder"]] == [""],
       "ohne Goodies: ein Stempel, keine Belohnungen")

print("Abzeichen (G-05)")
namen = [a["name"] for a in db.abzeichen(VA, ANNA)]
pruefe(namen == ["Schicht-Retter", "Frühaufsteher"],
       "Anna: eingetragen, als die Tagschicht unter Minimum war, und früh um sechs – " + str(namen))
namen = [a["name"] for a in db.abzeichen(VA, BERT)]
pruefe(namen == ["Nachtwache"], "Bert: über Mitternacht, aber nichts gerettet – " + str(namen))
pruefe(sql("SELECT retter FROM einteilung WHERE helfer_id = ? AND schicht_id = ?", ANNA, TAG)[0][0] == 1
       and sql("SELECT retter FROM einteilung WHERE helfer_id = ? AND schicht_id = ?", BERT, TAG)[0][0] == 0,
       "vermerkt wird es im Moment des Eintragens")
for jahr, kurz in ((2025, "AA 2025"), (2026, "AA 2026")):
    alt = veranstaltung("Die absolute Abfahrt %d" % jahr, kurz, f"{jahr}-07-01", f"{jahr}-07-04",
                        status="archiviert")
    b = db.bereich_anlegen(alt, {**LEER, "name": "Strecke"})
    db.einteilen(schicht(alt, b, f"{jahr}-07-02", "10:00", "12:00"), ANNA)
pruefe("Stammhelfer" in [a["name"] for a in db.abzeichen(VA, ANNA)],
       "2025, 2026, 2027 – das dritte Jahr in Folge")

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

    def anfrage(methode, pfad, daten=None):
        verbindung = http.client.HTTPConnection("127.0.0.1", hafen, timeout=10)
        koerper = urllib.parse.urlencode(daten, doseq=True).encode() if daten else None
        kopf = {"Content-Type": "application/x-www-form-urlencoded"} if koerper else {}
        verbindung.request(methode, pfad, body=koerper, headers=kopf)
        antwort = verbindung.getresponse()
        ergebnis = (antwort.status, antwort.getheader("Location", ""),
                    unescape(antwort.read().decode("utf-8")))
        verbindung.close()
        return ergebnis

    print("Zu sehen")
    tok = zugang.token(zugang.PLATZ, db.helfer_laden(ANNA))
    _, _, seite = anfrage("GET", f"/platz/{tok}")
    pruefe('class="kudos"' in seite and '<div class="voll">Helfershirt</div>' in seite
           and "Noch 2 Schichten bis ILRC-Cap." in seite, "Mein Helferplatz zeigt die Stempelkarte")
    pruefe('title="eingetragen, als die Schicht unter ihrem Minimum war">Schicht-Retter' in seite,
           "mit Abzeichen und dem, wofür es steht")
    status, ort, _ = anfrage("POST", "/aa-2027/angaben", {
        "s": str(FRUEH), "ich-vorname": "Cleo", "ich-nachname": "Neu",
        "ich-email": "cleo@example.org", "ich-volljaehrig": "ja", "ich-tshirt": "M",
        "weitere": "0", "aktion": "anmelden"})
    _, _, seite = anfrage("GET", ort) if status == 303 else (0, "", "")
    pruefe("Deine Stempelkarte" in seite and "Noch 1 Schicht bis Bier am Bierwagen." in seite
           and "Frühaufsteher" in seite,
           "die Bestätigung zeigt sie gleich: ein Stempel, noch einer bis zum Bier")
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
