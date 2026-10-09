"""T-Shirt-Ausgabe und die Materialausgabe (Funk, Schlüssel und mehr).

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
import subprocess
import sys
import time
import urllib.parse
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


db_url = testdb.wegwerf("helfer_material")
os.environ["DATABASE_URL"] = db_url

from app import db, normalisieren  # noqa: E402

print("Kennzeichen normalisieren")
for roh, erwartet in (("il-a 123", "ILA123"), ("IL A 123", "ILA123"),
                      ("ila123", "ILA123"), ("  il-a-123 ", "ILA123"),
                      ("", ""), ("---", "")):
    pruefe(normalisieren.kennzeichen(roh) == erwartet,
           repr(roh) + " -> " + repr(normalisieren.kennzeichen(roh)))

db.init()

# Alles im Helferbereich gehört zu einer Veranstaltung: diese hier, auf die
# Tage der Testdaten. Sie ist die einzige, also auch die, die der Server ohne
# eigene Wahl nimmt.
VA = db.VERANSTALTUNGEN.anlegen({"name": "Die absolute Abfahrt 2026", "kurz": "AA 2026",
                                 "beginn": "2026-08-28", "ende": "2026-08-30",
                                 "ort": "Ilmenau"})
con = db.verbinden()
with con:
    schicht_id, _ = db.schicht_sichern(con, VA, "Shuttle", "2026-08-29 08:00",
                                       "2026-08-29 16:00", "2026-08-29",
                                       soll=2)
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
    env={**os.environ, "DATABASE_URL": db_url, "BIND": f"127.0.0.1:{hafen}",
         "ADMIN_PASSWORD_HASH": HASH, "APP_SECRET_KEY": "test-schluessel",
         "COOKIE_SECURE": "0", "ZEITPLAN_SERIEN": "",
         "PYTHONIOENCODING": "utf-8"},
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def zeilen(sql, *parameter):
    return testdb.abfrage(db_url, "helfer", sql, parameter)


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
    for pfad in ("/helfer/ausgabe", "/helfer/material", "/helfer/helfer/neu"):
        status, ort, _ = anfrage("GET", pfad)
        pruefe(status == 303 and ort.startswith("/helfer/login"),
               pfad + " führt zur Anmeldung")

    anfrage("POST", "/helfer/login",
            {"passwort": "test-passwort-123", "kuerzel": "KK",
             "weiter": "/helfer"})
    _, _, seite = anfrage("GET", "/helfer/helfer")
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
    status, ort, _ = anfrage("POST", "/helfer/helfer/%d/tshirt" % anna,
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

    _, _, seite = anfrage("GET", "/helfer/helfer?suche=berg")
    pruefe("marke-abweichung" in seite, "die Abweichung ist markiert")
    pruefe('value="berg"' in seite, "das Suchfeld ist wieder gefüllt")
    pruefe(">1<" in seite.split("Andere Größe")[1][:200],
           "und wird oben gezählt")

    print("T-Shirt: was nicht geht")
    status, ort, _ = anfrage("POST", "/helfer/helfer/%d/tshirt" % anna,
                             {"csrf": CSRF, "groesse": "ERFUNDEN"})
    pruefe("hinweis=groesse" in ort, "eine erfundene Größe wird abgewiesen")
    pruefe(zeilen("SELECT tshirt_ausgegeben FROM helfer WHERE id = ?",
                  anna)[0][0] == "XL", "und ändert nichts")
    status, _, _ = anfrage("POST", "/helfer/helfer/%d/tshirt" % bert,
                           {"csrf": "falsch", "groesse": "M"})
    pruefe(status == 400, "ohne CSRF-Token wird nichts vermerkt")
    status, ort, _ = anfrage("POST", "/helfer/helfer/999999/tshirt",
                             {"csrf": CSRF, "groesse": "M"})
    pruefe("hinweis=unbekannt" in ort, "unbekannte Person wird abgefangen")

    print("T-Shirt: ohne angekündigte Größe geht auch")
    anfrage("POST", "/helfer/helfer/%d/tshirt" % bert,
            {"csrf": CSRF, "groesse": "S"})
    person = zeilen("SELECT * FROM helfer WHERE id = ?", bert)[0]
    pruefe(person["tshirt_ausgegeben"] == "S" and person["tshirt"] is None,
           "ausgegeben ohne angekündigt ist keine Abweichung")
    _, _, seite = anfrage("GET", "/helfer/helfer")
    pruefe(seite.count("marke-abweichung") == 1,
           "und wird nicht als solche gezählt")

    print("T-Shirt: zurücknehmen")
    status, ort, _ = anfrage("POST", "/helfer/helfer/%d/tshirt/zurueck" % bert,
                             {"csrf": CSRF})
    pruefe("hinweis=tshirt-zurueck" in ort, "meldet Erfolg")
    person = zeilen("SELECT * FROM helfer WHERE id = ?", bert)[0]
    pruefe(person["tshirt_ausgegeben_am"] is None
           and person["tshirt_ausgegeben"] is None, "alles wieder offen")

    print("Helfer von Hand anlegen")
    status, _, seite = anfrage("GET", "/helfer/helfer/neu")
    pruefe(status == 200 and "Helfer hinzufügen" in seite,
           "/helfer/helfer/neu oeffnet das Formular und wird nicht von "
           "/helfer/helfer/{id} als Zahl gelesen")
    status, ort, _ = anfrage("POST", "/helfer/helfer/neu", {
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

    status, _, seite = anfrage("POST", "/helfer/helfer/neu", {
        "csrf": CSRF, "name": "Spontan Spontanski",
        "email": "spontan@example.org"})
    pruefe("steht schon in der Liste" in seite,
           "dieselbe Person zweimal wird erklärt, nicht als Fehler geworfen")
    pruefe(len(zeilen("SELECT id FROM helfer")) == 3, "und nicht doppelt angelegt")

    status, _, seite = anfrage("POST", "/helfer/helfer/neu",
                               {"csrf": CSRF, "name": ""})
    pruefe('class="fehler"' in seite, "ohne Namen kommt das Formular zurück")

    print("Helfer ändern")
    status, ort, _ = anfrage("POST", "/helfer/helfer/%d/aendern" % spontan, {
        "csrf": CSRF, "name": "Spontan Spontanski", "tshirt": "XL",
        "email": "spontan@example.org", "veggie": "nein"})
    pruefe("hinweis=gespeichert" in ort, "speichern klappt")
    person = zeilen("SELECT * FROM helfer WHERE id = ?", spontan)[0]
    pruefe(person["tshirt"] == "XL" and person["veggie"] == 0, "die Werte stimmen")

    # Jede angebotene Groesse muss auch ankommen. 5XL stand eine Weile im
    # Auswahlfeld, waehrend eine CHECK-Klausel in der Tabelle nur bis 4XL
    # ging - wer sie waehlte, bekam einen Fehler statt einer Speicherung.
    print("Jede Groesse aus dem Auswahlfeld kommt auch an")
    for groesse in ("XS", "4XL", "5XL"):
        status, ort, _ = anfrage("POST", "/helfer/helfer/%d/aendern" % spontan, {
            "csrf": CSRF, "name": "Spontan Spontanski", "tshirt": groesse,
            "email": "spontan@example.org", "veggie": "nein"})
        gespeichert = zeilen("SELECT tshirt FROM helfer WHERE id = ?",
                             spontan)[0][0]
        pruefe("hinweis=gespeichert" in ort and gespeichert == groesse,
               groesse + " kommt in der Datenbank an")
    anfrage("POST", "/helfer/helfer/%d/aendern" % spontan, {
        "csrf": CSRF, "name": "Spontan Spontanski", "tshirt": "XL",
        "email": "spontan@example.org", "veggie": "nein"})

    print("Helfer als CSV")
    status, ort, _ = anfrage("GET", "/helfer/helfer/export.csv")
    kopf = None
    zeilen_csv = None
    pruefe(status == 200, "die Datei kommt")
    _, _, roh = anfrage("GET", "/helfer/helfer/export.csv")
    # anfrage() gibt Text zurueck - das reicht, um Inhalt und Trenner zu
    # pruefen; die Bytes selbst prueft der Aufruf gegen den Server unten.
    zeilen_csv = [z for z in roh.splitlines() if z.strip()]
    kopf = zeilen_csv[0].lstrip("﻿").split(";")
    pruefe(kopf[:4] == ["Name", "E-Mail", "Telefon", "Verpflegung"],
           "die Spalten stehen dran: " + ", ".join(kopf[:4]))
    for spalte in ("Größe angekündigt", "Größe wie eingetippt",
                   "T-Shirt ausgegeben", "ausgegeben am", "ausgegeben von"):
        pruefe(spalte in kopf, "steht dabei: " + spalte)
    pruefe(len(set(kopf)) == len(kopf), "keine Spalte doppelt")

    # Die T-Shirt-Ausgabe passt in die Personenzeile, weil es hoechstens eine
    # je Helfer gibt. Funk und Schluessel sind eigene Vorgaenge, davon
    # beliebig viele - die wuerden die Zeile vervielfachen.
    for spalte in ("Funkgerät", "Headset", "Ersatzakku", "Kennzeichen"):
        pruefe(spalte not in kopf, "nicht in dieser Sicht: " + spalte)
    pruefe(len(zeilen_csv) - 1 == len(zeilen("SELECT id FROM helfer")),
           "eine Zeile je Helfer: %d" % (len(zeilen_csv) - 1))
    pruefe(zeilen_csv[0].startswith("﻿"),
           "mit BOM voran, sonst zeigt Excel Umlautsalat")
    pruefe(any("Anna Berg" in z for z in zeilen_csv), "die Leute stehen drin")

    # Anna hat oben ein XL bekommen, angekuendigt war M. Genau fuer diesen
    # Fall stehen beide Spalten nebeneinander.
    annas = [z.split(";") for z in zeilen_csv if z.startswith("Anna Berg")][0]
    pruefe(annas[kopf.index("Größe angekündigt")] == "M"
           and annas[kopf.index("T-Shirt ausgegeben")] == "XL",
           "angekuendigt M, ausgegeben XL - beides steht da: "
           + str(annas[4:9]))
    pruefe(annas[kopf.index("ausgegeben von")] == "KK",
           "mit dem Kuerzel dessen, der es ausgegeben hat")

    # --- 2. Material einrichten (Lastenheft 3.8, V-09) --------------------
    print("Material: noch nichts")
    status, _, seite = anfrage("GET", "/helfer/ausgabe")
    pruefe(status == 200 and "Noch kein Material" in seite and 'href="/helfer/material"' in seite,
           "ohne Material sagt die Ausgabe, wo man es einrichtet")
    status, _, seite = anfrage("GET", "/helfer/material")
    pruefe(status == 200 and "Funk und Schlüssel anlegen" in seite,
           "die Materialseite bietet die bisherigen vier mit einem Klick an")
    status, ort, _ = anfrage("POST", "/helfer/material/standard", {"csrf": CSRF})
    pruefe("hinweis=material-standard" in ort, "angelegt")
    mat = {z["name"]: z for z in zeilen("SELECT * FROM material WHERE veranstaltung_id = ?", VA)}
    pruefe(sorted(mat) == ["Ersatzakku", "Fahrzeugschlüssel", "Funkgerät", "Headset"],
           "Funkgerät, Headset, Ersatzakku, Fahrzeugschlüssel")
    pruefe(mat["Funkgerät"]["vorgabe"] == 1 and mat["Headset"]["vorgabe"] == 0
           and mat["Fahrzeugschlüssel"]["erfassen"] == "kennzeichen",
           "ein Funkgerät vorbelegt, der Schlüssel mit Kennzeichen")
    anfrage("POST", "/helfer/material/standard", {"csrf": CSRF})
    pruefe(len(zeilen("SELECT id FROM material")) == 4, "ein zweiter Klick legt nichts doppelt an")
    FUNK, HEADSET, AKKU, SCHLUESSEL = (mat[n]["id"] for n in
                                       ("Funkgerät", "Headset", "Ersatzakku", "Fahrzeugschlüssel"))

    print("Material: anlegen, ändern, was nicht geht")
    status, ort, _ = anfrage("POST", "/helfer/material", {
        "csrf": CSRF, "name": "Parkausweis", "erfassen": "nummer", "vorgabe": "0"})
    pruefe("hinweis=material-neu" in ort, "ein neues Material")
    park = zeilen("SELECT * FROM material WHERE name = 'Parkausweis'")[0]
    pruefe(park["rueckgabe"] == 0 and park["unterschrift"] == 0 and park["erfassen"] == "nummer",
           "ohne Häkchen: ohne Rückgabe und ohne Unterschrift, mit Nummer")
    status, _, seite = anfrage("POST", "/helfer/material", {"csrf": CSRF, "name": "Funkgerät"})
    pruefe(status == 400 and "gibt es schon" in seite, "denselben Namen zweimal gibt es nicht")
    status, _, seite = anfrage("POST", "/helfer/material", {"csrf": CSRF, "name": ""})
    pruefe(status == 400 and "Ohne Namen" in seite, "ohne Namen auch nicht")
    status, ort, _ = anfrage("POST", "/helfer/material/%d" % HEADSET, {
        "csrf": CSRF, "name": "Headset", "vorgabe": "999", "rueckgabe": "1", "unterschrift": "1"})
    pruefe("hinweis=gespeichert" in ort
           and zeilen("SELECT vorgabe FROM material WHERE id = ?", HEADSET)[0][0] == 20,
           "eine unsinnig große Vorbelegung wird auf den Höchstwert geklemmt")
    anfrage("POST", "/helfer/material/%d" % HEADSET, {
        "csrf": CSRF, "name": "Headset", "vorgabe": "0", "rueckgabe": "1", "unterschrift": "1"})
    status, _, _ = anfrage("POST", "/helfer/material/%d" % HEADSET, {"csrf": "falsch", "name": "X"})
    pruefe(status == 400, "ohne CSRF-Token wird nichts gespeichert")

    print("Einstellungen: was aus der .env kommt")
    _, _, seite = anfrage("GET", "/helfer/einstellungen")
    pruefe("MONITOR_VORSCHAU" in seite,
           "die Werte aus der Konfiguration stehen zum Nachsehen dabei")
    pruefe("Veranstaltungstage" not in seite,
           "die Tage nicht mehr - die kommen aus der Veranstaltung")
    pruefe("nach einem Neustart" in seite,
           "mit dem Hinweis, dass eine Aenderung dort erst dann wirkt")
    pruefe('href="/helfer/material"' in seite, "und dem Weg zur Vorbelegung, die jetzt beim Material steht")

    print("Ausgabe und Ruecknahme nebeneinander")
    _, _, seite = anfrage("GET", "/helfer/ausgabe")
    pruefe('class="arbeitsflaeche"' in seite, "Formular und Liste stehen in einer Flaeche")
    pruefe('data-merken="ausgabe"' in seite, "das Formular laesst sich zuklappen und wird gemerkt")
    pruefe('class="arbeit-liste"' in seite, "die Liste hat ihre eigene Spalte")
    pruefe(seite.index("arbeit-formular") < seite.index("arbeit-liste"),
           "Formular zuerst, Liste daneben")
    pruefe("admin_merken.js" in seite, "das Merkskript haengt an der Seite")
    im_formular = dict(re.findall(r'id="m-(\d+)"[\s\S]{0,140}?value="(\d+)"', seite))
    pruefe(im_formular == {str(FUNK): "1", str(HEADSET): "0", str(AKKU): "0", str(park["id"]): "0"},
           "das Formular ist wie eingestellt vorbelegt: " + str(im_formular))
    pruefe('id="n-%d"' % SCHLUESSEL in seite and 'id="n-%d"' % park["id"] in seite,
           "Kennzeichen und Nummer haben ihr Feld")

    for alt in ("/helfer/funk", "/helfer/schluessel"):
        status, ort, _ = anfrage("GET", alt)
        pruefe(status == 303 and ort == "/helfer/ausgabe", alt + " führt zur Ausgabe")

    # --- 3. Ausgeben -----------------------------------------------------------
    print("Funk: ausgeben")
    pruefe("Noch nichts ausgegeben" in seite, "die leere Liste sagt das auch")
    status, ort, _ = anfrage("POST", "/helfer/ausgabe", {
        "csrf": CSRF, "helfer_id": str(anna), "datum": "2026-08-29",
        "m-%d" % FUNK: "1", "m-%d" % HEADSET: "1", "m-%d" % AKKU: "2",
        "bemerkung": "Shuttle Nord"})
    pruefe("hinweis=ausgegeben" in ort, "meldet Erfolg")
    vorgang = zeilen("SELECT * FROM ausgabe")[0]
    posten = {z["material_id"]: z["menge"] for z in
              zeilen("SELECT * FROM ausgabe_posten WHERE ausgabe_id = ?", vorgang["id"])}
    pruefe(posten == {FUNK: 1, HEADSET: 1, AKKU: 2}, "die Mengen stimmen: " + str(posten))
    pruefe(vorgang["datum"] == "2026-08-29" and vorgang["helfer_id"] == anna
           and vorgang["name"] == "Anna Berg",
           "mit Tagesbezug – ein Funkgerät wird für einen Tag geholt, nicht "
           "für eine einzelne Schicht")
    pruefe(vorgang["ausgegeben_von"] == "KK", "und mit Kürzel")

    status, ort, _ = anfrage("POST", "/helfer/ausgabe", {
        "csrf": CSRF, "helfer_id": str(bert), "datum": "morgen", "m-%d" % FUNK: "1"})
    pruefe("hinweis=ausgegeben" in ort, "ein unlesbarer Tag hält nichts auf")
    pruefe(zeilen("SELECT datum FROM ausgabe ORDER BY id")[1][0] is None,
           "er wird verworfen statt in die Datenbank gereicht")
    anfrage("POST", "/helfer/ausgabe/%d/loeschen"
            % zeilen("SELECT id FROM ausgabe ORDER BY id")[1][0], {"csrf": CSRF})

    print("An jemand anderes (V-09)")
    status, ort, _ = anfrage("POST", "/helfer/ausgabe",
                             {"csrf": CSRF, "name": "Ganz Neu", "m-%d" % FUNK: "1"})
    pruefe("hinweis=ausgegeben" in ort, "an einen Namen, der kein Helfer ist")
    pruefe(not zeilen("SELECT * FROM helfer WHERE name = 'Ganz Neu'"),
           "er landet nicht in der Helferliste")
    ohne = zeilen("SELECT * FROM ausgabe WHERE name = 'Ganz Neu'")[0]
    pruefe(ohne["helfer_id"] is None and ohne["datum"] is None,
           "der Vorgang steht nur auf dem Namen, ein Tagesbezug ist nicht nötig")

    status, ort, _ = anfrage("POST", "/helfer/ausgabe",
                             {"csrf": CSRF, "helfer_id": str(anna),
                              "m-%d" % FUNK: "0", "m-%d" % HEADSET: "0"})
    pruefe("hinweis=nichts" in ort, "gar nichts auszugeben ist kein Vorgang")
    pruefe(len(zeilen("SELECT id FROM ausgabe")) == 2, "und legt nichts an")
    status, ort, _ = anfrage("POST", "/helfer/ausgabe", {"csrf": CSRF, "m-%d" % FUNK: "1"})
    pruefe("hinweis=keiner" in ort, "ohne Person geht es nicht")

    print("Ohne Rückgabe, mit Nummer")
    status, ort, _ = anfrage("POST", "/helfer/ausgabe", {
        "csrf": CSRF, "helfer_id": str(bert), "m-%d" % park["id"]: "1",
        "n-%d" % park["id"]: "P 17", "m-%d" % FUNK: "0"})
    park_vorgang = zeilen("SELECT * FROM ausgabe WHERE helfer_id = ?", bert)[0]
    pruefe(park_vorgang["zurueck_am"] is not None,
           "ein Parkausweis ist mit der Übergabe erledigt")
    pruefe(zeilen("SELECT nummer FROM ausgabe_posten WHERE ausgabe_id = ?",
                  park_vorgang["id"])[0][0] == "P 17", "seine Nummer steht dabei")
    _, _, seite = anfrage("GET", "/helfer/ausgabe")
    pruefe("ohne Rückgabe" in seite and "1× Parkausweis (Nr. P 17)" in seite,
           "die Liste zeigt es so")

    print("Funk: Zähler")
    zahlen = dict(re.findall(
        r'zaehler-titel">([^<]+)</p>\s*<p class="zaehler-zahl">(\d+)', seite))
    pruefe(zahlen.get("Funkgerät") == "2" and zahlen.get("Ersatzakku") == "2"
           and zahlen.get("Parkausweis") == "1",
           "zwei Funkgeräte und zwei Ersatzakkus draußen, ein Parkausweis ausgegeben: "
           + str(zahlen))

    print("Funk: teilweise zurück")
    p = {z["material_id"]: z["id"] for z in
         zeilen("SELECT * FROM ausgabe_posten WHERE ausgabe_id = ?", vorgang["id"])}
    status, ort, _ = anfrage("POST", "/helfer/ausgabe/%d/zurueck" % vorgang["id"],
                             {"csrf": CSRF, "teilweise": "1", "z-%d" % p[FUNK]: "1",
                              "z-%d" % p[HEADSET]: "0", "z-%d" % p[AKKU]: "1"})
    pruefe("hinweis=zurueck" in ort, "meldet Erfolg")
    zurueck = {z["material_id"]: z["zurueck"] for z in
               zeilen("SELECT * FROM ausgabe_posten WHERE ausgabe_id = ?", vorgang["id"])}
    pruefe(zurueck == {FUNK: 1, HEADSET: 0, AKKU: 1}, "die Teilmengen stehen drin")
    pruefe(zeilen("SELECT zurueck_am FROM ausgabe WHERE id = ?", vorgang["id"])[0][0] is None,
           "solange etwas fehlt, gilt der Vorgang nicht als erledigt")
    _, _, seite = anfrage("GET", "/helfer/ausgabe?offen=1")
    pruefe(seite.count('class="ist-draussen"') == 2, "und steht weiter unter den offenen")

    print("Funk: mehr zurück als raus geht nicht")
    anfrage("POST", "/helfer/ausgabe/%d/zurueck" % vorgang["id"],
            {"csrf": CSRF, "teilweise": "1", "z-%d" % p[FUNK]: "99",
             "z-%d" % p[HEADSET]: "0", "z-%d" % p[AKKU]: "1"})
    pruefe(zeilen("SELECT zurueck FROM ausgabe_posten WHERE id = ?", p[FUNK])[0][0] == 1,
           "die Menge wird auf das Ausgegebene begrenzt")

    print("Funk: alles zurück")
    anfrage("POST", "/helfer/ausgabe/%d/zurueck" % vorgang["id"], {"csrf": CSRF})
    jetzt = zeilen("SELECT * FROM ausgabe WHERE id = ?", vorgang["id"])[0]
    pruefe(jetzt["zurueck_am"] is not None and jetzt["zurueck_von"] == "KK",
           "jetzt ist der Vorgang erledigt, mit Kürzel")
    pruefe(zeilen("SELECT zurueck FROM ausgabe_posten WHERE id = ?", p[HEADSET])[0][0] == 1,
           "auch das Headset ist zurück")
    _, _, seite = anfrage("GET", "/helfer/ausgabe?offen=1")
    pruefe(seite.count('class="ist-draussen"') == 1, "einer bleibt offen")
    status, _, _ = anfrage("POST", "/helfer/ausgabe/%d/zurueck" % vorgang["id"],
                           {"csrf": "falsch"})
    pruefe(status == 400, "ohne CSRF-Token geht keine Rückgabe")

    # --- 4. Schlüssel ----------------------------------------------------------
    print("Schlüssel: Stamm baut sich auf")
    status, ort, _ = anfrage("POST", "/helfer/ausgabe", {
        "csrf": CSRF, "name": "Maik Tibbe", "n-%d" % SCHLUESSEL: "il-x 999",
        "m-%d" % FUNK: "0", "bemerkung": "Shuttle 1"})
    pruefe("hinweis=fahrzeug-neu" in ort, "das erste Mal legt das Fahrzeug an und sagt es")
    wagen = zeilen("SELECT * FROM fahrzeug")
    pruefe(len(wagen) == 1, "ein Fahrzeug im Stamm")
    pruefe(wagen[0]["kennzeichen_norm"] == "ILX999", "normalisiert gespeichert")
    pruefe(wagen[0]["kennzeichen"] == "IL-X 999",
           "die Schreibweise bleibt für die Anzeige erhalten")
    pruefe(wagen[0]["name"] == "Maik Tibbe", "der Halter ist gemerkt")

    status, ort, _ = anfrage("POST", "/helfer/ausgabe", {
        "csrf": CSRF, "helfer_id": str(anna), "n-%d" % SCHLUESSEL: "ILX999",
        "m-%d" % FUNK: "0"})
    pruefe("hinweis=ausgegeben" in ort, "anders getippt ist derselbe Wagen, kein neuer")
    pruefe(len(zeilen("SELECT id FROM fahrzeug")) == 1, "der Stamm bleibt bei einem")
    pruefe(zeilen("SELECT name FROM fahrzeug")[0][0] == "Maik Tibbe",
           "und der einmal gemerkte Halter wird nicht überschrieben")
    schluessel = zeilen("SELECT a.id, a.name, p.nummer FROM ausgabe a JOIN ausgabe_posten p"
                        " ON p.ausgabe_id = a.id WHERE p.material_id = ? ORDER BY a.id", SCHLUESSEL)
    pruefe(len(schluessel) == 2 and schluessel[1]["name"] == "Anna Berg"
           and schluessel[1]["nummer"] == "IL-X 999",
           "die zweite Ausgabe steht auf Anna – wer den Schlüssel hat, kann vom Halter abweichen")

    status, ort, _ = anfrage("POST", "/helfer/ausgabe",
                             {"csrf": CSRF, "name": "Wer", "n-%d" % SCHLUESSEL: "---"})
    pruefe("hinweis=kein-kennzeichen" in ort,
           "ein Kennzeichen ohne Buchstaben und Ziffern wird abgewiesen")
    pruefe(len(zeilen("SELECT id FROM fahrzeug")) == 1, "und legt nichts an")

    print("Der Fahrzeugstamm steht unter der Flaeche")
    _, _, seite = anfrage("GET", "/helfer/ausgabe")
    pruefe(seite.index("arbeitsflaeche") < seite.index("fahrzeugstamm"),
           "nicht in der Spalte neben dem Formular")
    pruefe('data-merken="fahrzeugstamm"' in seite, "und laesst sich ebenfalls zuklappen")
    pruefe('<option value="IL-X 999">Maik Tibbe</option>' in seite,
           "das Kennzeichenfeld schlägt den Stamm vor")

    print("Namensvorschläge für jemand anderes")
    liste = seite.split('<datalist id="v-namen">')[1].split("</datalist>")[0]
    pruefe("Maik Tibbe" in liste and "Ganz Neu" in liste and "Anna Berg" not in liste,
           "wer schon ohne Helfereintrag etwas bekam – Helfer stehen in der Auswahl darüber")

    print("Schlüssel: zurück")
    sid = schluessel[0]["id"]
    status, ort, _ = anfrage("POST", "/helfer/ausgabe/%d/zurueck" % sid, {"csrf": CSRF})
    pruefe("hinweis=zurueck" in ort, "meldet Erfolg")
    zeile = zeilen("SELECT * FROM ausgabe WHERE id = ?", sid)[0]
    pruefe(zeile["zurueck_am"] is not None and zeile["zurueck_von"] == "KK",
           "mit Zeitpunkt und Kürzel")
    _, _, seite = anfrage("GET", "/helfer/ausgabe?offen=1")
    pruefe(seite.count('class="ist-draussen"') == 2, "Annas Schlüssel und Ganz Neus Funkgerät sind noch draußen")

    print("Umschalter: alles oder nur was draußen ist")
    gesamt = zeilen("SELECT COUNT(*) FROM ausgabe")[0][0]
    draussen = zeilen("SELECT COUNT(*) FROM ausgabe WHERE zurueck_am IS NULL")[0][0]
    for anhang, erwartet_aktiv, erwartete_zeilen in (
            ("", "Alle", gesamt), ("?offen=1", "Noch draußen", draussen)):
        _, _, seite = anfrage("GET", "/helfer/ausgabe" + anhang)
        pruefe('data-merken-filter="ausgabe-offen"' in seite,
               "/helfer/ausgabe" + anhang + ": der Umschalter wird gemerkt")
        # Beide Zahlen stehen immer dran - auch auf der gefilterten Seite,
        # sonst waere "Alle" so gross wie die gerade sichtbare Liste.
        zahlen = re.findall(r'umschalter-zahl">(\d+)<', seite)
        pruefe(zahlen == [str(gesamt), str(draussen)],
               "beide Zahlen stimmen: %s statt %s" % (zahlen, [gesamt, draussen]))
        aktiv = re.search(r'umschalter-teil ist-aktiv[^"]*"'
                          r'[\s\S]{0,200}?>\s*([^<]+?)\s*<span', seite)
        pruefe(aktiv is not None and aktiv.group(1) == erwartet_aktiv,
               "die gewählte Seite ist hervorgehoben: " + (aktiv.group(1) if aktiv else "keine"))
        # admin_merken.js vergleicht die gemerkte Wahl mit dem data-wert des
        # hervorgehobenen Teils - stimmte der nicht, lüde es immer wieder neu.
        teile = re.findall(r'<a class="umschalter-teil([^"]*)"\s*'
                           r'href="[^"]*" data-wert="(\d)"', seite)
        markiert = [wert for klassen, wert in teile if "ist-aktiv" in klassen]
        pruefe(markiert == ["1" if anhang else "0"],
               "genau ein data-wert ist markiert, und zwar der richtige: " + str(markiert))
        pruefe(seite.count('<tr data-suche=') == erwartete_zeilen,
               "und es stehen %d Zeilen da" % erwartete_zeilen)

    print("Suche ist trennzeichentolerant")
    _, _, seite = anfrage("GET", "/helfer/ausgabe")
    pruefe(any("ilx999" in z for z in re.findall(r'<tr data-suche="([^"]*)"', seite)),
           "der Suchtext enthält die normalisierte Form des Kennzeichens")

    print("Material löschen")
    status, ort, _ = anfrage("POST", "/helfer/material/%d/loeschen" % FUNK, {"csrf": CSRF})
    pruefe("hinweis=material-ausgegeben" in ort and zeilen("SELECT 1 FROM material WHERE id = ?", FUNK),
           "was schon herausging, bleibt")
    anfrage("POST", "/helfer/material", {"csrf": CSRF, "name": "Vertippt"})
    tipp = zeilen("SELECT id FROM material WHERE name = 'Vertippt'")[0][0]
    status, ort, _ = anfrage("POST", "/helfer/material/%d/loeschen" % tipp, {"csrf": CSRF})
    pruefe("hinweis=material-weg" in ort and not zeilen("SELECT 1 FROM material WHERE id = ?", tipp),
           "was nie herausging, lässt sich löschen")

    print("Löschen")
    status, ort, _ = anfrage("POST", "/helfer/ausgabe/%d/loeschen" % sid, {"csrf": CSRF})
    pruefe("hinweis=geloescht" in ort and not zeilen("SELECT 1 FROM ausgabe WHERE id = ?", sid)
           and not zeilen("SELECT 1 FROM ausgabe_posten WHERE ausgabe_id = ?", sid),
           "Vorgang samt Posten weg")

    print("Fahrzeug aus dem Stamm nehmen")
    # Loeschte man ein Fahrzeug mit Vorgaengen, waere die Ausgabehistorie still
    # weg - und die Unterschriften dazu zeigten ins Leere.
    mit = zeilen("SELECT f.id FROM fahrzeug f WHERE EXISTS"
                 " (SELECT 1 FROM ausgabe_posten p WHERE p.fahrzeug_id = f.id)")[0][0]
    status, ort, _ = anfrage("POST", "/helfer/fahrzeug/%d/loeschen" % mit, {"csrf": CSRF})
    pruefe("hinweis=fahrzeug-hat-vorgaenge" in ort, "mit Vorgaengen wird abgelehnt")
    pruefe(len(zeilen("SELECT id FROM fahrzeug WHERE id = ?", mit)) == 1,
           "und nichts ist verschwunden")

    # Der Fall, um den es geht: ein Vertipper. Er kommt beim Ausgeben in den
    # Stamm; wird der Vorgang geloescht, bleibt das Fahrzeug allein zurueck.
    anfrage("POST", "/helfer/ausgabe",
            {"csrf": CSRF, "name": "Vertippt", "n-%d" % SCHLUESSEL: "IL-ZZ 999"})
    tipp = zeilen("SELECT id FROM fahrzeug WHERE kennzeichen_norm = 'ILZZ999'")[0][0]
    falsch = zeilen("SELECT ausgabe_id FROM ausgabe_posten WHERE fahrzeug_id = ?", tipp)[0][0]
    anfrage("POST", "/helfer/ausgabe/%d/loeschen" % falsch, {"csrf": CSRF})
    status, ort, _ = anfrage("POST", "/helfer/fahrzeug/%d/loeschen" % tipp, {"csrf": CSRF})
    pruefe("hinweis=fahrzeug-weg" in ort
           and not zeilen("SELECT id FROM fahrzeug WHERE id = ?", tipp),
           "ohne Vorgaenge geht es")
    status, ort, _ = anfrage("POST", "/helfer/fahrzeug/999999/loeschen", {"csrf": CSRF})
    pruefe("hinweis=unbekannt" in ort, "ein Fahrzeug, das es nicht gibt")
    status, _, _ = anfrage("POST", "/helfer/fahrzeug/%d/loeschen" % mit, {"csrf": "falsch"})
    pruefe(status == 400, "ohne Token geht gar nichts")
    _, _, seite = anfrage("GET", "/helfer/ausgabe")
    pruefe("hat Vorgänge" in seite, "in der Liste steht statt des Knopfes, warum es nicht geht")

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
