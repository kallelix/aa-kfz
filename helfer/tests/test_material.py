"""T-Shirt-Ausgabe, Funkgeräte und KFZ-Schlüssel.

    python helfer/tests/test_material.py

Startet den Server selbst. Die drei Ausgaben haben gemeinsam, dass sie im
Betrieb an einem Tisch mit Schlange davor bedient werden – geprüft wird
deshalb nicht nur, ob etwas gespeichert wird, sondern auch, ob die Ansicht
danach noch dort steht, wo man war.
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


verzeichnis = Path(tempfile.mkdtemp(prefix="helfer-material-"))
db_pfad = verzeichnis / "helfer.db"
os.environ["DB_PATH"] = str(db_pfad)
os.environ["TAGE"] = "2026-08-28,2026-08-29,2026-08-30"

from app import db, normalisieren  # noqa: E402

print("Kennzeichen normalisieren")
for roh, erwartet in (("il-a 123", "ILA123"), ("IL A 123", "ILA123"),
                      ("ila123", "ILA123"), ("  il-a-123 ", "ILA123"),
                      ("", ""), ("---", "")):
    pruefe(normalisieren.kennzeichen(roh) == erwartet,
           repr(roh) + " -> " + repr(normalisieren.kennzeichen(roh)))

db.init()
con = db.verbinden()
with con:
    schicht_id, _ = db.schicht_sichern(con, "Shuttle", "2026-08-29 08:00",
                                       "2026-08-29 16:00", "2026-08-29",
                                       bedarf=2)
    anna, _ = db.helfer_anlegen(con, {"name": "Anna Berg",
                                      "email": "anna@example.org",
                                      "tshirt": "M", "tshirt_roh": "M"})
    bert, _ = db.helfer_anlegen(con, {"name": "Bert Öhl",
                                      "email": "bert@example.org"})
    db.einteilen(schicht_id, anna, quelle="import", con=con)
con.close()

hafen = freier_hafen()
prozess = subprocess.Popen(
    [str(PYTHON), "-m", "app"],
    cwd=str(WURZEL),
    env={**os.environ, "DB_PATH": str(db_pfad), "BIND": f"127.0.0.1:{hafen}",
         "ADMIN_PASSWORD_HASH": HASH, "APP_SECRET_KEY": "test-schluessel",
         "COOKIE_SECURE": "0", "ZEITPLAN_SERIEN": "",
         "PYTHONIOENCODING": "utf-8"},
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


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
    for pfad in ("/admin/funk", "/admin/schluessel", "/admin/helfer/neu"):
        status, ort, _ = anfrage("GET", pfad)
        pruefe(status == 303 and ort.startswith("/admin/login"),
               pfad + " führt zur Anmeldung")

    anfrage("POST", "/admin/login",
            {"passwort": "test-passwort-123", "kuerzel": "KK",
             "weiter": "/admin"})
    _, _, seite = anfrage("GET", "/admin/helfer")
    CSRF = re.search(r'name="csrf" value="([^"]+)"', seite).group(1)

    # --- 1. T-Shirt --------------------------------------------------------
    print("T-Shirt: Vorbelegung")
    zeile = re.search(r'<tr id="helfer-%d".*?</tr>' % anna, seite, re.S).group(0)
    pruefe(re.search(r'value="M"\s+selected', zeile) is not None,
           "die Auswahl ist auf die angekündigte Größe vorbelegt")
    zeile = re.search(r'<tr id="helfer-%d".*?</tr>' % bert, seite, re.S).group(0)
    pruefe("selected" not in zeile,
           "wer keine angekündigt hat, bekommt keine Vorbelegung")

    print("T-Shirt: ausgeben")
    status, ort, _ = anfrage("POST", "/admin/helfer/%d/tshirt" % anna,
                             {"csrf": CSRF, "groesse": "XL", "suche": "berg"})
    pruefe(status == 303 and "hinweis=tshirt" in ort, "meldet Erfolg")
    pruefe("suche=berg" in ort and "#helfer-%d" % anna in ort,
           "kehrt mit demselben Suchbegriff an dieselbe Zeile zurück: " + ort)

    person = zeilen("SELECT * FROM helfer WHERE id = ?", anna)[0]
    pruefe(person["tshirt_ausgegeben"] == "XL", "die ausgegebene Größe steht drin")
    pruefe(person["tshirt"] == "M",
           "die angekündigte bleibt daneben stehen – beide zusammen sind für "
           "die Nachbestellung mehr wert als eine allein")
    pruefe(bool(person["tshirt_ausgegeben_am"]), "mit Zeitpunkt")
    pruefe(person["tshirt_kuerzel"] == "KK", "und wer sie ausgegeben hat")

    _, _, seite = anfrage("GET", "/admin/helfer?suche=berg")
    pruefe("marke-abweichung" in seite, "die Abweichung ist markiert")
    pruefe('value="berg"' in seite, "das Suchfeld ist wieder gefüllt")
    pruefe(">1<" in seite.split("Andere Größe")[1][:200],
           "und wird oben gezählt")

    print("T-Shirt: was nicht geht")
    status, ort, _ = anfrage("POST", "/admin/helfer/%d/tshirt" % anna,
                             {"csrf": CSRF, "groesse": "ERFUNDEN"})
    pruefe("hinweis=groesse" in ort, "eine erfundene Größe wird abgewiesen")
    pruefe(zeilen("SELECT tshirt_ausgegeben FROM helfer WHERE id = ?",
                  anna)[0][0] == "XL", "und ändert nichts")
    status, _, _ = anfrage("POST", "/admin/helfer/%d/tshirt" % bert,
                           {"csrf": "falsch", "groesse": "M"})
    pruefe(status == 400, "ohne CSRF-Token wird nichts vermerkt")
    status, ort, _ = anfrage("POST", "/admin/helfer/999999/tshirt",
                             {"csrf": CSRF, "groesse": "M"})
    pruefe("hinweis=unbekannt" in ort, "unbekannte Person wird abgefangen")

    print("T-Shirt: ohne angekündigte Größe geht auch")
    anfrage("POST", "/admin/helfer/%d/tshirt" % bert,
            {"csrf": CSRF, "groesse": "S"})
    person = zeilen("SELECT * FROM helfer WHERE id = ?", bert)[0]
    pruefe(person["tshirt_ausgegeben"] == "S" and person["tshirt"] is None,
           "ausgegeben ohne angekündigt ist keine Abweichung")
    _, _, seite = anfrage("GET", "/admin/helfer")
    pruefe(seite.count("marke-abweichung") == 1,
           "und wird nicht als solche gezählt")

    print("T-Shirt: zurücknehmen")
    status, ort, _ = anfrage("POST", "/admin/helfer/%d/tshirt/zurueck" % bert,
                             {"csrf": CSRF})
    pruefe("hinweis=tshirt-zurueck" in ort, "meldet Erfolg")
    person = zeilen("SELECT * FROM helfer WHERE id = ?", bert)[0]
    pruefe(person["tshirt_ausgegeben_am"] is None
           and person["tshirt_ausgegeben"] is None, "alles wieder offen")

    print("Helfer von Hand anlegen")
    status, _, seite = anfrage("GET", "/admin/helfer/neu")
    pruefe(status == 200 and "Helfer hinzufügen" in seite,
           "/admin/helfer/neu oeffnet das Formular und wird nicht von "
           "/admin/helfer/{id} als Zahl gelesen")
    status, ort, _ = anfrage("POST", "/admin/helfer/neu", {
        "csrf": CSRF, "name": "Spontan Spontanski", "tshirt": "L",
        "veggie": "ja", "email": "spontan@example.org", "telefon": "0170 1"})
    pruefe(status == 303 and "hinweis=angelegt" in ort, "wird angelegt")
    spontan = int(re.search(r"helfer-(\d+)", ort).group(1))
    person = zeilen("SELECT * FROM helfer WHERE id = ?", spontan)[0]
    pruefe(person["tshirt"] == "L" and person["veggie"] == 1,
           "mit Größe und Verpflegung")
    pruefe(len(zeilen("SELECT id FROM einteilung WHERE helfer_id = ?",
                      spontan)) == 0,
           "ohne Schicht – genau dafür gibt es die Funktion")

    status, _, seite = anfrage("POST", "/admin/helfer/neu", {
        "csrf": CSRF, "name": "Spontan Spontanski",
        "email": "spontan@example.org"})
    pruefe("steht schon in der Liste" in seite,
           "dieselbe Person zweimal wird erklärt, nicht als Fehler geworfen")
    pruefe(len(zeilen("SELECT id FROM helfer")) == 3, "und nicht doppelt angelegt")

    status, _, seite = anfrage("POST", "/admin/helfer/neu",
                               {"csrf": CSRF, "name": ""})
    pruefe('class="fehler"' in seite, "ohne Namen kommt das Formular zurück")

    print("Helfer ändern")
    status, ort, _ = anfrage("POST", "/admin/helfer/%d/aendern" % spontan, {
        "csrf": CSRF, "name": "Spontan Spontanski", "tshirt": "XL",
        "email": "spontan@example.org", "veggie": "nein"})
    pruefe("hinweis=gespeichert" in ort, "speichern klappt")
    person = zeilen("SELECT * FROM helfer WHERE id = ?", spontan)[0]
    pruefe(person["tshirt"] == "XL" and person["veggie"] == 0, "die Werte stimmen")

    # --- 2. Funkgeräte -----------------------------------------------------
    print("Einstellungen: Vorbelegung der Materialausgabe")
    status, _, seite = anfrage("GET", "/admin/einstellungen")
    pruefe(status == 200, "die Seite laedt")
    vorgaben = dict(re.findall(r'id="v-(\w+)"[^>]*value="(\d+)"', seite))
    pruefe(vorgaben == {"funke": "1", "headset": "0", "ersatzakku": "0"},
           "ohne Einstellung gilt: ein Funkgeraet, sonst nichts: " + str(vorgaben))

    _, _, funk = anfrage("GET", "/admin/funk")
    im_formular = dict(re.findall(
        r'id="m-(\w+)"[\s\S]{0,140}?value="(\d+)"', funk))
    pruefe(im_formular == vorgaben,
           "und genau das steht im Ausgabeformular: " + str(im_formular))

    status, ort, _ = anfrage("POST", "/admin/einstellungen",
                             {"csrf": CSRF, "funke": "1", "headset": "1",
                              "ersatzakku": "2"})
    pruefe("hinweis=gespeichert" in ort, "speichern meldet Erfolg")
    _, _, funk = anfrage("GET", "/admin/funk")
    im_formular = dict(re.findall(
        r'id="m-(\w+)"[\s\S]{0,140}?value="(\d+)"', funk))
    pruefe(im_formular == {"funke": "1", "headset": "1", "ersatzakku": "2"},
           "das Ausgabeformular folgt: " + str(im_formular))

    print("Einstellungen: was nicht durchgeht")
    anfrage("POST", "/admin/einstellungen",
            {"csrf": CSRF, "funke": "-5", "headset": "999",
             "ersatzakku": "quatsch"})
    _, _, seite = anfrage("GET", "/admin/einstellungen")
    vorgaben = dict(re.findall(r'id="v-(\w+)"[^>]*value="(\d+)"', seite))
    pruefe(vorgaben["funke"] == "0", "eine negative Zahl wird auf 0 geklemmt")
    pruefe(vorgaben["headset"] == "20",
           "eine unsinnig grosse auf den Hoechstwert: " + vorgaben["headset"])
    pruefe(vorgaben["ersatzakku"] == "2",
           "und was keine Zahl ist, laesst den alten Wert stehen")

    status, _, _ = anfrage("POST", "/admin/einstellungen",
                           {"csrf": "falsch", "funke": "9"})
    pruefe(status == 400, "ohne CSRF-Token wird nichts gespeichert")

    # Fuer den Rest der Pruefungen wieder auf die Vorgabe zurueck.
    anfrage("POST", "/admin/einstellungen",
            {"csrf": CSRF, "funke": "1", "headset": "0", "ersatzakku": "0"})

    print("Einstellungen: was aus der .env kommt")
    _, _, seite = anfrage("GET", "/admin/einstellungen")
    pruefe("TAGE" in seite and "MONITOR_VORSCHAU" in seite,
           "die Werte aus der Konfiguration stehen zum Nachsehen dabei")
    pruefe("nach einem Neustart" in seite,
           "mit dem Hinweis, dass eine Aenderung dort erst dann wirkt")

    print("Ausgabe und Ruecknahme nebeneinander")
    for pfad, name in (("/admin/funk", "funk-ausgabe"),
                       ("/admin/schluessel", "schluessel-ausgabe")):
        _, _, seite = anfrage("GET", pfad)
        pruefe('class="arbeitsflaeche"' in seite,
               pfad + ": Formular und Liste stehen in einer Flaeche")
        pruefe('data-merken="' + name + '"' in seite,
               "das Formular laesst sich zuklappen und wird gemerkt")
        pruefe('class="arbeit-liste"' in seite, "die Liste hat ihre eigene Spalte")
        pruefe(seite.index("arbeit-formular") < seite.index("arbeit-liste"),
               "Formular zuerst, Liste daneben")
        pruefe("admin_klapp.js" in seite, "das Klappskript haengt an der Seite")

    print("Funk: ausgeben")
    status, _, seite = anfrage("GET", "/admin/funk")
    pruefe(status == 200 and "Noch nichts ausgegeben" in seite,
           "die leere Seite sagt das auch")

    status, ort, _ = anfrage("POST", "/admin/funk/ausgeben", {
        "csrf": CSRF, "helfer_id": str(anna), "datum": "2026-08-29",
        "funke": "1", "headset": "1", "ersatzakku": "2",
        "bemerkung": "Shuttle Nord"})
    pruefe("hinweis=ausgegeben" in ort, "meldet Erfolg")
    vorgang = zeilen("SELECT * FROM ausleihe")[0]
    pruefe((vorgang["funke"], vorgang["headset"], vorgang["ersatzakku"])
           == (1, 1, 2), "die Mengen stimmen")
    pruefe(vorgang["datum"] == "2026-08-29",
           "mit Tagesbezug – ein Funkgerät wird für einen Tag geholt, nicht "
           "für eine einzelne Schicht")
    pruefe(vorgang["ausgegeben_von"] == "KK", "und mit Kürzel")

    status, ort, _ = anfrage("POST", "/admin/funk/ausgeben", {
        "csrf": CSRF, "helfer_id": str(bert), "datum": "morgen", "funke": "1"})
    pruefe("hinweis=ausgegeben" in ort, "ein unlesbarer Tag hält nichts auf")
    pruefe(zeilen("SELECT datum FROM ausleihe ORDER BY id")[1][0] is None,
           "er wird verworfen statt in die Datenbank gereicht")
    anfrage("POST", "/admin/ausleihe/%d/loeschen"
            % zeilen("SELECT id FROM ausleihe ORDER BY id")[1][0],
            {"csrf": CSRF})

    print("Funk: ohne Schicht und für jemand Neues")
    status, ort, _ = anfrage("POST", "/admin/funk/ausgeben",
                             {"csrf": CSRF, "neuer_name": "Ganz Neu",
                              "funke": "1"})
    pruefe("hinweis=neu-angelegt" in ort,
           "eine getippte Person wird angelegt und die Ausgabe gemeldet")
    neu = zeilen("SELECT * FROM helfer WHERE name = 'Ganz Neu'")
    pruefe(len(neu) == 1, "die Person steht jetzt in der Helferliste")
    ohne = zeilen("SELECT * FROM ausleihe WHERE helfer_id = ?", neu[0]["id"])[0]
    pruefe(ohne["datum"] is None,
           "ein Tagesbezug ist ausdrücklich nicht nötig")

    status, ort, _ = anfrage("POST", "/admin/funk/ausgeben",
                             {"csrf": CSRF, "helfer_id": str(anna),
                              "funke": "0", "headset": "0", "ersatzakku": "0"})
    pruefe("hinweis=nichts" in ort, "gar nichts auszugeben ist kein Vorgang")
    pruefe(len(zeilen("SELECT id FROM ausleihe")) == 2, "und legt nichts an")

    status, ort, _ = anfrage("POST", "/admin/funk/ausgeben",
                             {"csrf": CSRF, "funke": "1"})
    pruefe("hinweis=keiner" in ort, "ohne Person geht es nicht")

    print("Funk: Zähler")
    _, _, seite = anfrage("GET", "/admin/funk")
    zahlen = dict(re.findall(
        r'zaehler-titel">([^<]+)</p>\s*<p class="zaehler-zahl">(\d+)', seite))
    pruefe(zahlen.get("Funkgerät") == "2", "zwei Funkgeräte draußen")
    pruefe(zahlen.get("Ersatzakku") == "2", "zwei Ersatzakkus draußen")

    print("Funk: teilweise zurück")
    status, ort, _ = anfrage("POST", "/admin/ausleihe/%d/zurueck" % vorgang["id"],
                             {"csrf": CSRF, "teilweise": "1", "funke": "1",
                              "headset": "0", "ersatzakku": "1"})
    pruefe("hinweis=zurueck" in ort, "meldet Erfolg")
    jetzt = zeilen("SELECT * FROM ausleihe WHERE id = ?", vorgang["id"])[0]
    pruefe((jetzt["funke_zurueck"], jetzt["ersatzakku_zurueck"]) == (1, 1),
           "die Teilmengen stehen drin")
    pruefe(jetzt["zurueck_am"] is None,
           "solange etwas fehlt, gilt der Vorgang nicht als erledigt")
    _, _, seite = anfrage("GET", "/admin/funk?offen=1")
    pruefe(seite.count('class="ist-draussen"') == 2,
           "und steht weiter unter den offenen")

    print("Funk: mehr zurück als raus geht nicht")
    anfrage("POST", "/admin/ausleihe/%d/zurueck" % vorgang["id"],
            {"csrf": CSRF, "teilweise": "1", "funke": "99", "headset": "0",
             "ersatzakku": "0"})
    pruefe(zeilen("SELECT funke_zurueck FROM ausleihe WHERE id = ?",
                  vorgang["id"])[0][0] == 1,
           "die Menge wird auf das Ausgegebene begrenzt")

    print("Funk: alles zurück")
    status, ort, _ = anfrage("POST", "/admin/ausleihe/%d/zurueck" % vorgang["id"],
                             {"csrf": CSRF})
    jetzt = zeilen("SELECT * FROM ausleihe WHERE id = ?", vorgang["id"])[0]
    pruefe(jetzt["zurueck_am"] is not None, "jetzt ist der Vorgang erledigt")
    pruefe(jetzt["headset_zurueck"] == 1, "auch das Headset ist zurück")
    _, _, seite = anfrage("GET", "/admin/funk?offen=1")
    pruefe(seite.count('class="ist-draussen"') == 1, "einer bleibt offen")

    status, _, _ = anfrage("POST", "/admin/ausleihe/%d/zurueck" % vorgang["id"],
                           {"csrf": "falsch"})
    pruefe(status == 400, "ohne CSRF-Token geht keine Rückgabe")

    # --- 3. KFZ-Schlüssel --------------------------------------------------
    print("Schlüssel: Stamm baut sich auf")
    status, ort, _ = anfrage("POST", "/admin/schluessel/ausgeben", {
        "csrf": CSRF, "kennzeichen": "il-x 999", "name": "Maik Tibbe",
        "bemerkung": "Shuttle 1"})
    pruefe("hinweis=fahrzeug-neu" in ort,
           "das erste Mal legt das Fahrzeug an und sagt es")
    wagen = zeilen("SELECT * FROM fahrzeug")
    pruefe(len(wagen) == 1, "ein Fahrzeug im Stamm")
    pruefe(wagen[0]["kennzeichen_norm"] == "ILX999", "normalisiert gespeichert")
    pruefe(wagen[0]["kennzeichen"] == "IL-X 999",
           "die Schreibweise bleibt für die Anzeige erhalten")
    pruefe(wagen[0]["name"] == "Maik Tibbe", "der Halter ist gemerkt")

    status, ort, _ = anfrage("POST", "/admin/schluessel/ausgeben", {
        "csrf": CSRF, "kennzeichen": "ILX999", "name": "Anna Berg"})
    pruefe("hinweis=schluessel-raus" in ort,
           "anders getippt ist derselbe Wagen, kein neuer")
    pruefe(len(zeilen("SELECT id FROM fahrzeug")) == 1, "der Stamm bleibt bei einem")
    pruefe(zeilen("SELECT name FROM fahrzeug")[0][0] == "Maik Tibbe",
           "und der einmal gemerkte Halter wird nicht überschrieben")
    pruefe(len(zeilen("SELECT id FROM schluessel")) == 2, "zwei Ausgaben")
    pruefe(zeilen("SELECT name FROM schluessel ORDER BY id")[1][0] == "Anna Berg",
           "die zweite Ausgabe steht auf Anna – wer den Schlüssel hat, kann "
           "vom Halter abweichen")

    status, ort, _ = anfrage("POST", "/admin/schluessel/ausgeben",
                             {"csrf": CSRF, "kennzeichen": "---"})
    pruefe("hinweis=kein-kennzeichen" in ort,
           "ein Kennzeichen ohne Buchstaben und Ziffern wird abgewiesen")
    pruefe(len(zeilen("SELECT id FROM fahrzeug")) == 1, "und legt nichts an")

    print("Der Fahrzeugstamm steht unter der Flaeche")
    _, _, seite = anfrage("GET", "/admin/schluessel")
    pruefe(seite.index("arbeitsflaeche") < seite.index("fahrzeugstamm"),
           "nicht in der Spalte neben dem Formular")
    pruefe('data-merken="fahrzeugstamm"' in seite,
           "und laesst sich ebenfalls zuklappen")

    print("Schlüssel: Namensvorschläge")
    _, _, seite = anfrage("GET", "/admin/schluessel")
    liste = seite.split('<datalist id="v-namen">')[1].split("</datalist>")[0]
    pruefe(liste.index("Anna Berg") < liste.index("Bert"),
           "die vom Shuttle stehen vorn: " + liste[:120].replace("\\n", " "))
    pruefe("Ganz Neu" in liste,
           "die von Hand angelegten stehen auch drin")

    print("Schlüssel: zurück")
    sid = zeilen("SELECT id FROM schluessel ORDER BY id")[0][0]
    status, ort, _ = anfrage("POST", "/admin/schluessel/%d/zurueck" % sid,
                             {"csrf": CSRF})
    pruefe("hinweis=zurueck" in ort, "meldet Erfolg")
    zeile = zeilen("SELECT * FROM schluessel WHERE id = ?", sid)[0]
    pruefe(zeile["zurueck_am"] is not None and zeile["zurueck_von"] == "KK",
           "mit Zeitpunkt und Kürzel")

    status, ort, _ = anfrage("POST", "/admin/schluessel/%d/zurueck" % sid,
                             {"csrf": CSRF})
    pruefe(zeilen("SELECT zurueck_am FROM schluessel WHERE id = ?", sid)[0][0]
           == zeile["zurueck_am"],
           "ein zweites Mal ändert den Zeitpunkt nicht")

    _, _, seite = anfrage("GET", "/admin/schluessel?offen=1")
    pruefe(seite.count('class="ist-draussen"') == 1, "einer ist noch draußen")

    print("Schlüssel: Suche ist trennzeichentolerant")
    _, _, seite = anfrage("GET", "/admin/schluessel")
    zeile = re.search(r'<tr data-suche="([^"]*)"', seite).group(1)
    pruefe("ilx999" in zeile,
           "der Suchtext enthält die normalisierte Form: " + zeile[:60])

    print("Löschen")
    status, ort, _ = anfrage("POST", "/admin/schluessel/%d/loeschen" % sid,
                             {"csrf": CSRF})
    pruefe("hinweis=geloescht" in ort and
           len(zeilen("SELECT id FROM schluessel")) == 1, "Schlüsselvorgang weg")
    status, ort, _ = anfrage("POST", "/admin/ausleihe/%d/loeschen" % vorgang["id"],
                             {"csrf": CSRF})
    pruefe("hinweis=geloescht" in ort and
           len(zeilen("SELECT id FROM ausleihe")) == 1, "Ausleihe weg")

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
