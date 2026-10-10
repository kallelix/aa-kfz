"""Helferparty (Lastenheft 4.4: G-09).

    python helfer/tests/test_party.py

Wann und wo, die Einladung an alle, die dabei sind, die Antwort über den
eigenen Link – für sich und die Mitangemeldeten, mit der Zahl der
Begleitpersonen –, die Summen für die Planung und die Erinnerung am Tag.
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


db_url = testdb.wegwerf("helfer_party")
os.environ.update({"DATABASE_URL": db_url, "APP_SECRET_KEY": "test-schluessel",
                   "JETZT_FEST": "2027-06-20 10:00", "BASIS_URL": "https://helfer.example.org"})

from app import config, db, versand, zugang  # noqa: E402

db.init()
VA = db.VERANSTALTUNGEN.anlegen({"name": "Die absolute Abfahrt 2027", "kurz": "AA 2027",
                                 "beginn": "2027-07-01", "ende": "2027-07-04",
                                 "ort": "Ilmenau", "status": "offen"})
ANGEBOT = {"goodies": 0, "shirt": 0, "schnitte": 0, "verpflegung": 0, "party": 1}
db.angebot_setzen(VA, ANGEBOT)
B = db.bereich_anlegen(VA, {"name": "Strecke", "beschreibung": "", "treffpunkt": "",
                            "mindestalter": None, "voraussetzungen": "", "intern": 0})
S = db.schicht_anlegen(VA, B, {"datum": "2027-07-02", "beginn": "2027-07-02 08:00",
                               "ende": "2027-07-02 12:00", "minimum": 1, "soll": 9, "reserve": 0,
                               "mindestalter": None, "ort": "", "hinweis": "", "intern": 0})


def sql(text, *parameter):
    return testdb.abfrage(db_url, "helfer", text, parameter)


def person(name, email=True, **mehr):
    nummer, _ = db.helfer_von_hand({"name": name, "email": name.split()[0].lower() + "@example.org"
                                    if email else ""})
    werte = {"vorname": name.split()[0], **mehr}
    sql("UPDATE helfer SET " + ", ".join(k + " = ?" for k in werte) + " WHERE id = ?",
        *werte.values(), nummer)
    return nummer


LENA = person("Lena Mutter")
KAI = person("Kai Mutter", email=False, angemeldet_von=LENA)
MAX = person("Max Allein")
OLA = person("Ola Nichtdabei")
for helfer_id in (LENA, KAI, MAX):
    db.einteilen(S, helfer_id)

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

    def mails(typ):
        return {z["helfer_id"]: z for z in sql("SELECT * FROM mail_out WHERE typ = ?", typ)}

    anfrage("POST", "/helfer/login", {"passwort": "test-passwort-123", "kuerzel": "KK",
                                      "weiter": "/helfer"})

    print("Wann und wo")
    status, _, seite = anfrage("GET", "/helfer/party")
    csrf = re.search(r'name="csrf" value="([^"]+)"', seite).group(1)
    pruefe(status == 200 and 'href="/helfer/party"' in seite and "Wann und wo" in seite,
           "Helferparty steht unter Leute")
    pruefe("Einladen (" not in seite, "eingeladen wird erst, wenn Tag und Ort feststehen")
    status, ort, _ = anfrage("POST", "/helfer/party", {"csrf": csrf, "datum": "Sonntag", "uhr": "18"})
    pruefe("hinweis=party-wann" in ort, "ein unlesbarer Tag geht nicht")
    status, ort, _ = anfrage("POST", "/helfer/party", {
        "csrf": csrf, "datum": "2027-07-04", "uhr": "18:00", "ort": "Am Orgazelt",
        "hinweis": "Grillen und Beisammensein."})
    pruefe("hinweis=party-gespeichert" in ort
           and sql("SELECT beginn, ort FROM party")[0][0] == "2027-07-04 18:00", "gespeichert")

    print("Einladen")
    _, _, seite = anfrage("GET", "/helfer/party")
    pruefe("Einladen (2)" in seite and "dich und Kai seid eingeladen" in seite,
           "zwei Mails: Lena (mit Kai) und Max – Ola war nicht dabei")
    status, ort, _ = anfrage("POST", "/helfer/party/einladen", {"csrf": csrf})
    m = mails("party")
    pruefe("hinweis=party-eingeladen" in ort and sorted(m) == sorted([LENA, MAX]), "verschickt")
    lena = m.get(LENA, {"body": ""})["body"]
    pruefe("Sonntag, 04.07. um 18:00 Uhr" in lena and "Am Orgazelt" in lena
           and f"https://helfer.example.org/party/" in lena and f"?v={VA}" in lena,
           "mit Wann, Wo und dem Link zur Antwort")
    anfrage("POST", "/helfer/party/einladen", {"csrf": csrf})
    pruefe(len(mails("party")) == 2, "ein zweiter Klick lädt niemanden doppelt ein")

    print("Antworten")
    link = re.search(r"https://helfer\.example\.org(/party/\S+)", lena).group(1)
    status, _, seite = anfrage("GET", link, mit_glas=False)
    pruefe(status == 200 and "Wer kommt?" in seite and "Kai" in seite
           and re.search(r'value="%d"\s+checked' % LENA, seite),
           "die Seite fragt für Lena und Kai, Lena vorgehakt")
    status, ort, _ = anfrage("POST", link, {"kommt": [str(LENA), str(KAI)], "begleitung": "2"},
                             mit_glas=False)
    pruefe(status == 303 and "hinweis=gespeichert" in ort, "gespeichert")
    pruefe(sorted(tuple(z.values()) for z in sql(
        "SELECT helfer_id, kommt, begleitung FROM party_zusage ORDER BY helfer_id"))
        == sorted([(LENA, 1, 2), (KAI, 1, 0)]), "Lena und Kai kommen, mit zwei Begleitpersonen")
    max_link = re.search(r"https://helfer\.example\.org(/party/\S+)", mails("party")[MAX]["body"]).group(1)
    anfrage("POST", max_link, {"begleitung": "0"}, mit_glas=False)
    pruefe(sql("SELECT kommt FROM party_zusage WHERE helfer_id = ?", MAX)[0][0] == 0,
           "Max sagt ab – auch das hilft beim Planen")
    ola = f"/party/{zugang.token(zugang.PARTY, db.helfer_laden(OLA))}?v={VA}"
    status, _, _ = anfrage("GET", ola, mit_glas=False)
    pruefe(status == 404, "wer nicht eingeladen ist, kommt mit einem Link nicht weiter")
    status, _, _ = anfrage("GET", link.replace(f"?v={VA}", "?v=9999"), mit_glas=False)
    pruefe(status == 404, "und mit einer fremden Veranstaltung auch nicht")

    tok = zugang.token(zugang.PLATZ, db.helfer_laden(LENA))
    _, _, seite = anfrage("GET", f"/platz/{tok}", mit_glas=False)
    pruefe("Helferparty" in seite and "Du kommst mit 2 Begleitpersonen" in seite,
           "Mein Helferplatz zeigt die Antwort")

    print("Für die Planung")
    _, _, seite = anfrage("GET", "/helfer/party")
    zahlen = re.findall(r'zaehler-zahl">(\d+)<', seite)
    pruefe(zahlen[:2] == ["4", "1"] and "2 Helfer, 2 Begleitung" in seite,
           "vier kommen – zwei Helfer, zwei Begleitpersonen –, einer hat abgesagt: " + str(zahlen))

    print("Am Tag")
    config.JETZT_FEST = "2027-07-04 07:00"
    pruefe(versand.party_erinnern() == 0, "vor acht Uhr noch nicht")
    config.JETZT_FEST = "2027-07-04 09:00"
    pruefe(versand.party_erinnern() == 1 and sorted(mails("party_tag")) == [LENA],
           "um neun an Lena – Kai steht in ihrer Antwort, Max hat abgesagt")
    pruefe("um 18:00 Uhr, Am Orgazelt" in mails("party_tag")[LENA]["body"], "mit Uhrzeit und Ort")
    pruefe(versand.party_erinnern() == 0, "und nur einmal")

    print("Ohne Party")
    db.angebot_setzen(VA, {**ANGEBOT, "party": 0})
    _, _, seite = anfrage("GET", "/helfer/party")
    pruefe("Keine Helferparty" in seite and 'href="/helfer/party"' not in seite,
           "die Seite sagt es, unter Leute steht sie nicht")
    status, _, _ = anfrage("GET", link, mit_glas=False)
    pruefe(status == 404, "und der Link führt ins Leere")
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
