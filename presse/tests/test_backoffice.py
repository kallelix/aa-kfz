"""Backoffice und Abholliste der Presse-Akkreditierung (Schritte 3 bis 5).

    python presse/tests/test_backoffice.py

Startet den Server selbst mit eigener Wegwerf-Datenbank.
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

PYTHON = WURZEL.parent / ".venv" / "Scripts" / "python.exe"
if not PYTHON.exists():
    PYTHON = WURZEL.parent / ".venv" / "bin" / "python"
if not PYTHON.exists():
    PYTHON = Path(sys.executable)

# bcrypt-Hash von "test-passwort-123"
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


verzeichnis = Path(tempfile.mkdtemp(prefix="presse-bo-"))
db = verzeichnis / "presse.db"
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

    print("Zugriffsschutz")
    for pfad in ("/admin", "/admin/abholung", "/admin/anmeldung/1"):
        status, ort, _ = anfrage("GET", pfad)
        pruefe(status == 303 and ort.startswith("/admin/login"),
               pfad + " verlangt Anmeldung")

    # Drei Anmeldungen ueber das oeffentliche Formular anlegen.
    LEUTE = [
        ("Petra", "Blende", "Blende & Licht", "ja", "gebuehr"),
        ("Sven", "Öhler", "Freier Journalist", "ja", "bilderspende"),
        ("Anna", "Zoom", "Hobby", "nein", ""),
    ]
    for vorname, nachname, firma, komm, gegen in LEUTE:
        daten = {"vorname": vorname, "nachname": nachname, "firma": firma,
                 "email": vorname.lower() + "@example.org", "sicherheit": "1",
                 "kommerziell": komm}
        if gegen:
            daten["gegenleistung"] = gegen
        if gegen == "bilderspende":
            daten["bildrechte"] = "1"
        anfrage("POST", "/", daten)
    pruefe(len(zeilen("SELECT id FROM anmeldung")) == 3, "drei Anmeldungen angelegt")

    print("Anmelden")
    status, ort, _ = anfrage("POST", "/admin/login",
                             {"passwort": "falsch", "weiter": "/admin"})
    pruefe(status == 401, "falsches Passwort wird abgewiesen")
    anfrage("POST", "/admin/login",
            {"passwort": "test-passwort-123", "kuerzel": "KK", "weiter": "/admin"})
    status, _, liste = anfrage("GET", "/admin")
    pruefe(status == 200, "Liste laedt nach der Anmeldung")
    CSRF = re.search(r'name="csrf" value="([^"]+)"', liste).group(1)

    print("Liste")
    pruefe("Blende" in liste and "Öhler" in liste and "Zoom" in liste,
           "alle drei stehen drin")
    pruefe("3 Anmeldungen angezeigt" in liste, "Trefferzahl stimmt")
    pruefe("nicht kommerziell" in liste, "die nicht-kommerzielle ist als solche erkennbar")

    _, _, gefiltert = anfrage("GET", "/admin?gegenleistung=gebuehr")
    pruefe("Blende" in gefiltert and "Zoom" not in gefiltert, "Filter Gebuehr greift")
    _, _, gefiltert = anfrage("GET", "/admin?gegenleistung=keine")
    pruefe("Zoom" in gefiltert and "Blende" not in gefiltert,
           "Filter 'nicht kommerziell' greift")
    _, _, gefiltert = anfrage("GET", "/admin?suche=" + urllib.parse.quote("öhler"))
    pruefe("Öhler" in gefiltert and "Blende" not in gefiltert,
           "Suche findet Umlaute unabhaengig von Gross/Klein")

    print("Detailansicht und Korrektur")
    status, _, detail = anfrage("GET", "/admin/anmeldung/1")
    pruefe(status == 200 and "Blende" in detail, "Detailansicht laedt")
    pruefe("Sicherheitshinweis bestätigt" in detail,
           "der Zeitpunkt der Zustimmung steht im Verlauf")

    status, ort, _ = anfrage("POST", "/admin/anmeldung/1/speichern", {
        "csrf": CSRF, "vorname": "Petra", "nachname": "Blende-Licht",
        "firma": "Blende & Licht GmbH", "email": "petra@example.org",
        "kommerziell": "ja", "gegenleistung": "gebuehr"})
    pruefe("hinweis=gespeichert" in ort, "Korrektur wird gespeichert")
    eintrag = zeilen("SELECT * FROM anmeldung WHERE id = 1")[0]
    pruefe(eintrag["nachname"] == "Blende-Licht", "der neue Name steht drin")

    # Im Backoffice sind die Zustimmungs-Haekchen keine Pflicht.
    pruefe(bool(eintrag["sicherheit_ok_am"]),
           "der Zeitstempel der Sicherheitszustimmung bleibt unangetastet")

    status, _, text = anfrage("POST", "/admin/anmeldung/1/speichern", {
        "csrf": CSRF, "vorname": "", "nachname": "Blende", "firma": "X",
        "email": "petra@example.org", "kommerziell": "nein"})
    pruefe(status == 422 and "Vorname bitte" in text, "leerer Vorname wird abgewiesen")

    print("Umstellen auf Bilderspende vermerkt die Bildrechte")
    status, _, _ = anfrage("POST", "/admin/anmeldung/1/speichern", {
        "csrf": CSRF, "vorname": "Petra", "nachname": "Blende-Licht",
        "firma": "Blende & Licht GmbH", "email": "petra@example.org",
        "kommerziell": "ja", "gegenleistung": "bilderspende"})
    pruefe(status == 303, "das Umstellen geht ohne Serverfehler durch: " + str(status))
    eintrag = zeilen("SELECT * FROM anmeldung WHERE id = 1")[0]
    pruefe(bool(eintrag["bildrechte_ok_am"]), "Zeitstempel wurde gesetzt")
    anfrage("POST", "/admin/anmeldung/1/speichern", {
        "csrf": CSRF, "vorname": "Petra", "nachname": "Blende-Licht",
        "firma": "Blende & Licht GmbH", "email": "petra@example.org",
        "kommerziell": "ja", "gegenleistung": "gebuehr"})
    eintrag = zeilen("SELECT * FROM anmeldung WHERE id = 1")[0]
    pruefe(eintrag["bildrechte_ok_am"] is None, "und beim Zurueckstellen wieder geraeumt")

    print("Abholliste")
    status, _, abholung = anfrage("GET", "/admin/abholung")
    pruefe(status == 200, "Abholliste laedt")
    pruefe(abholung.count("<tr data-suche=") == 3, "alle drei stehen drauf")
    pruefe('data-suche="petra blende-licht blende &amp; licht gmbh"' in abholung,
           "der Suchtext ist kleingeschrieben und enthaelt die Firma")
    pruefe("/static/liste.js" in abholung, "das Filterskript ist eingebunden")
    pruefe(abholung.count('class="sortknopf"') == 3, "drei Spalten sind sortierbar")

    print("Badge ausgeben")
    status, ort, _ = anfrage("POST", "/admin/anmeldung/1/badge", {"csrf": CSRF})
    pruefe("hinweis=badge" in ort, "Ausgabe meldet Erfolg")
    eintrag = zeilen("SELECT * FROM anmeldung WHERE id = 1")[0]
    pruefe(eintrag["status"] == "ausgegeben", "Status ist ausgegeben")
    pruefe(bool(eintrag["badge_am"]), "Zeitpunkt steht")
    pruefe(eintrag["badge_durch"] == "KK", "das Kuerzel aus der Sitzung steht dabei")

    status, ort, _ = anfrage("POST", "/admin/anmeldung/1/badge", {"csrf": CSRF})
    pruefe("hinweis=nichts" in ort, "zweimal ausgeben aendert nichts")

    status, ort, _ = anfrage("POST", "/admin/anmeldung/1/badge",
                             {"csrf": CSRF, "ausgeben": "0"})
    pruefe("hinweis=badge_zurueck" in ort, "zuruecknehmen geht")
    eintrag = zeilen("SELECT * FROM anmeldung WHERE id = 1")[0]
    pruefe(eintrag["status"] == "neu" and eintrag["badge_am"] is None,
           "Status und Zeitpunkt sind geraeumt")

    print("Gebuehr")
    status, ort, _ = anfrage("POST", "/admin/anmeldung/1/gebuehr", {"csrf": CSRF})
    pruefe("hinweis=gebuehr" in ort, "Gebuehr kassiert")
    pruefe(bool(zeilen("SELECT gebuehr_bezahlt_am FROM anmeldung WHERE id = 1")[0][0]),
           "Zeitpunkt steht")
    anfrage("POST", "/admin/anmeldung/1/gebuehr", {"csrf": CSRF, "bezahlt": "0"})
    pruefe(zeilen("SELECT gebuehr_bezahlt_am FROM anmeldung WHERE id = 1")[0][0] is None,
           "zuruecknehmen geht")

    status, ort, _ = anfrage("POST", "/admin/anmeldung/3/gebuehr", {"csrf": CSRF})
    pruefe("hinweis=nichts" in ort,
           "wer keine Gebuehr gewaehlt hat, kann auch keine bezahlen")

    print("CSRF")
    for pfad, daten in (
        ("/admin/anmeldung/1/badge", {"csrf": "falsch"}),
        ("/admin/anmeldung/1/gebuehr", {"csrf": "falsch"}),
        ("/admin/anmeldung/1/loeschen", {"csrf": "falsch"}),
        ("/admin/anmeldung/1/speichern", {"csrf": "falsch", "vorname": "X"}),
    ):
        status, _, _ = anfrage("POST", pfad, daten)
        pruefe(status == 400, pfad + " ohne CSRF-Token -> 400")
    pruefe(len(zeilen("SELECT id FROM anmeldung")) == 3, "nichts davon hat gewirkt")

    print("Unbekannte Nummer")
    for pfad in ("/admin/anmeldung/999", ):
        status, _, _ = anfrage("GET", pfad)
        pruefe(status == 404, pfad + " -> 404")
    for pfad in ("/admin/anmeldung/999/badge", "/admin/anmeldung/999/gebuehr"):
        status, _, _ = anfrage("POST", pfad, {"csrf": CSRF})
        pruefe(status == 404, pfad + " -> 404")

    print("Loeschen")
    status, ort, _ = anfrage("POST", "/admin/anmeldung/3/loeschen", {"csrf": CSRF})
    pruefe("hinweis=geloescht" in ort, "Loeschen meldet Erfolg")
    pruefe(len(zeilen("SELECT id FROM anmeldung")) == 2, "der Datensatz ist weg")

    print("Abmelden")
    anfrage("POST", "/admin/logout", {"csrf": CSRF})
    status, ort, _ = anfrage("GET", "/admin")
    pruefe(status == 303 and ort.startswith("/admin/login"), "danach ist wieder zu")

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
