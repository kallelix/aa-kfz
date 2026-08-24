"""CSV-Export der Presse-Akkreditierung (Schritt 8).

    python presse/tests/test_export.py
"""

import csv
import http.client
import io
import os
import re
import socket
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

HASH = "$2b$12$jWSkTX2jwE2Afm795IqpuuLOLzUGEL8Qruhfa67JQvzJd4fn.6fnm"
TRENNER = ";"

fehler = []


def pruefe(bedingung, text):
    print(("  ok   " if bedingung else "  FEHL ") + text)
    if not bedingung:
        fehler.append(text)


def freier_hafen():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


verzeichnis = Path(tempfile.mkdtemp(prefix="presse-csv-"))
hafen = freier_hafen()

prozess = subprocess.Popen(
    [str(PYTHON), "-m", "app"],
    cwd=str(WURZEL),
    env={**os.environ, "DB_PATH": str(verzeichnis / "presse.db"),
         "BIND": f"127.0.0.1:{hafen}", "ADMIN_PASSWORD_HASH": HASH,
         "APP_SECRET_KEY": "test-schluessel", "COOKIE_SECURE": "0",
         "SMTP_HOST": "", "MAIL_FROM": "", "PYTHONIOENCODING": "utf-8"},
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

    def anfrage(methode, pfad, daten=None, roh=False):
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
        inhalt = antwort.read()
        ergebnis = (antwort.status, antwort.headers,
                    inhalt if roh else inhalt.decode("utf-8"))
        verbindung.close()
        return ergebnis

    def tabelle(text):
        return list(csv.reader(io.StringIO(text, newline=""), delimiter=TRENNER))

    print("Ohne Anmeldung")
    status, kopf, _ = anfrage("GET", "/admin/export.csv")
    pruefe(status == 303 and kopf.get("Location", "").startswith("/admin/login"),
           "Export ohne Anmeldung fuehrt zur Anmeldeseite")

    # Drei Anmeldungen, eine davon mit Zeichen, die CSV gern zerlegen.
    for daten in (
        {"vorname": "Petra", "nachname": "Gebuehr", "firma": "Foto GmbH",
         "email": "petra@example.org", "kommerziell": "ja",
         "gegenleistung": "gebuehr", "sicherheit": "1"},
        {"vorname": "Sven", "nachname": "Öhler; Sohn",
         "firma": 'Presse "Vor Ort"', "email": "sven@example.org",
         "kommerziell": "ja", "gegenleistung": "bilderspende",
         "bildrechte": "1", "sicherheit": "1",
         "bemerkung": "Zeile eins\nZeile zwei; mit Trenner"},
        {"vorname": "Anna", "nachname": "Hobby", "firma": "privat",
         "email": "anna@example.org", "kommerziell": "nein", "sicherheit": "1"},
    ):
        anfrage("POST", "/", daten)

    anfrage("POST", "/admin/login",
            {"passwort": "test-passwort-123", "kuerzel": "KK", "weiter": "/admin"})

    print("Grundform")
    status, kopf, rohdaten = anfrage("GET", "/admin/export.csv", roh=True)
    pruefe(status == 200, "Export liefert 200")
    pruefe(kopf.get("content-type", "").startswith("text/csv"), "Content-Type ist text/csv")
    verfuegung = kopf.get("content-disposition", "")
    pruefe("attachment" in verfuegung and "presse-" in verfuegung,
           "als Download angeboten: " + verfuegung)
    pruefe(rohdaten.startswith(b"\xef\xbb\xbf"), "beginnt mit UTF-8-BOM")

    text = rohdaten.decode("utf-8-sig")
    pruefe("\r\n" in text, "Zeilenende ist CRLF")
    zeilen = tabelle(text)
    kopfzeile = zeilen[0]
    pruefe(kopfzeile[0] == "Nr." and "Akkreditierung" in kopfzeile,
           "Kopfzeile stimmt: " + str(kopfzeile[:5]))
    pruefe(all("IP" not in feld for feld in kopfzeile), "keine IP-Spalte")
    pruefe(len(zeilen) == 4, "drei Anmeldungen plus Kopfzeile")

    print("Inhalte")
    spalten = {name: wert for name, wert in zip(kopfzeile, zeilen[1])}
    # Neueste zuerst, also steht Anna oben.
    pruefe(spalten["Name"] == "Hobby", "Sortierung neueste zuerst: " + spalten["Name"])
    pruefe(spalten["Kommerziell"] == "nein", "kommerziell wird als ja/nein ausgegeben")
    pruefe(spalten["Akkreditierung"] == "keine", "ohne Gegenleistung steht 'keine'")

    nach_name = {z[4]: dict(zip(kopfzeile, z)) for z in zeilen[1:]}
    pruefe(nach_name["Gebuehr"]["Akkreditierung"] == "20 EUR Gebühr",
           "Gebuehr im Klartext: " + nach_name["Gebuehr"]["Akkreditierung"])
    pruefe("Bilderspende" in nach_name["Öhler; Sohn"]["Akkreditierung"],
           "Bilderspende im Klartext")
    pruefe(bool(nach_name["Gebuehr"]["Sicherheitshinweis bestätigt am"]),
           "der Zeitstempel der Sicherheitszustimmung ist dabei")
    pruefe(bool(nach_name["Öhler; Sohn"]["Bildrechte zugestimmt am"]),
           "und bei Bilderspende der der Bildrechte")
    pruefe(nach_name["Hobby"]["Bildrechte zugestimmt am"] == "",
           "ohne Bilderspende bleibt die Spalte leer")

    print("Sonderzeichen")
    heikel = nach_name["Öhler; Sohn"]
    pruefe(heikel["Name"] == "Öhler; Sohn", "Semikolon im Feld bleibt heil")
    pruefe(heikel["Firma"] == 'Presse "Vor Ort"', "Anfuehrungszeichen bleiben heil")
    pruefe(heikel["Bemerkung"] == "Zeile eins\nZeile zwei; mit Trenner",
           "Zeilenumbruch bleibt heil: " + repr(heikel["Bemerkung"]))

    print("Filter")
    _, _, text = anfrage("GET", "/admin/export.csv?gegenleistung=gebuehr")
    zeilen = tabelle(text.lstrip("﻿"))
    pruefe(len(zeilen) == 2 and zeilen[1][4] == "Gebuehr", "Filter Gebuehr greift")

    _, _, text = anfrage("GET", "/admin/export.csv?gegenleistung=keine")
    zeilen = tabelle(text.lstrip("﻿"))
    pruefe(len(zeilen) == 2 and zeilen[1][4] == "Hobby",
           "Filter 'nicht kommerziell' greift")

    _, _, text = anfrage("GET", "/admin/export.csv?suche=" + urllib.parse.quote("öhler"))
    zeilen = tabelle(text.lstrip("﻿"))
    pruefe(len(zeilen) == 2, "Suche greift, auch mit Umlaut")

    _, _, text = anfrage("GET", "/admin/export.csv?suche=gibtesnicht")
    pruefe(len(tabelle(text.lstrip("﻿"))) == 1, "leere Auswahl: nur die Kopfzeile")

    _, _, text = anfrage(
        "GET", "/admin/export.csv?sortierung=" + urllib.parse.quote("id; DROP TABLE anmeldung--"))
    pruefe(len(tabelle(text.lstrip("﻿"))) == 4,
           "unbekannte Sortierung richtet keinen Schaden an")

    print("Verweis in der Liste")
    _, _, liste = anfrage("GET", "/admin?gegenleistung=gebuehr")
    pruefe("/admin/export.csv?status=&amp;gegenleistung=gebuehr" in liste,
           "die Liste verlinkt den Export mit den aktuellen Filtern")

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
