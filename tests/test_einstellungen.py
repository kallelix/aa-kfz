"""Benachrichtigung der Orga bei neuen Anträgen.

    python tests/test_einstellungen.py

Startet den Server selbst und legt eigene Testdaten an – kein Seed nötig.
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

PYTHON = WURZEL / ".venv" / "Scripts" / "python.exe"
if not PYTHON.exists():
    PYTHON = WURZEL / ".venv" / "bin" / "python"
if not PYTHON.exists():
    PYTHON = Path(sys.executable)

HASH = "$2b$12$jWSkTX2jwE2Afm795IqpuuLOLzUGEL8Qruhfa67JQvzJd4fn.6fnm"

fehler = []


def pruefe(bedingung, text):
    print(("  ok   " if bedingung else "  FEHL ") + text)
    if not bedingung:
        fehler.append(text)


# --- Umbau einer alten Datenbank ---------------------------------------------
print("Umbau von mail_out")
from app import config as config_modul  # noqa: E402
from app import db as db_modul  # noqa: E402

alt_verzeichnis = Path(tempfile.mkdtemp(prefix="abfahrt-umbau-"))
alt_db = alt_verzeichnis / "alt.db"
con = sqlite3.connect(alt_db)
con.executescript(
    "CREATE TABLE antrag (id INTEGER PRIMARY KEY, vorname TEXT, nachname TEXT,"
    " funktion TEXT, kategorie TEXT, email TEXT, telefon TEXT, kennzeichen TEXT,"
    " bemerkung TEXT, status TEXT, entscheidung_am TEXT, entscheidung_durch TEXT,"
    " begruendung TEXT, tel_informiert_am TEXT, created_at TEXT, remote_ip TEXT);"
    "CREATE TABLE mail_out (id INTEGER PRIMARY KEY, antrag_id INTEGER,"
    " typ TEXT NOT NULL CHECK (typ IN ('eingang', 'genehmigt', 'abgelehnt')),"
    " empfaenger TEXT NOT NULL, betreff TEXT NOT NULL, body TEXT NOT NULL,"
    " versuche INTEGER NOT NULL DEFAULT 0, gesendet_am TEXT, letzter_fehler TEXT,"
    " created_at TEXT NOT NULL);"
    "INSERT INTO mail_out (id, antrag_id, typ, empfaenger, betreff, body, versuche,"
    " created_at) VALUES (7, 1, 'eingang', 'a@example.org', 'Betreff', 'Text', 2,"
    " '2026-01-01T00:00:00+00:00');"
)
con.commit()
con.close()

config_modul.DB_PATH = alt_db
ergaenzt = db_modul.init()
pruefe(any("mail_out.typ" in eintrag for eintrag in ergaenzt),
       "der Umbau wird gemeldet: " + str(ergaenzt))

con = sqlite3.connect(alt_db)
con.row_factory = sqlite3.Row
zeile = con.execute("SELECT * FROM mail_out WHERE id = 7").fetchone()
pruefe(zeile is not None, "die vorhandene Zeile hat den Umbau ueberlebt")
if zeile:
    pruefe(zeile["typ"] == "eingang" and zeile["versuche"] == 2
           and zeile["empfaenger"] == "a@example.org",
           "mit allen Werten")
    pruefe(zeile["naechster_versuch"] is None, "die neue Spalte ist da und leer")
sql = con.execute("SELECT sql FROM sqlite_master WHERE name = 'mail_out'").fetchone()[0]
pruefe("'orga'" in sql, "der neue Typ ist erlaubt")
indizes = [z[0] for z in con.execute(
    "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'mail_out'")]
pruefe("idx_mail_out_offen" in indizes, "der Index wurde wieder angelegt")
con.execute("INSERT INTO mail_out (antrag_id, typ, empfaenger, betreff, body, created_at)"
            " VALUES (1, 'orga', 'x@example.org', 'B', 'T', '2026-01-01T00:00:00+00:00')")
con.commit()
con.close()
pruefe(True, "eine orga-Mail laesst sich einfuegen")
pruefe(db_modul.init() == [], "zweiter Lauf baut nichts mehr um")


# --- Ueber HTTP --------------------------------------------------------------
def freier_hafen():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


verzeichnis = Path(tempfile.mkdtemp(prefix="abfahrt-einstellungen-"))
db = verzeichnis / "test.db"
hafen = freier_hafen()

prozess = subprocess.Popen(
    [str(PYTHON), "-m", "app"],
    cwd=str(WURZEL),
    env={**os.environ, "DB_PATH": str(db), "BIND": f"127.0.0.1:{hafen}",
         "ADMIN_PASSWORD_HASH": HASH, "APP_SECRET_KEY": "test-schluessel",
         "COOKIE_SECURE": "0", "SMTP_HOST": "", "MAIL_FROM": "",
         "PYTHONIOENCODING": "utf-8"},
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)

try:
    for _ in range(100):
        try:
            with socket.create_connection(("127.0.0.1", hafen), timeout=0.2):
                break
        except OSError:
            time.sleep(0.1)
    else:
        raise RuntimeError("Server ist nicht hochgekommen")

    keks = {"wert": ""}

    def anfrage(methode, pfad, daten=None):
        verbindung = http.client.HTTPConnection("127.0.0.1", hafen, timeout=10)
        koerper = urllib.parse.urlencode(daten or {}, encoding="utf-8", doseq=True) if daten else None
        kopf = {}
        if koerper is not None:
            kopf["Content-Type"] = "application/x-www-form-urlencoded"
        if keks["wert"]:
            kopf["Cookie"] = keks["wert"]
        verbindung.request(methode, pfad, body=koerper, headers=kopf)
        antwort = verbindung.getresponse()
        gesetzt = antwort.getheader("Set-Cookie", "")
        if gesetzt:
            keks["wert"] = gesetzt.split(";")[0]
        ergebnis = (antwort.status, antwort.getheader("Location", ""),
                    antwort.read().decode("utf-8"))
        verbindung.close()
        return ergebnis

    def mails(typ):
        con = sqlite3.connect(db)
        con.row_factory = sqlite3.Row
        try:
            return con.execute(
                "SELECT * FROM mail_out WHERE typ = ? ORDER BY id", (typ,)
            ).fetchall()
        finally:
            con.close()

    antrag = {"vorname": "Nina", "nachname": "Neu", "funktion": "Aufbau",
              "kategorie": "camping", "kennzeichen": "KA-NN 1",
              "email": "nina@example.org", "bemerkung": "Kommt Freitag"}

    print("Ohne Anmeldung")
    status, ort, _ = anfrage("GET", "/admin/einstellungen")
    pruefe(status == 303 and ort.startswith("/admin/login"),
           "Einstellungen ohne Anmeldung fuehren zur Anmeldeseite")

    print("Ohne gepflegte Adresse")
    anfrage("POST", "/", antrag)
    pruefe(mails("orga") == [], "ohne Adresse wird niemand benachrichtigt")
    pruefe(len(mails("eingang")) == 1, "die Eingangsbestaetigung kommt trotzdem")

    anfrage("POST", "/admin/login", {"passwort": "test-passwort-123", "weiter": "/admin"})
    _, _, seite = anfrage("GET", "/admin/einstellungen")
    CSRF = re.search(r'name="csrf" value="([^"]+)"', seite).group(1)
    pruefe('name="benachrichtigung"' in seite, "das Feld ist da")
    pruefe('value=""' in seite, "und noch leer")

    print("Adresse pflegen")
    status, _, text = anfrage("POST", "/admin/einstellungen",
                              {"csrf": CSRF, "benachrichtigung": "keine-adresse"})
    pruefe(status == 422 and "E-Mail-Adresse" in text, "Unfug wird abgewiesen")

    status, _, _ = anfrage("POST", "/admin/einstellungen",
                           {"csrf": "falsch", "benachrichtigung": "orga@example.org"})
    pruefe(status == 400, "ohne CSRF-Token -> 400")

    status, ort, _ = anfrage("POST", "/admin/einstellungen",
                             {"csrf": CSRF, "benachrichtigung": "  Orga@Example.ORG  "})
    _, _, seite = anfrage("GET", ort)
    pruefe("ab sofort gemeldet" in seite, "Speichern meldet Erfolg")
    pruefe('value="orga@example.org"' in seite,
           "Adresse ist getrimmt und kleingeschrieben gespeichert")

    print("Benachrichtigung geht raus")
    anfrage("POST", "/", dict(antrag, vorname="Otto", nachname="Ohne", telefon="030 1",
                              email="", kennzeichen="KA-OO 2"))
    zeilen = mails("orga")
    pruefe(len(zeilen) == 1, "ein Antrag, eine Meldung: " + str(len(zeilen)))
    if zeilen:
        meldung = zeilen[0]
        pruefe(meldung["empfaenger"] == "orga@example.org", "an die gepflegte Adresse")
        pruefe("Otto Ohne" in meldung["betreff"], "Name im Betreff: " + meldung["betreff"])
        pruefe("KA-OO 2" in meldung["body"], "Kennzeichen im Text")
        pruefe("/admin/antrag/2" in meldung["body"], "Verweis in die Detailansicht")
        pruefe(meldung["gesendet_am"] is None, "wird nicht im Request verschickt")
    pruefe(len(mails("eingang")) == 1,
           "Otto hat keine Mailadresse, bekommt also keine Bestaetigung")

    print("Abschalten")
    status, ort, _ = anfrage("POST", "/admin/einstellungen",
                             {"csrf": CSRF, "benachrichtigung": ""})
    _, _, seite = anfrage("GET", ort)
    pruefe("niemand mehr" in seite, "Leeren meldet die Abschaltung")
    vorher = len(mails("orga"))
    anfrage("POST", "/", dict(antrag, vorname="Paul", nachname="Passt", kennzeichen="KA-PP 3"))
    pruefe(len(mails("orga")) == vorher, "danach wird nicht mehr benachrichtigt")

    print("Reiter")
    _, _, liste = anfrage("GET", "/admin")
    pruefe('href="/admin/einstellungen">Einstellungen' in liste,
           "der Reiter steht im Backoffice")

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
print("Wegwerf-Datenbanken lagen in " + str(verzeichnis) + " und " + str(alt_verzeichnis))
sys.exit(1 if fehler else 0)
