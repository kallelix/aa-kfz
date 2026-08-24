"""Formular und Datenmodell der Presse-Akkreditierung (Schritte 1 und 2).

    python presse/tests/test_anmeldung.py

Startet den Server selbst und legt eine Wegwerf-Datenbank an – keine
Vorbereitung nötig.
"""

import http.client
import os
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

PYTHON = WURZEL.parent / ".venv" / "Scripts" / "python.exe"
if not PYTHON.exists():
    PYTHON = WURZEL.parent / ".venv" / "bin" / "python"
if not PYTHON.exists():
    PYTHON = Path(sys.executable)

fehler = []


def pruefe(bedingung, text):
    print(("  ok   " if bedingung else "  FEHL ") + text)
    if not bedingung:
        fehler.append(text)


# --- Validierung ohne Server -------------------------------------------------
print("Validierung")
from app.validation import pruefen  # noqa: E402

VOLL = {
    "vorname": "Petra", "nachname": "Blende", "firma": "Blende & Licht",
    "email": "petra@example.org", "sicherheit": "1",
}

_, meldungen = pruefen(dict(VOLL, kommerziell="nein"))
pruefe(meldungen == {}, "nicht kommerziell reicht ohne Gegenleistung")

_, meldungen = pruefen(dict(VOLL, kommerziell="ja"))
pruefe("gegenleistung" in meldungen, "kommerziell ohne Wahl wird bemaengelt")

_, meldungen = pruefen(dict(VOLL, kommerziell="ja", gegenleistung="bilderspende"))
pruefe("bildrechte" in meldungen, "Bilderspende ohne Zustimmung wird bemaengelt")

werte, meldungen = pruefen(
    dict(VOLL, kommerziell="ja", gegenleistung="bilderspende", bildrechte="1"))
pruefe(meldungen == {}, "Bilderspende mit Zustimmung geht durch")

werte, meldungen = pruefen(dict(VOLL, kommerziell="nein", gegenleistung="gebuehr"))
pruefe(meldungen == {} and werte["gegenleistung"] == "",
       "mitgeschickte Wahl wird bei 'nicht kommerziell' verworfen, nicht bemaengelt")

ohne_haken = {k: v for k, v in VOLL.items() if k != "sicherheit"}
_, meldungen = pruefen(dict(ohne_haken, kommerziell="nein"))
pruefe("sicherheit" in meldungen, "ohne Sicherheitshaken geht nichts")

_, meldungen = pruefen(dict(VOLL, kommerziell="nein", email=""))
pruefe("email" in meldungen, "E-Mail ist Pflicht")

_, meldungen = pruefen(dict(VOLL, kommerziell="nein", firma=""))
pruefe("firma" in meldungen, "Firma ist Pflicht")


# --- Ueber HTTP ---------------------------------------------------------------
def freier_hafen():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


verzeichnis = Path(tempfile.mkdtemp(prefix="presse-test-"))
db = verzeichnis / "presse.db"
hafen = freier_hafen()

prozess = subprocess.Popen(
    [str(PYTHON), "-m", "app"],
    cwd=str(WURZEL),
    env={**os.environ, "DB_PATH": str(db), "BIND": f"127.0.0.1:{hafen}",
         "APP_SECRET_KEY": "test", "SMTP_HOST": "", "MAIL_FROM": "",
         "BADGES_GESAMT": "3", "PYTHONIOENCODING": "utf-8"},
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)


def zeilen(sql, *parameter):
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    try:
        return con.execute(sql, parameter).fetchall()
    finally:
        con.close()


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
        koerper = urllib.parse.urlencode(daten or {}, encoding="utf-8") if daten else None
        kopf = {"Content-Type": "application/x-www-form-urlencoded"} if koerper else {}
        verbindung.request(methode, pfad, body=koerper, headers=kopf)
        antwort = verbindung.getresponse()
        ergebnis = (antwort.status, antwort.getheader("Location", ""),
                    antwort.read().decode("utf-8"))
        verbindung.close()
        return ergebnis

    print("Formular")
    status, _, seite = anfrage("GET", "/")
    pruefe(status == 200, "Formular laedt")
    for feld in ("vorname", "nachname", "firma", "email", "telefon",
                 "kommerziell", "gegenleistung", "bildrechte", "sicherheit"):
        pruefe('name="' + feld + '"' in seite, "Feld " + feld + " ist da")
    pruefe("20 EUR" in seite, "die Gebuehr steht aus der Konfiguration im Text")
    pruefe("Sturzzonen" in seite, "der Sicherheitshinweis steht im Formular")
    pruefe("Social Media, Print und Merch" in seite, "die Bildrechte stehen im Formular")
    pruefe("nur-kommerziell" in seite and "nur-bilderspende" in seite,
           "die bedingten Bloecke sind markiert")
    pruefe("<script" not in seite, "das Formular kommt ohne JavaScript aus")

    print("Absenden")
    status, ort, _ = anfrage("POST", "/", dict(VOLL, kommerziell="nein"))
    pruefe(status == 303 and "nr=1" in ort, "nicht kommerziell wird angenommen: " + ort)
    pruefe("art=" not in ort, "und traegt keine Gegenleistung mit")

    eintrag = zeilen("SELECT * FROM anmeldung WHERE id = 1")[0]
    pruefe(eintrag["kommerziell"] == 0, "kommerziell ist 0")
    pruefe(eintrag["gegenleistung"] is None, "keine Gegenleistung gespeichert")
    pruefe(bool(eintrag["sicherheit_ok_am"]), "Zeitpunkt der Sicherheitsbestaetigung steht")
    pruefe(eintrag["bildrechte_ok_am"] is None, "keine Bildrechte ohne Bilderspende")
    pruefe(eintrag["status"] == "neu", "Status ist neu")

    status, ort, _ = anfrage("POST", "/", dict(VOLL, kommerziell="ja", gegenleistung="gebuehr"))
    pruefe("art=gebuehr" in ort, "Gebuehr wird an die Dankeseite gereicht")
    eintrag = zeilen("SELECT * FROM anmeldung WHERE id = 2")[0]
    pruefe(eintrag["kommerziell"] == 1 and eintrag["gegenleistung"] == "gebuehr",
           "Gebuehr ist gespeichert")
    pruefe(eintrag["bildrechte_ok_am"] is None, "bei Gebuehr keine Bildrechte")

    status, ort, _ = anfrage("POST", "/", dict(
        VOLL, kommerziell="ja", gegenleistung="bilderspende", bildrechte="1"))
    eintrag = zeilen("SELECT * FROM anmeldung WHERE id = 3")[0]
    pruefe(eintrag["gegenleistung"] == "bilderspende", "Bilderspende ist gespeichert")
    pruefe(bool(eintrag["bildrechte_ok_am"]), "Zustimmung zu den Bildrechten ist vermerkt")

    print("Abgewiesen wird")
    status, _, text = anfrage("POST", "/", dict(VOLL, kommerziell="ja"))
    pruefe(status == 422 and "eine der beiden Möglichkeiten" in text,
           "kommerziell ohne Wahl")
    status, _, text = anfrage("POST", "/", dict(VOLL, kommerziell="ja",
                                                gegenleistung="bilderspende"))
    pruefe(status == 422 and "Zustimmung zur Nutzung" in text,
           "Bilderspende ohne Zustimmung")
    status, _, text = anfrage("POST", "/", {k: v for k, v in VOLL.items()
                                            if k != "sicherheit"} | {"kommerziell": "nein"})
    pruefe(status == 422 and "Sicherheitshinweis" in text, "ohne Sicherheitshaken")
    pruefe(len(zeilen("SELECT id FROM anmeldung")) == 3, "nichts davon wurde gespeichert")

    print("Honeypot")
    status, ort, _ = anfrage("POST", "/", dict(VOLL, kommerziell="nein",
                                               webseite="http://spam.example"))
    pruefe(status == 303, "der Bot sieht eine Bestaetigung")
    pruefe(len(zeilen("SELECT id FROM anmeldung")) == 3, "gespeichert wurde nichts")

    print("Dankeseite")
    status, _, seite = anfrage("GET", "/danke?nr=2&art=gebuehr")
    pruefe(status == 200 and "20 EUR passend mitbringen" in seite,
           "bei Gebuehr steht der Zahlungshinweis da")
    _, _, seite = anfrage("GET", "/danke?nr=3&art=bilderspende")
    pruefe("Bilderspende gewählt" in seite, "bei Bilderspende steht der Hinweis dazu")
    pruefe("passend mitbringen" not in seite, "und kein Zahlungshinweis")
    _, _, seite = anfrage("GET", "/danke?nr=1")
    pruefe("passend mitbringen" not in seite and "Bilderspende gewählt" not in seite,
           "ohne Gegenleistung keines von beidem")
    _, _, seite = anfrage("GET", "/danke?nr=<script>&art=quatsch")
    pruefe("<script>" not in seite, "Unfug in den Parametern wird nicht eingebaut")
    pruefe("Orga-Büro" in seite, "der Abholort steht auf der Dankeseite")

    print("Badge-Obergrenze")
    _, _, seite = anfrage("GET", "/")
    pruefe("rechnerisch vergeben" in seite,
           "bei BADGES_GESAMT=3 und drei Anmeldungen wird gewarnt")
    status, ort, _ = anfrage("POST", "/", dict(VOLL, kommerziell="nein"))
    pruefe(status == 303, "angenommen wird trotzdem weiter")
    pruefe(len(zeilen("SELECT id FROM anmeldung")) == 4, "und gespeichert auch")

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
print("Wegwerf-Datenbank lag in " + str(verzeichnis))
sys.exit(1 if fehler else 0)
