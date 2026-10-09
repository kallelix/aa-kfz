"""Der Hilferuf (Lastenheft 3.4: C-03, C-04, C-09, A-12).

    python helfer/tests/test_hilferuf.py

Knappe Schichten auswählen, dann zweierlei: der Text für die Community mit
kurzen Links und je passender Person aus dem Helferstamm eine Mail mit
allen Schichten, die zu ihr passen. Passend heißt: zu der Zeit frei, Zeiten,
Vorlieben, Alter und Einsatzgrenzen stehen nicht dagegen, nicht abbestellt.
Je Schicht höchstens eine Mail-Runde in 24 Stunden. Abbestellen mit einem
Klick.
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


db_url = testdb.wegwerf("helfer_hilferuf")
os.environ.update({"DATABASE_URL": db_url, "APP_SECRET_KEY": "test-schluessel",
                   "JETZT_FEST": "2027-06-20 10:00", "BASIS_URL": "https://helfer.example.org"})

from app import db, hilferuf  # noqa: E402

print("Kurze Links (A-12)")
pruefe(hilferuf.kurz(7) == "7" and hilferuf.kurz(1000) == "rs" and hilferuf.kurz(0) == "0",
       "7 bleibt 7, 1000 wird rs")
pruefe(hilferuf.nummer("rs") == 1000 and hilferuf.nummer("RS") == 1000
       and hilferuf.nummer("r-s") is None and hilferuf.nummer("") is None,
       "und zurück – Unsinn ergibt nichts")
pruefe(hilferuf.whatsapp_link("Hilfe & mehr") == "https://wa.me/?text=Hilfe%20%26%20mehr",
       "der WhatsApp-Link ist ein gewöhnlicher Link mit dem Text darin")

db.init()
VA = db.VERANSTALTUNGEN.anlegen({"name": "Die absolute Abfahrt 2027", "kurz": "AA 2027",
                                 "beginn": "2027-07-01", "ende": "2027-07-04",
                                 "ort": "Ilmenau", "status": "offen"})
ALT = db.VERANSTALTUNGEN.anlegen({"name": "Die absolute Abfahrt 2026", "kurz": "AA 2026",
                                  "beginn": "2026-08-28", "ende": "2026-08-30",
                                  "ort": "Ilmenau", "status": "archiviert"})
db.angebot_setzen(VA, {"goodies": 0, "shirt": 0, "schnitte": 0, "verpflegung": 0, "party": 0})


def bereich(name, vorlieben, **mehr):
    return db.bereich_anlegen(VA, {"name": name, "beschreibung": "", "treffpunkt": "Zelt",
                                   "mindestalter": None, "voraussetzungen": "", "intern": 0,
                                   "vorlieben": vorlieben, **mehr})


STRECKE = bereich("Strecke", ["strecke"])
SHUTTLE_B = bereich("Shuttle", ["fahren"], mindestalter=18)
MERCH_B = bereich("Merch", ["menschen"])
ORGA_B = bereich("Orgabüro", [], intern=1)


def schicht(b, tag, von, bis, soll, minimum):
    return db.schicht_anlegen(VA, b, {
        "datum": tag, "beginn": f"{tag} {von}", "ende": f"{tag} {bis}", "minimum": minimum,
        "soll": soll, "reserve": 0, "mindestalter": None, "ort": "", "hinweis": "", "intern": 0})


ROT = schicht(STRECKE, "2027-07-02", "08:00", "12:00", 3, 2)
SHUTTLE = schicht(SHUTTLE_B, "2027-07-02", "09:00", "12:00", 1, 1)
MERCH = schicht(MERCH_B, "2027-07-02", "10:00", "14:00", 2, 0)
GELB = schicht(STRECKE, "2027-07-02", "13:00", "17:00", 2, 1)
VOLL = schicht(STRECKE, "2027-07-03", "08:00", "12:00", 1, 1)
INTERN = schicht(ORGA_B, "2027-07-03", "08:00", "12:00", 2, 1)


def sql(text, *parameter):
    return testdb.abfrage(db_url, "helfer", text, parameter)


STAMM = "2026-08-30 18:00"


def person(name, stamm=True, **mehr):
    nummer, _ = db.helfer_von_hand({"name": name, "email": name.split()[0].lower() + "@example.org"})
    werte = {"vorname": name.split()[0], **mehr}
    if stamm:
        werte["stamm_einwilligung_am"] = STAMM
    sql("UPDATE helfer SET " + ", ".join(k + " = ?" for k in werte) + " WHERE id = ?",
        *werte.values(), nummer)
    return nummer


ANNA = person("Anna Strecke", volljaehrig=1)
BEN = person("Ben Jung", volljaehrig=0, geburtsdatum="2011-01-01")
CARL = person("Carl Belegt", volljaehrig=1)
DORA = person("Dora Ab", volljaehrig=1, aufrufe_abbestellt_am="2027-01-01 10:00")
EMIL = person("Emil Fremd", stamm=False, volljaehrig=1)
FRIDA = person("Frida Grenze", volljaehrig=1)
GRETA = person("Greta Nachmittag", volljaehrig=1)
ZORA = person("Zora Voll", stamm=False)

# Anna mag die Strecke – das sagte sie im Vorjahr.
sql("INSERT INTO teilnahme (veranstaltung_id, helfer_id, vorlieben, angemeldet_am)"
    " VALUES (?, ?, '{strecke}', '2026-06-01 10:00')", ALT, ANNA)
db.einteilen(ROT, CARL)
db.einteilen(GELB, ZORA)
db.einteilen(VOLL, ZORA)
sql("INSERT INTO einsatzgrenze (helfer_id, bereich_id, art, angelegt_am)"
    " VALUES (?, ?, 'nicht_anbieten', '2027-01-01 10:00')", FRIDA, STRECKE)
sql("INSERT INTO verfuegbarkeit (veranstaltung_id, helfer_id, beginn, ende, springer, angelegt_am)"
    " VALUES (?, ?, '2027-07-02 13:00', '2027-07-02 18:00', 1, '2027-06-01 10:00')", VA, GRETA)

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

    def zeilen(seite):
        """(Schicht, besetzt/soll, passend) je Zeile, in der Reihenfolge der Seite."""
        return [(int(a), b, re.sub(r"<[^>]+>", "", c).strip()) for a, b, c in re.findall(
            r'name="s" value="(\d+)"[\s\S]*?(\d+/\d+)</td>\s*<td class="rechts nowrap">([\s\S]*?)</td>',
            seite)]

    def mails():
        return sql("SELECT * FROM mail_out WHERE typ = 'hilferuf' ORDER BY id")

    anfrage("POST", "/helfer/login", {"passwort": "test-passwort-123", "kuerzel": "KK",
                                      "weiter": "/helfer"})

    print("Die knappen Schichten (C-03)")
    status, _, seite = anfrage("GET", "/helfer/hilferuf")
    csrf = re.search(r'name="csrf" value="([^"]+)"', seite).group(1)
    liste = zeilen(seite)
    pruefe(status == 200 and [z[0] for z in liste] == [ROT, SHUTTLE, MERCH, GELB],
           "unter Minimum zuerst, dann der Rest unter Soll – nichts Volles, nichts Internes: "
           + str(liste))
    pruefe([z[2] for z in liste] == ["2", "1", "2", "4"],
           "passend: Strecke früh Anna und Ben, Shuttle nur Frida, Merch Ben und Frida, "
           "Strecke spät auch Carl und Greta – gefunden " + str([z[2] for z in liste]))
    pruefe('href="/helfer/hilferuf"' in seite, "Hilferuf steht unter Leute")

    print("Vorbereiten")
    status, _, seite = anfrage("GET", "/helfer/hilferuf?s=%d&s=%d" % (ROT, GELB))
    kurz_rot = "https://helfer.example.org/s/" + hilferuf.kurz(ROT)
    pruefe("Wir brauchen Hilfe bei Die absolute Abfahrt 2027!" in seite and kurz_rot in seite
           and "Fr 02.07. 08:00–12:00 · Strecke · noch 2 frei" in seite,
           "der Text für die Community, mit kurzem Link je Schicht")
    pruefe('href="https://wa.me/?text=Wir%20brauchen%20Hilfe' in seite, "und als WhatsApp-Link")
    namen = re.findall(r'href="/helfer/helfer/\d+">([^<]+)</a>', seite)
    pruefe(sorted(namen) == ["Anna Strecke", "Ben Jung", "Carl Belegt", "Greta Nachmittag"],
           "die Mail bekämen vier – nicht Dora (abbestellt), Emil (kein Stamm), Frida "
           "(Grenze): " + str(namen))
    pruefe("4 Mails schicken" in seite and "Eintragen: https://helfer.example.org/platz/" in seite,
           "ein Knopf, und die Mail zum Ansehen")

    print("Schicken")
    status, ort, _ = anfrage("POST", "/helfer/hilferuf", {"csrf": csrf, "s": [ROT, GELB]})
    pruefe(status == 303 and "hinweis=hilferuf" in ort, "der Hilferuf ist unterwegs")
    m = {z["helfer_id"]: z for z in mails()}
    pruefe(sorted(m) == sorted([ANNA, BEN, CARL, GRETA]), "vier Mails")
    anna = m.get(ANNA, {"body": ""})["body"]
    pruefe(f"aa-2027/angaben?s={ROT}" in anna and f"aa-2027/angaben?s={GELB}" in anna
           and "/abbestellen/" in anna, "Anna bekommt beide Schichten in einer Mail, mit Abbestellen")
    pruefe(f"s={ROT}" not in m.get(CARL, {"body": ""})["body"]
           and f"s={GELB}" in m.get(CARL, {"body": ""})["body"],
           "Carl nur die späte – früh ist er schon eingeteilt")
    pruefe(f"s={ROT}" not in m.get(GRETA, {"body": ""})["body"],
           "Greta nur die späte – sie hat nachmittags gesagt")
    rufe = {z["schicht_id"]: z["empfaenger"] for z in sql("SELECT * FROM hilferuf")}
    pruefe(rufe == {ROT: 2, GELB: 4}, "je Schicht vermerkt, mit wie vielen: " + str(rufe))

    link = re.search(r"https://helfer\.example\.org(/platz/\S+/aa-2027/angaben\?s=\d+)", anna)
    status, _, seite = anfrage("GET", link.group(1), mit_glas=False) if link else (0, "", "")
    pruefe(status == 200 and "Strecke" in seite, "der Link aus der Mail bereitet die Zusage vor")

    print("Nicht zweimal in 24 Stunden (C-04)")
    _, _, seite = anfrage("GET", "/helfer/hilferuf")
    liste = {z[0]: z[2] for z in zeilen(seite)}
    pruefe(liste[ROT].startswith("gerufen 20.06.") and liste[GELB].startswith("gerufen"),
           "die beiden stehen als gerufen da: " + str(liste))
    status, ort, _ = anfrage("POST", "/helfer/hilferuf", {"csrf": csrf, "s": [ROT, GELB]})
    pruefe("hinweis=hilferuf-leer" in ort and len(mails()) == 4, "ein zweites Mal geht keine Mail")
    _, _, seite = anfrage("GET", "/helfer/hilferuf?s=%d" % ROT)
    pruefe(kurz_rot in seite, "in den Text für die Community darf sie trotzdem")
    status, ort, _ = anfrage("POST", "/helfer/hilferuf", {"csrf": csrf, "s": [SHUTTLE]})
    pruefe("hinweis=hilferuf" in ort and [z["helfer_id"] for z in mails()][-1] == FRIDA,
           "für den Shuttle geht es – an Frida")

    print("Der kurze Link (A-12)")
    status, ort, _ = anfrage("GET", "/s/" + hilferuf.kurz(ROT), mit_glas=False)
    pruefe(status == 303 and ort == f"/aa-2027/schichten?s={ROT}#s{ROT}",
           "führt in die Liste, die Schicht angekreuzt")
    _, _, seite = anfrage("GET", f"/aa-2027/schichten?s={ROT}", mit_glas=False)
    pruefe(f'id="s{ROT}"' in seite and re.search(r'name="s" value="%d" checked' % ROT, seite),
           "dort steht sie mit Sprungmarke und Haken")
    for nummer, was in ((VOLL, "voll"), (INTERN, "intern")):
        status, ort, _ = anfrage("GET", "/s/" + hilferuf.kurz(nummer), mit_glas=False)
        pruefe(ort == "/aa-2027/schichten?hinweis=nicht-frei", f"{was}: dieselbe neutrale Antwort")
    _, _, seite = anfrage("GET", "/aa-2027/schichten?hinweis=nicht-frei", mit_glas=False)
    pruefe("Diese Schicht ist gerade nicht frei – hier sind andere" in seite, "mit diesem Satz")
    status, _, _ = anfrage("GET", "/s/zzzzzz", mit_glas=False)
    pruefe(status == 404, "eine Nummer, die es nicht gibt: 404")

    print("Abbestellen (C-09)")
    weg = re.search(r"https://helfer\.example\.org(/abbestellen/\S+)", anna)
    status, _, seite = anfrage("GET", weg.group(1), mit_glas=False) if weg else (0, "", "")
    pruefe(status == 200 and ">Abbestellen</button>" in seite
           and sql("SELECT aufrufe_abbestellt_am FROM helfer WHERE id = ?", ANNA)[0][0] is None,
           "der Link zeigt nur die Seite – noch ist nichts abbestellt")
    status, _, seite = anfrage("POST", weg.group(1), mit_glas=False) if weg else (0, "", "")
    pruefe(status == 200 and "Erledigt" in seite
           and sql("SELECT aufrufe_abbestellt_am FROM helfer WHERE id = ?", ANNA)[0][0],
           "ein Klick, und es ist abbestellt")
    pruefe(ANNA not in [k["person"]["id"] for k in db.hilferuf_kandidaten(VA)]
           and ANNA not in [p["id"] for p in db.stamm_einzuladen(VA)],
           "Anna bekommt danach weder Hilferufe noch Einladungen")
    tok = re.search(r"/platz/([^/\s]+)/", anna).group(1)
    _, _, seite = anfrage("GET", f"/platz/{tok}/angaben", mit_glas=False)
    pruefe('name="aufrufe" value="1"\n' in seite or re.search(r'name="aufrufe" value="1"\s*>', seite),
           "in Mein Helferplatz steht das Häkchen jetzt leer")
    db.aufrufe_setzen(ANNA, True)
    _, _, seite = anfrage("GET", f"/platz/{tok}/angaben", mit_glas=False)
    pruefe(re.search(r'name="aufrufe" value="1"\s+checked', seite), "und wieder gesetzt, wenn bestellt")
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
