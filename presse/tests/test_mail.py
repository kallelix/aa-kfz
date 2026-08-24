"""Mailvorlagen und Bilderspende-Nachverfolgung (Schritte 6 und 7).

    python presse/tests/test_mail.py

Startet den Server selbst. Es geht nichts nach draußen – ohne SMTP_HOST
sammeln sich die Mails in der Warteschlange.
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


verzeichnis = Path(tempfile.mkdtemp(prefix="presse-mail-"))
db = verzeichnis / "presse.db"
hafen = freier_hafen()

prozess = subprocess.Popen(
    [str(PYTHON), "-m", "app"],
    cwd=str(WURZEL),
    env={**os.environ, "DB_PATH": str(db), "BIND": f"127.0.0.1:{hafen}",
         "ADMIN_PASSWORD_HASH": HASH, "APP_SECRET_KEY": "test-schluessel",
         "COOKIE_SECURE": "0", "SMTP_HOST": "", "MAIL_FROM": "",
         "KONTAKT_MAIL": "presse@example.de",
         "BILDER_ABGABE": "https://wolke.example.de/abfahrt",
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

    def anmelden(vorname, nachname, komm, gegen):
        daten = {"vorname": vorname, "nachname": nachname, "firma": "Foto " + nachname,
                 "email": vorname.lower() + "@example.org", "sicherheit": "1",
                 "kommerziell": komm}
        if gegen:
            daten["gegenleistung"] = gegen
        if gegen == "bilderspende":
            daten["bildrechte"] = "1"
        anfrage("POST", "/", daten)

    print("Bestaetigungsmail beim Absenden")
    anmelden("Petra", "Gebuehr", "ja", "gebuehr")
    mails = zeilen("SELECT * FROM mail_out WHERE anmeldung_id = 1")
    pruefe(len(mails) == 1 and mails[0]["typ"] == "eingang",
           "die Bestaetigung wird eingereiht")
    pruefe(mails[0]["gesendet_am"] is None, "und nicht im Request verschickt")
    pruefe(mails[0]["empfaenger"] == "petra@example.org", "Empfaenger stimmt")

    body = mails[0]["body"]
    pruefe("20 EUR Gebühr" in body, "Variante Gebuehr nennt den Betrag")
    pruefe("passend mitbringen" in body, "und den Zahlungshinweis")
    pruefe("Sturzzonen" in body, "der Sicherheitshinweis steht in der Mail")
    pruefe("Orga-Büro" in body, "der Abholort steht drin")
    pruefe("presse@example.de" in body, "der Ansprechpartner steht drunter")
    pruefe("Bilder als Spende" not in body, "und nichts von der anderen Variante")
    pruefe("<" not in body or "<html" not in body.lower(), "reiner Text")

    anmelden("Sven", "Spende", "ja", "bilderspende")
    body = zeilen("SELECT body FROM mail_out WHERE anmeldung_id = 2")[0]["body"]
    pruefe("10 Bilder als Spende" in body, "Variante Bilderspende nennt den Umfang")
    pruefe("Social Media, Print und Merch" in body, "und die Nutzungsbedingungen")
    pruefe("passend mitbringen" not in body, "aber keinen Zahlungshinweis")

    anmelden("Anna", "Hobby", "nein", "")
    body = zeilen("SELECT body FROM mail_out WHERE anmeldung_id = 3")[0]["body"]
    pruefe("nicht kommerziell" in body, "dritte Variante nennt die Nutzung")
    pruefe("keine Gebühr" in body, "und dass nichts zu zahlen ist")

    print("Verlinkung in der Bestaetigung")
    anfrage("POST", "/", {
        "vorname": "Timo", "nachname": "Verlinkt", "firma": "Verlinkt Media",
        "email": "timo@example.org", "sicherheit": "1", "kommerziell": "ja",
        "gegenleistung": "bilderspende", "bildrechte": "1",
        "verlinkung": "1", "social_media": "@timo.verlinkt"})
    body = zeilen("SELECT body FROM mail_out WHERE anmeldung_id = 4")[0]["body"]
    pruefe("Verlinkung:    @timo.verlinkt" in body,
           "das Profil steht in der Uebersicht")
    pruefe("verlinken wir dich als @timo.verlinkt" in body,
           "und die Zusage steht im Text")

    body = zeilen("SELECT body FROM mail_out WHERE anmeldung_id = 2")[0]["body"]
    pruefe("verlinken wir dich" not in body,
           "ohne Wunsch wird nichts versprochen")

    print("Bilder ausstehend")
    anfrage("POST", "/admin/login",
            {"passwort": "test-passwort-123", "kuerzel": "KK", "weiter": "/admin"})
    _, _, seite = anfrage("GET", "/admin")
    CSRF = re.search(r'name="csrf" value="([^"]+)"', seite).group(1)

    status, _, bilder = anfrage("GET", "/admin/bilder")
    pruefe(status == 200, "die Ansicht laedt")
    pruefe("Nichts offen" in bilder,
           "ohne abgeholtes Badge steht noch niemand drauf")

    anfrage("POST", "/admin/anmeldung/2/badge", {"csrf": CSRF})
    _, _, bilder = anfrage("GET", "/admin/bilder")
    pruefe("Spende" in bilder, "nach der Badge-Ausgabe steht er drauf")
    pruefe("noch nicht" in bilder, "und ist als noch nicht erinnert markiert")

    anfrage("POST", "/admin/anmeldung/1/badge", {"csrf": CSRF})
    _, _, bilder = anfrage("GET", "/admin/bilder")
    pruefe("Gebuehr" not in bilder, "wer die Gebuehr gewaehlt hat, steht nicht drauf")

    print("Erinnern")
    status, ort, _ = anfrage("POST", "/admin/anmeldung/2/erinnerung", {"csrf": CSRF})
    pruefe("hinweis=erinnert" in ort, "Erinnerung meldet Erfolg")
    mails = zeilen("SELECT * FROM mail_out WHERE anmeldung_id = 2 AND typ = 'erinnerung'")
    pruefe(len(mails) == 1, "die Erinnerung ist eingereiht")
    pruefe("wolke.example.de" in mails[0]["body"],
           "BILDER_ABGABE steht in der Mail")
    pruefe("10 Bilder" in mails[0]["body"], "der Umfang steht drin")
    pruefe(bool(zeilen("SELECT erinnerung_am FROM anmeldung WHERE id = 2")[0][0]),
           "der Zeitpunkt ist vermerkt")

    status, ort, _ = anfrage("POST", "/admin/anmeldung/1/erinnerung", {"csrf": CSRF})
    pruefe("hinweis=nichts" in ort, "wer keine Bilderspende gewaehlt hat, wird nicht erinnert")
    pruefe(len(zeilen("SELECT id FROM mail_out WHERE anmeldung_id = 1 AND typ = 'erinnerung'")) == 0,
           "und bekommt auch keine Mail")

    print("Bilder erhalten")
    status, ort, _ = anfrage("POST", "/admin/anmeldung/2/bilder", {"csrf": CSRF})
    pruefe("hinweis=bilder" in ort, "Haken meldet Erfolg")
    _, _, bilder = anfrage("GET", "/admin/bilder")
    pruefe("Nichts offen" in bilder, "danach ist die Liste leer")

    status, ort, _ = anfrage("POST", "/admin/anmeldung/2/erinnerung", {"csrf": CSRF})
    pruefe("hinweis=nichts" in ort, "wer geliefert hat, wird nicht mehr erinnert")

    anfrage("POST", "/admin/anmeldung/2/bilder", {"csrf": CSRF, "erhalten": "0"})
    pruefe(zeilen("SELECT bilder_erhalten_am FROM anmeldung WHERE id = 2")[0][0] is None,
           "Haken laesst sich zuruecknehmen")

    print("Sammelerinnerung")
    anmelden("Uwe", "Zweispende", "ja", "bilderspende")
    anfrage("POST", "/admin/anmeldung/5/badge", {"csrf": CSRF})
    status, ort, _ = anfrage("POST", "/admin/erinnerungen", {"csrf": CSRF})
    pruefe("anzahl=2" in ort, "beide offenen wurden erinnert: " + ort)
    pruefe(len(zeilen("SELECT id FROM mail_out WHERE typ = 'erinnerung'")) == 3,
           "insgesamt drei Erinnerungen in der Schlange")

    anfrage("POST", "/admin/anmeldung/2/bilder", {"csrf": CSRF})
    anfrage("POST", "/admin/anmeldung/5/bilder", {"csrf": CSRF})
    anfrage("POST", "/admin/anmeldung/4/bilder", {"csrf": CSRF})
    status, ort, _ = anfrage("POST", "/admin/erinnerungen", {"csrf": CSRF})
    pruefe("anzahl=0" in ort, "ohne Offene wird nichts verschickt")

    print("CSRF")
    for pfad in ("/admin/anmeldung/2/erinnerung", "/admin/anmeldung/2/bilder",
                 "/admin/erinnerungen"):
        status, _, _ = anfrage("POST", pfad, {"csrf": "falsch"})
        pruefe(status == 400, pfad + " ohne CSRF-Token -> 400")

    print("Nichts ist rausgegangen")
    offen = zeilen("SELECT COUNT(*) FROM mail_out WHERE gesendet_am IS NULL")[0][0]
    gesamt = zeilen("SELECT COUNT(*) FROM mail_out")[0][0]
    pruefe(offen == gesamt and gesamt > 0,
           "ohne SMTP_HOST warten alle " + str(gesamt) + " Mails in der Schlange")

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
