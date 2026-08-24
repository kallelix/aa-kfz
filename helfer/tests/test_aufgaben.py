"""Aufgabenplan und Programmpunkte von Hand (Schritt 5).

    python helfer/tests/test_aufgaben.py

Startet den Server selbst. Prüft vor allem den Konfliktschutz: dass zwei
Leute, die gleichzeitig am selben Eintrag arbeiten, sich nicht gegenseitig
überschreiben, ohne es zu merken.
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


# --- Der reine Teil: Prüfen und Umformen ----------------------------------

os.environ["TAGE"] = "2026-08-28,2026-08-29,2026-08-30"
verzeichnis = Path(tempfile.mkdtemp(prefix="helfer-aufgaben-"))
db_pfad = verzeichnis / "helfer.db"
os.environ["DB_PATH"] = str(db_pfad)

from app import db, eintraege  # noqa: E402

print("Uhrzeiten lesen")
for roh, erwartet in (("08:30", "08:30"), ("8.30", "08:30"), ("8:5", "08:05"),
                      ("", ""), ("25:00", None), ("quatsch", None),
                      ("23:59", "23:59"), ("12", None)):
    pruefe(eintraege._uhrzeit(roh) == erwartet,
           repr(roh) + " -> " + repr(eintraege._uhrzeit(roh)))

print("Aufgabe prüfen")
werte, f = eintraege.pruefen({"titel": "Zelt aufbauen", "datum": "2026-08-27",
                              "beginn": "08:00", "ende": "12:00",
                              "phase": "aufbau"})
pruefe(not f, "eine vollständige Aufgabe geht durch")
pruefe(werte["beginn"] == "2026-08-27 08:00", "Beginn wird zusammengesetzt")
pruefe(werte["ende"] == "2026-08-27 12:00", "Ende auch")

werte, f = eintraege.pruefen({"titel": "Nachtwache", "datum": "2026-08-29",
                              "beginn": "22:00", "ende": "02:00"})
pruefe(werte["ende"] == "2026-08-30 02:00",
       "über Mitternacht liegt das Ende am Folgetag: " + str(werte["ende"]))

werte, f = eintraege.pruefen({"titel": "Pokale besorgen"})
pruefe(not f and werte["datum"] is None,
       "ohne Datum ist in Ordnung – das ist der Pool")

_, f = eintraege.pruefen({"titel": ""})
pruefe("titel" in f, "ohne Bezeichnung nicht")
_, f = eintraege.pruefen({"titel": "X", "beginn": "08:00"})
pruefe("datum" in f, "eine Uhrzeit ohne Tag wäre ortlos")
_, f = eintraege.pruefen({"titel": "X", "datum": "2026-08-29", "ende": "12:00"})
pruefe("beginn" in f, "ein Ende ohne Anfang ergibt keine Spanne")
_, f = eintraege.pruefen({"titel": "X", "datum": "gestern"})
pruefe("datum" in f, "ein unlesbares Datum wird gemeldet")

werte, _ = eintraege.pruefen({"titel": "X", "phase": "erfunden",
                              "status": "erfunden"})
pruefe(werte["phase"] == "event" and werte["status"] == "offen",
       "unbekannte Phase und unbekannter Status fallen auf die Vorgabe zurück")

print("Programmpunkt prüfen")
werte, f = eintraege.programm_pruefen({"titel": "Rennlauf", "beginn": "11:30"},
                                      "2026-08-30")
pruefe(werte["ende"] is None and werte["zeit_roh"] == "ab 11:30 Uhr",
       "ohne Ende bleibt es offen, der Wortlaut wird mitgeführt")
werte, _ = eintraege.programm_pruefen(
    {"titel": "Training", "beginn": "10:00", "ende": "12:00"}, "2026-08-30")
pruefe(werte["zeit_roh"] == "10:00 - 12:00 Uhr",
       "mit Ende steht die Spanne im Wortlaut")

# --- Der Rest: über HTTP ---------------------------------------------------

db.init()
hafen = freier_hafen()

prozess = subprocess.Popen(
    [str(PYTHON), "-m", "app"],
    cwd=str(WURZEL),
    env={**os.environ, "DB_PATH": str(db_pfad), "BIND": f"127.0.0.1:{hafen}",
         "ADMIN_PASSWORD_HASH": HASH, "APP_SECRET_KEY": "test-schluessel",
         "COOKIE_SECURE": "0", "ZEITPLAN_SERIEN": "",
         "PYTHONIOENCODING": "utf-8"},
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)


def zeilen(sql, *parameter):
    con = sqlite3.connect(db_pfad)
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
        koerper = urllib.parse.urlencode(daten, doseq=True).encode() if daten else None
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

    print("Ohne Anmeldung")
    for pfad in ("/admin/aufgaben", "/admin/aufgabe/neu", "/admin/aufgabe/1"):
        status, ort, _ = anfrage("GET", pfad)
        pruefe(status == 303 and ort.startswith("/admin/login"),
               pfad + " führt zur Anmeldung")

    anfrage("POST", "/admin/login",
            {"passwort": "test-passwort-123", "kuerzel": "KK",
             "weiter": "/admin"})
    _, _, seite = anfrage("GET", "/admin/aufgaben")
    CSRF = re.search(r'name="csrf" value="([^"]+)"', seite).group(1)
    pruefe("Noch keine Aufgabe erfasst" in seite, "leerer Plan sagt das auch")

    print("Anlegen")
    for titel, datum, von, bis, phase in (
            ("Zelt aufbauen", "2026-08-27", "08:00", "12:00", "aufbau"),
            ("Strom legen", "2026-08-27", "13:00", "16:00", "aufbau"),
            ("Streckenband prüfen", "2026-08-29", "06:00", "07:00", "event"),
            ("Pokale besorgen", "", "", "", "sonstiges")):
        status, ort, _ = anfrage("POST", "/admin/aufgabe/neu", {
            "csrf": CSRF, "titel": titel, "datum": datum, "beginn": von,
            "ende": bis, "phase": phase, "ort": "Zeltplatz",
            "verantwortlich": "Kalle"})
        pruefe(status == 303 and "hinweis=angelegt" in ort, titel)
    pruefe(len(zeilen("SELECT id FROM aufgabe")) == 4, "vier Aufgaben stehen drin")

    status, _, _ = anfrage("POST", "/admin/aufgabe/neu",
                           {"csrf": "falsch", "titel": "Geschmuggelt"})
    pruefe(status == 400, "ohne CSRF-Token wird nichts angelegt")
    pruefe(len(zeilen("SELECT id FROM aufgabe")) == 4, "und nichts geschrieben")

    print("Fehlerhafte Eingabe")
    status, _, seite = anfrage("POST", "/admin/aufgabe/neu",
                               {"csrf": CSRF, "titel": ""})
    pruefe(status == 400 and 'class="fehler"' in seite,
           "ohne Titel kommt das Formular zurück")
    status, _, seite = anfrage("POST", "/admin/aufgabe/neu",
                               {"csrf": CSRF, "titel": "Merken",
                                "notiz": "nicht verlieren", "beginn": "08:00"})
    pruefe("nicht verlieren" in seite,
           "die schon getippten Werte stehen noch im Formular")
    pruefe(len(zeilen("SELECT id FROM aufgabe")) == 4, "nichts wurde angelegt")

    print("Liste")
    _, _, seite = anfrage("GET", "/admin/aufgaben")
    pruefe(seite.count('<tr id="aufgabe-') == 4, "vier Zeilen")
    gruppen = re.findall(r'class="tagestitel">\s*([^<\n]+)', seite)
    pruefe([g.strip() for g in gruppen] == ["Do 27.08.", "Sa 29.08.", "Pool"],
           "nach Tagen gruppiert, der Pool ganz hinten: " + str(gruppen))
    pruefe("Zeltplatz" in seite and "Kalle" in seite, "Ort und Wer stehen drin")

    _, _, seite = anfrage("GET", "/admin/aufgaben?phase=aufbau")
    pruefe(seite.count('<tr id="aufgabe-') == 2, "Filter nach Phase greift")
    _, _, seite = anfrage("GET", "/admin/aufgaben?status=erledigt")
    pruefe(seite.count('<tr id="aufgabe-') == 0, "Filter nach Status greift")
    _, _, seite = anfrage("GET", "/admin/aufgaben?phase=erfunden")
    pruefe(seite.count('<tr id="aufgabe-') == 4,
           "eine erfundene Phase filtert nicht, statt zu scheitern")

    print("Status per Knopf")
    status, ort, _ = anfrage("POST", "/admin/aufgabe/1/status",
                             {"csrf": CSRF, "status": "arbeit"})
    pruefe("hinweis=status" in ort and "#aufgabe-1" in ort,
           "meldet Erfolg und springt zur Zeile: " + ort)
    pruefe(zeilen("SELECT status FROM aufgabe WHERE id = 1")[0][0] == "arbeit",
           "der Status steht in der Datenbank")

    status, ort, _ = anfrage("POST", "/admin/aufgabe/1/status",
                             {"csrf": CSRF, "status": "erfunden"})
    pruefe("hinweis=unbekannt" in ort, "ein erfundener Status wird abgewiesen")
    pruefe(zeilen("SELECT status FROM aufgabe WHERE id = 1")[0][0] == "arbeit",
           "und ändert nichts")

    status, ort, _ = anfrage("POST", "/admin/aufgabe/1/status",
                             {"csrf": CSRF, "status": "erledigt",
                              "f_phase": "aufbau"})
    pruefe("phase=aufbau" in ort, "der Filter überlebt den Statuswechsel")

    print("Konfliktschutz")
    _, _, formular = anfrage("GET", "/admin/aufgabe/2")
    stand = re.search(r'name="version" value="(\d+)"', formular).group(1)
    pruefe(stand == "1", "das Formular trägt die Fassung mit: " + stand)

    felder = {"csrf": CSRF, "titel": "Strom legen (Fassung A)",
              "phase": "aufbau", "status": "offen", "datum": "2026-08-27",
              "beginn": "13:00", "ende": "16:00", "version": stand}
    status, ort, _ = anfrage("POST", "/admin/aufgabe/2", felder)
    pruefe(status == 303 and "hinweis=gespeichert" in ort, "erster speichert")

    # Zweiter Browser, der das Formular vorher geladen hatte.
    felder["titel"] = "Strom legen (Fassung B)"
    status, _, seite = anfrage("POST", "/admin/aufgabe/2", felder)
    pruefe(status == 409, "mit veraltetem Stand gibt es 409, nicht 200")
    pruefe("Jemand anderes war schneller" in seite, "und eine klare Ansage")
    pruefe("Fassung A" in seite, "der jetzt gespeicherte Text wird gezeigt")
    pruefe("Fassung B" in seite, "und die eigene Eingabe bleibt stehen")
    pruefe(zeilen("SELECT titel FROM aufgabe WHERE id = 2")[0][0]
           == "Strom legen (Fassung A)", "überschrieben wurde NICHTS")

    neuer_stand = re.search(r'name="version" value="(\d+)"', seite).group(1)
    pruefe(neuer_stand == "2", "das Formular trägt jetzt den neuen Stand")
    felder["version"] = neuer_stand
    status, ort, _ = anfrage("POST", "/admin/aufgabe/2", felder)
    pruefe(status == 303, "ein zweiter, bewusster Versuch geht durch")
    pruefe(zeilen("SELECT titel FROM aufgabe WHERE id = 2")[0][0]
           == "Strom legen (Fassung B)", "und gewinnt dann")

    print("Vorschlagslisten")
    _, _, formular = anfrage("GET", "/admin/aufgabe/neu")
    pruefe('<datalist id="v-ort">' in formular, "es gibt eine Liste für den Ort")
    pruefe('value="Zeltplatz"' in formular,
           "und darin steht, was schon vorkommt")
    pruefe('value="Kalle"' in formular, "dasselbe für den Verantwortlichen")
    pruefe("keine feste Auswahl" in formular,
           "und es steht dabei, dass man auch anderes tippen kann")

    print("Löschen")
    status, ort, _ = anfrage("POST", "/admin/aufgabe/3/loeschen", {"csrf": CSRF})
    pruefe("hinweis=geloescht" in ort, "meldet Erfolg")
    pruefe(len(zeilen("SELECT id FROM aufgabe")) == 3, "die Zeile ist weg")
    status, _, _ = anfrage("POST", "/admin/aufgabe/4/loeschen",
                           {"csrf": "falsch"})
    pruefe(status == 400 and len(zeilen("SELECT id FROM aufgabe")) == 3,
           "ohne CSRF-Token wird nichts gelöscht")

    print("Unbekannte Nummern")
    status, _, _ = anfrage("GET", "/admin/aufgabe/999999")
    pruefe(status == 404, "unbekannte Aufgabe -> 404")
    status, _, _ = anfrage("GET", "/admin/programm/999999")
    pruefe(status == 404, "unbekannter Programmpunkt -> 404")

    print("Programmpunkt von Hand")
    con = sqlite3.connect(db_pfad)
    with con:
        con.execute(
            "INSERT INTO programm (serie, titel, datum, beginn, ende, tag_roh,"
            " zeit_roh, angelegt_am) VALUES ('dhc', 'Rennlauf', '2026-08-30',"
            " '2026-08-30 11:30', NULL, 'Sonntag', 'ab 11.30 Uhr', '2026-01-01')")
    con.close()
    pid = zeilen("SELECT id FROM programm")[0][0]

    _, _, formular = anfrage("GET", "/admin/programm/%d" % pid)
    pruefe("ab 11.30 Uhr" in formular,
           "das Formular zeigt, was auf der Website steht")
    pstand = re.search(r'name="version" value="(\d+)"', formular).group(1)

    pfelder = {"csrf": CSRF, "titel": "Rennlauf", "beginn": "12:00",
               "ende": "14:00", "notiz": "laut Rennleitung", "version": pstand}
    status, ort, _ = anfrage("POST", "/admin/programm/%d" % pid, pfelder)
    pruefe(status == 303 and "hinweis=gespeichert" in ort, "speichern klappt")
    zeile = zeilen("SELECT * FROM programm WHERE id = ?", pid)[0]
    pruefe(zeile["von_hand"] == 1,
           "der Punkt gilt jetzt als eigene Fassung – sonst überschriebe ihn "
           "der nächste Abruf wieder")
    pruefe(zeile["beginn"] == "2026-08-30 12:00", "die neue Zeit steht drin")
    pruefe(zeile["zeit_roh"] == "12:00 - 14:00 Uhr", "und ihr Wortlaut")

    status, _, seite = anfrage("POST", "/admin/programm/%d" % pid, pfelder)
    pruefe(status == 409 and "Jemand anderes war schneller" in seite,
           "auch hier schützt die Fassung")

    status, ort, _ = anfrage("POST", "/admin/programm/%d/freigeben" % pid,
                             {"csrf": CSRF})
    pruefe("hinweis=freigegeben" in ort, "Freigabe meldet Erfolg")
    pruefe(zeilen("SELECT von_hand FROM programm WHERE id = ?", pid)[0][0] == 0,
           "danach folgt der Punkt wieder der Website")

    print("Aufgaben im Band")
    _, _, seite = anfrage("GET", "/admin/band?tag=2026-08-27")
    pruefe("band-aufgabe" in seite, "die Aufgaben des Tages stehen im Band")
    pruefe(seite.count('href="/admin/aufgabe/') >= 2,
           "und führen auf ihre Seite")
    _, _, seite = anfrage("GET", "/admin/band?tag=2026-08-30")
    pruefe("band-aufgabe" not in seite,
           "an einem Tag ohne Aufgaben steht auch keine im Band")

    print("Der Pool bleibt draußen")
    _, _, seite = anfrage("GET", "/admin/band?tag=2026-08-27")
    pruefe("Pokale besorgen" not in seite,
           "eine Aufgabe ohne Uhrzeit hat auf einer Zeitachse nichts verloren")

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
