"""Fahrzeug im Backoffice erfassen – wahlweise gleich genehmigt.

    python tests/test_erfassen.py

Startet den Server selbst und braucht keine Vorbereitung. Geprüft wird der
Weg, der vorher zwei Schritte brauchte: anlegen und danach genehmigen.
"""

import http.client
import os
import re
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.parse
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WURZEL))
sys.path.insert(0, str(WURZEL / "kennzeichen"))

PYTHON = WURZEL / ".venv" / "Scripts" / "python.exe"
if not PYTHON.exists():
    PYTHON = WURZEL / ".venv" / "bin" / "python"
if not PYTHON.exists():
    PYTHON = Path(sys.executable)

# bcrypt-Hash von "test-passwort-123".
HASH = "$2b$12$jWSkTX2jwE2Afm795IqpuuLOLzUGEL8Qruhfa67JQvzJd4fn.6fnm"
PASSWORT = "test-passwort-123"

fehler = []


def pruefe(bedingung, text):
    print(("  ok   " if bedingung else "  FEHL ") + text)
    if not bedingung:
        fehler.append(text)


NL = chr(10)


# --- Die Regel selbst, ohne Server ------------------------------------------
print("Mehrere Kennzeichen aus einem Feld")
from app import validation as _v  # noqa: E402

faelle = [
    ("IL-A 123", ["IL-A 123"], "eines bleibt eines"),
    ("IL-A 123, IL-B 7; IL-C 9", ["IL-A 123", "IL-B 7", "IL-C 9"],
     "Komma und Semikolon trennen"),
    ("IL-A 123" + NL + "IL-B 7", ["IL-A 123", "IL-B 7"], "Zeilenumbruch auch"),
    # Das Leerzeichen darf NICHT trennen - es steht mitten im Kennzeichen.
    ("IL-A 123", ["IL-A 123"], "das Leerzeichen im Kennzeichen bleibt"),
    ("IL-A 123, ila123", ["IL-A 123"],
     "dieselbe Nummer anders geschrieben faellt weg"),
    ("  ,, IL-X 1 ,  ", ["IL-X 1"], "Leerraum und leere Stuecke stoeren nicht"),
]
for roh, erwartet, was in faelle:
    liste, meldung = _v.kennzeichen_liste(roh)
    pruefe(liste == erwartet and not meldung, was + ": " + str(liste))

for roh in ("AB", "IL-A 123, XY", "x" * 40):
    liste, meldung = _v.kennzeichen_liste(roh)
    pruefe(not liste and meldung,
           "unbrauchbare Eingabe wird benannt: " + meldung[:44])


print("Kontaktweg: Pflicht nur, wenn noch entschieden werden muss")
from app import validation  # noqa: E402

grund = {"vorname": "A", "nachname": "B", "funktion": "C",
         "kategorie": "expo", "kennzeichen": "B-XY 1"}
_, meldungen = validation.pruefen(dict(grund))
pruefe("email" in meldungen and "telefon" in meldungen,
       "ohne Kontakt und mit Vorgabe: beide Felder bemaengelt")
_, meldungen = validation.pruefen(dict(grund), kontakt_pflicht=False)
pruefe(not meldungen,
       "ohne Kontakt, aber ohne Pflicht: nichts zu bemaengeln")
# Alles andere bleibt Pflicht - die Ausnahme gilt nur dem Kontaktweg.
_, meldungen = validation.pruefen({"kategorie": "expo"}, kontakt_pflicht=False)
pruefe("vorname" in meldungen and "nachname" in meldungen
       and "funktion" in meldungen,
       "Name und Funktion bleiben Pflicht: " + ", ".join(sorted(meldungen)))


# --- Ueber HTTP --------------------------------------------------------------
def freier_hafen():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


verzeichnis = Path(tempfile.mkdtemp(prefix="abfahrt-erfassen-"))
db = verzeichnis / "test.db"
hafen = freier_hafen()

prozess = subprocess.Popen(
    [str(PYTHON), "-m", "app"],
    cwd=str(WURZEL / "kennzeichen"),
    env={**os.environ, "DB_PATH": str(db), "BIND": f"127.0.0.1:{hafen}",
         "ADMIN_PASSWORD_HASH": HASH, "APP_SECRET_KEY": "test-schluessel",
         "COOKIE_SECURE": "0", "SMTP_HOST": "", "MAIL_FROM": "",
         "KONTINGENTE": "camping:1", "PYTHONIOENCODING": "utf-8"},
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
)

keks = {"wert": ""}


def ruf(methode, pfad, daten=None):
    c = http.client.HTTPConnection("127.0.0.1", hafen, timeout=15)
    koerper = urllib.parse.urlencode(daten).encode() if daten else None
    kopf = {"Content-Type": "application/x-www-form-urlencoded"} if daten else {}
    if keks["wert"]:
        kopf["Cookie"] = keks["wert"]
    c.request(methode, pfad, body=koerper, headers=kopf)
    r = c.getresponse()
    gesetzt = r.getheader("Set-Cookie", "")
    if gesetzt:
        keks["wert"] = gesetzt.split(";")[0]
    ergebnis = (r.status, r.getheader("Location", ""),
                r.read().decode("utf-8", "replace"))
    c.close()
    return ergebnis


def zeilen(sql, *parameter):
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    try:
        return con.execute(sql, parameter).fetchall()
    finally:
        con.close()


try:
    for _ in range(150):
        try:
            with socket.create_connection(("127.0.0.1", hafen), timeout=0.2):
                break
        except OSError:
            time.sleep(0.2)
    else:
        raise RuntimeError("Server ist nicht hochgekommen")

    print("Ohne Anmeldung geht nichts")
    status, ort, _ = ruf("GET", "/kennzeichen/antrag/neu")
    pruefe(status == 303 and ort.startswith("/kennzeichen/login"),
           "das Formular fuehrt zur Anmeldung")

    ruf("POST", "/kennzeichen/login",
        {"passwort": PASSWORT, "kuerzel": "KK", "weiter": "/kennzeichen"})

    print("Der Weg zum Formular")
    status, _, seite = ruf("GET", "/kennzeichen")
    pruefe('href="/kennzeichen/antrag/neu"' in seite,
           "die Liste bietet 'Fahrzeug erfassen' an")
    status, _, seite = ruf("GET", "/kennzeichen/antrag/neu")
    pruefe(status == 200, "das Formular laedt")
    # Die Route muss VOR /kennzeichen/antrag/{antrag_id} stehen, sonst landet
    # "neu" als Wert in antrag_id und die Anfrage scheitert an der
    # Zahlenpruefung.
    pruefe("int_parsing" not in seite and "Fahrzeug erfassen" in seite,
           "und wird nicht als Antragsnummer missverstanden")
    pruefe("von 1" in seite, "das Kontingent steht bei der Kategorie")
    csrf = re.search(r'name="csrf" value="([^"]+)"', seite).group(1)

    print("Erfassen und gleich genehmigen")
    status, ort, _ = ruf("POST", "/kennzeichen/antrag/neu", {
        "csrf": csrf, "vorname": "Anna", "nachname": "Berg",
        "funktion": "Sanitäter", "kategorie": "camping",
        "kennzeichen": "IL-A 123", "aktion": "genehmigen"})
    pruefe(status == 303 and "hinweis=angelegt_genehmigt" in ort, "meldet Erfolg")
    anna = zeilen("SELECT * FROM antrag WHERE nachname = 'Berg'")[0]
    pruefe(anna["status"] == "genehmigt", "steht sofort auf genehmigt")
    pruefe(bool(anna["entscheidung_am"]) and anna["entscheidung_durch"] == "KK",
           "mit Zeitpunkt und Kuerzel - wie bei einer Genehmigung von Hand")
    pruefe(not anna["email"] and not anna["telefon"],
           "und ohne Kontakt, denn die Person stand davor")
    pruefe(not zeilen("SELECT id FROM mail_out"),
           "ohne Adresse geht keine Mail hinaus")

    print("Nur erfassen: dann ist der Kontakt Pflicht")
    status, _, seite = ruf("POST", "/kennzeichen/antrag/neu", {
        "csrf": csrf, "vorname": "Bert", "nachname": "Öhl",
        "funktion": "Aufbau", "kategorie": "expo", "kennzeichen": "IL-B 7",
        "aktion": "nur_anlegen"})
    pruefe(status == 422 and "mindestens E-Mail oder Telefon" in seite,
           "ohne Kontakt abgelehnt - die Entscheidung muss ja jemanden erreichen")
    pruefe(not zeilen("SELECT id FROM antrag WHERE nachname = 'Öhl'"),
           "und nichts gespeichert")

    status, ort, _ = ruf("POST", "/kennzeichen/antrag/neu", {
        "csrf": csrf, "vorname": "Bert", "nachname": "Öhl",
        "funktion": "Aufbau", "kategorie": "expo", "kennzeichen": "IL-B 7",
        "telefon": "0170 1", "aktion": "nur_anlegen"})
    bert = zeilen("SELECT * FROM antrag WHERE nachname = 'Öhl'")[0]
    pruefe("hinweis=angelegt" in ort and bert["status"] == "neu",
           "mit Telefon geht es, und der Antrag wartet auf die Entscheidung")
    pruefe(bert["entscheidung_am"] is None,
           "ohne Entscheidungsdaten - es ist ja keine gefallen")

    print("Die Zusage nur auf Wunsch")
    ruf("POST", "/kennzeichen/antrag/neu", {
        "csrf": csrf, "vorname": "Dora", "nachname": "Elm", "funktion": "Bau",
        "kategorie": "expo", "kennzeichen": "IL-D 4",
        "email": "dora@example.org", "aktion": "genehmigen"})
    pruefe(not zeilen("SELECT id FROM mail_out"),
           "mit Adresse, aber ohne Haekchen: keine Mail")

    ruf("POST", "/kennzeichen/antrag/neu", {
        "csrf": csrf, "vorname": "Clara", "nachname": "Dorn",
        "funktion": "Presse", "kategorie": "vip", "kennzeichen": "IL-C 9",
        "email": "clara@example.org", "aktion": "genehmigen",
        "mail_schicken": "1"})
    mails = zeilen("SELECT * FROM mail_out")
    pruefe(len(mails) == 1 and mails[0]["empfaenger"] == "clara@example.org"
           and mails[0]["typ"] == "genehmigt",
           "mit Haekchen genau eine Zusage")

    print("Was nicht durchgeht")
    status, _, seite = ruf("POST", "/kennzeichen/antrag/neu",
                           {"csrf": csrf, "vorname": "X"})
    pruefe(status == 422 and "feld-fehler" in seite,
           "ohne Pflichtfelder abgelehnt")
    status, _, _ = ruf("POST", "/kennzeichen/antrag/neu", {
        "csrf": "falsch", "vorname": "Y", "nachname": "Z", "funktion": "a",
        "kategorie": "expo", "kennzeichen": "IL-E 1", "aktion": "genehmigen"})
    pruefe(status == 400, "ohne gueltigen Token abgelehnt")

    print("Mehrere Fahrzeuge in einem Rutsch")
    status, ort, _ = ruf("POST", "/kennzeichen/antrag/neu", {
        "csrf": csrf, "vorname": "Emil", "nachname": "Fuchs",
        "funktion": "Aufbau", "kategorie": "expo",
        # Vier Eingaben, aber "ilf2" ist derselbe Wagen wie "IL-F 2".
        "kennzeichen": "IL-F 2" + NL + "IL-G 3, ilf2; IL-H 4",
        "aktion": "genehmigen"})
    fuchs = zeilen("SELECT * FROM antrag WHERE nachname = 'Fuchs' ORDER BY id")
    pruefe(len(fuchs) == 3,
           "drei Antraege aus vier Eingaben - die Dopplung faellt weg")
    pruefe([z["kennzeichen"] for z in fuchs] == ["IL-F 2", "IL-G 3", "IL-H 4"],
           "je Antrag ein Kennzeichen: "
           + ", ".join(z["kennzeichen"] for z in fuchs))
    pruefe(all(z["status"] == "genehmigt" and z["entscheidung_durch"] == "KK"
               for z in fuchs),
           "alle drei genehmigt, alle mit Kuerzel")
    pruefe(all(z["vorname"] == "Emil" and z["funktion"] == "Aufbau"
               for z in fuchs),
           "und alle mit denselben uebrigen Angaben")
    pruefe(status == 303 and "hinweis=mehrere_genehmigt" in ort
           and "anzahl=3" in ort,
           "danach zurueck in die Liste, nicht auf einen der drei: " + ort)

    status, _, seite = ruf("GET", "/kennzeichen?" + ort.split("?", 1)[1])
    pruefe("3 Fahrzeuge erfasst und genehmigt" in seite,
           "die Liste sagt, wie viele es waren")

    print("Ein Tippfehler mittendrin verwirft alles")
    vorher = len(zeilen("SELECT id FROM antrag"))
    status, _, seite = ruf("POST", "/kennzeichen/antrag/neu", {
        "csrf": csrf, "vorname": "Gerd", "nachname": "Hain", "funktion": "Bau",
        "kategorie": "expo", "kennzeichen": "IL-I 5, XY, IL-J 6",
        "aktion": "genehmigen"})
    pruefe(status == 422 and "„XY“" in seite,
           "die Meldung nennt das unbrauchbare Stueck")
    pruefe(len(zeilen("SELECT id FROM antrag")) == vorher,
           "und kein einziger der drei ist entstanden")
    pruefe("IL-I 5, XY, IL-J 6" in seite,
           "die Eingabe steht noch da - sonst waere die Arbeit weg")

    print("Das Ergebnis steht in der Liste")
    status, _, seite = ruf("GET", "/kennzeichen?status=genehmigt")
    pruefe(seite.count("marke-genehmigt") == 6,
           "sechs genehmigte Antraege, ohne dass jemand zweimal geklickt haette")

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
    sys.exit(1)
print("alle Pruefungen bestanden")
print("Wegwerf-Datenbank lag in " + str(verzeichnis))
