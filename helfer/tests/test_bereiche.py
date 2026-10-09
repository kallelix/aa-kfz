"""Bereiche, Schichten und Goodies pflegen (Lastenheft 2.1, V-03 bis V-07),
dazu die Bereichsleitung als Konto (2.1a, B-02).

    python helfer/tests/test_bereiche.py

Erst das Prüfen der Formularwerte ohne Server, dann die Migration der
bisherigen Listen in Bereiche, zuletzt alles über HTTP – einschließlich der
Vorlage aus einer früheren Veranstaltung.
"""

import http.client
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.parse
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WURZEL))
sys.path.insert(0, str(WURZEL.parent))
from kern import db as kern_db  # noqa: E402
from kern import testdb  # noqa: E402
from kern import veranstaltungen as va  # noqa: E402
from kern.konten import Konten  # noqa: E402

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


def tupel(zeilen):
    return [tuple(z.values()) for z in zeilen]


def freier_hafen():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


db_url = testdb.wegwerf("helfer_bereiche")
os.environ["DATABASE_URL"] = db_url

from app import db, planung  # noqa: E402

# --- Prüfen ohne Datenbank -------------------------------------------------

print("Bereich prüfen")
werte, f = planung.bereich_pruefen({
    "name": "  Shuttle ", "mindestalter": "18", "intern": "1",
    "voraussetzungen": "Führerschein Klasse B\n\n  seit einem Jahr  \n"})
pruefe(not f and werte["name"] == "Shuttle", "ein vollständiger Bereich geht durch")
pruefe(werte["mindestalter"] == 18 and werte["intern"] == 1, "Alter und intern")
pruefe(werte["voraussetzungen"] == "Führerschein Klasse B\nseit einem Jahr",
       "Voraussetzungen: eine je Zeile, Leerzeilen fallen weg")
_, f = planung.bereich_pruefen({"name": ""})
pruefe("name" in f, "ohne Namen nicht")
_, f = planung.bereich_pruefen({"name": "X", "mindestalter": "zwölf"})
pruefe("mindestalter" in f, "ein Alter in Worten wird gemeldet")
werte, f = planung.bereich_pruefen({"name": "X", "mindestalter": ""})
pruefe(not f and werte["mindestalter"] is None, "ohne Alter: keine Grenze")

print("Schicht prüfen")
GUT = {"datum": "2027-07-02", "beginn": "08:00", "ende": "12:00", "soll": "4"}
werte, f = planung.schicht_pruefen(GUT)
pruefe(not f, "eine vollständige Schicht geht durch")
pruefe(werte["beginn"] == "2027-07-02 08:00" and werte["ende"] == "2027-07-02 12:00",
       "Beginn und Ende werden zusammengesetzt")
pruefe(werte["minimum"] == 4 and werte["reserve"] == 0,
       "ohne Minimum gilt das Soll, ohne Reserve null")
werte, _ = planung.schicht_pruefen({**GUT, "beginn": "20:00", "ende": "02:00"})
pruefe(werte["ende"] == "2027-07-03 02:00" and werte["datum"] == "2027-07-02",
       "über Mitternacht: Ende am Folgetag, einsortiert beim Vortag")
_, f = planung.schicht_pruefen({**GUT, "minimum": "5"})
pruefe("minimum" in f, "das Minimum darf nicht über dem Soll liegen")
_, f = planung.schicht_pruefen({**GUT, "soll": ""})
pruefe("soll" in f, "ohne Soll nicht")
_, f = planung.schicht_pruefen({**GUT, "soll": "0"})
pruefe("soll" in f, "ein Soll von null ist keine Schicht")
_, f = planung.schicht_pruefen({**GUT, "ende": "08:00"})
pruefe("ende" in f, "Beginn gleich Ende geht nicht")
_, f = planung.schicht_pruefen({**GUT, "datum": ""})
pruefe("datum" in f, "ohne Tag nicht")
_, f = planung.schicht_pruefen({**GUT, "reserve": "-1"})
pruefe("reserve" in f, "eine negative Reserve wird gemeldet")
werte, f = planung.schicht_pruefen({**GUT, "minimum": "0", "reserve": "2",
                                    "mindestalter": "16"})
pruefe(not f and werte["minimum"] == 0 and werte["reserve"] == 2
       and werte["mindestalter"] == 16, "Minimum null, Reserve und Alter gehen")

print("Goodie prüfen")
werte, f = planung.goodie_pruefen({"name": "Ein Bier am Bierwagen", "schwelle": "2",
                                   "schwelle_art": "schichten", "mindestalter": "16",
                                   "alternative": "Eine Eistüte"})
pruefe(not f and werte["ab_schichten"] == 2 and werte["ab_stunden"] is None,
       "ab zwei Schichten, mit Alternative")
werte, f = planung.goodie_pruefen({"name": "Cap", "schwelle": "8", "schwelle_art": "stunden"})
pruefe(not f and werte["ab_stunden"] == 8 and werte["ab_schichten"] is None,
       "nach Stunden geht auch")
_, f = planung.goodie_pruefen({"name": "Bier", "schwelle": "1", "alternative": "Eis"})
pruefe("alternative" in f, "eine Alternative ohne Altersgrenze bekäme niemand")
_, f = planung.goodie_pruefen({"name": "Bier"})
pruefe("schwelle" in f, "ohne Schwelle nicht")

print("Verschieben")
pruefe(planung.verschieben("2026-08-29 08:00", 307) == "2027-07-02 08:00",
       "ein Zeitpunkt wandert um ganze Tage")
pruefe(planung.verschieben("2026-08-29", -1) == "2026-08-28", "ein Tag auch rückwärts")

# --- Migration: aus Listen werden Bereiche ----------------------------------

print("Migration der Listen")
alt_url = testdb.wegwerf("helfer_bereiche_alt")
va.Veranstaltungen(lambda: alt_url).init()
nur_anfang = Path(tempfile.mkdtemp())
try:
    shutil.copy(WURZEL / "app" / "migrationen" / "0001_anfang.sql", nur_anfang)
    kern_db.migrieren(alt_url, "helfer", nur_anfang)
finally:
    shutil.rmtree(nur_anfang, ignore_errors=True)
alt_va = va.Veranstaltungen(lambda: alt_url).anlegen(
    {"name": "AA 2026", "kurz": "AA 2026", "beginn": "2026-08-28", "ende": "2026-08-30"})
con = kern_db.verbinden(alt_url, "helfer")
with con:
    for liste, beginn, ende, bedarf in (("Shuttle", "08:00", "12:00", 3),
                                        ("Shuttle", "12:00", "16:00", 2),
                                        ("Orgabüro", "09:00", "18:00", 1)):
        con.execute(
            "INSERT INTO schicht (veranstaltung_id, liste, beginn, ende, datum, bedarf,"
            " angelegt_am) VALUES (?, ?, ?, ?, '2026-08-29', ?, '2026-01-01 00:00:00')",
            (alt_va, liste, "2026-08-29 " + beginn, "2026-08-29 " + ende, bedarf))
con.close()
eingespielt = kern_db.migrieren(alt_url, "helfer", WURZEL / "app" / "migrationen")
pruefe(eingespielt == ["0002_bereiche.sql"], "die neue Migration läuft auf alten Bestand")
pruefe(tupel(testdb.abfrage(alt_url, "helfer", "SELECT name FROM bereich ORDER BY name"))
       == [("Orgabüro",), ("Shuttle",)], "aus jeder Liste wird ein Bereich")
pruefe(tupel(testdb.abfrage(
           alt_url, "helfer", "SELECT b.name, s.minimum, s.soll, s.reserve FROM schicht s"
           " JOIN bereich b ON b.id = s.bereich_id ORDER BY s.beginn, b.name"))
       == [("Shuttle", 3, 3, 0), ("Orgabüro", 1, 1, 0), ("Shuttle", 2, 2, 0)],
       "der Bedarf wird Soll und Minimum, Reserve null")

# --- Über HTTP --------------------------------------------------------------

db.init()
VA = db.VERANSTALTUNGEN.anlegen({"name": "Die absolute Abfahrt 2026", "kurz": "AA 2026",
                                 "beginn": "2026-08-28", "ende": "2026-08-30",
                                 "ort": "Ilmenau", "status": "archiviert"})
NEU = db.VERANSTALTUNGEN.anlegen({"name": "Die absolute Abfahrt 2027", "kurz": "AA 2027",
                                  "beginn": "2027-07-02", "ende": "2027-07-04",
                                  "ort": "Ilmenau"})
# Kalle leitet den Shuttle. Sein Konto hat noch kein Passwort: solange es
# keinen Admin mit Passwort gibt, gilt das gemeinsame, mit dem der Test beginnt.
KONTEN = Konten(lambda: db_url)
KALLE = KONTEN.anlegen(email="kalle@example.org", name="Kalle Beispiel", kuerzel="KB",
                       rolle="bereichsleitung", telefon="0151 000000")
hafen = freier_hafen()

prozess = subprocess.Popen(
    [str(PYTHON), "-m", "app"],
    cwd=str(WURZEL),
    env={**os.environ, "DATABASE_URL": db_url, "BIND": f"127.0.0.1:{hafen}",
         "ADMIN_PASSWORD_HASH": HASH, "APP_SECRET_KEY": "test-schluessel",
         "COOKIE_SECURE": "0", "ZEITPLAN_SERIEN": "", "JETZT_FEST": "2026-08-20 10:00",
         "PYTHONIOENCODING": "utf-8"},
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)


def zeilen(sql, *parameter):
    """Die Zeilen als Tupel – zum Vergleichen mit erwarteten Werten."""
    return tupel(testdb.abfrage(db_url, "helfer", sql, parameter))


try:
    for _ in range(100):
        try:
            with socket.create_connection(("127.0.0.1", hafen), timeout=0.2):
                break
        except OSError:
            time.sleep(0.1)
    else:
        raise RuntimeError("Server ist nicht hochgekommen")

    # Zwei Kekse: die Sitzung und die gewählte Veranstaltung. Ein zweites
    # Glas für einen zweiten Browser – die Bereichsleitung.
    kekse = {}

    def anfrage(methode, pfad, daten=None, glas=None):
        glas = kekse if glas is None else glas
        verbindung = http.client.HTTPConnection("127.0.0.1", hafen, timeout=10)
        koerper = urllib.parse.urlencode(daten, doseq=True).encode() if daten else None
        kopf = {}
        if koerper is not None:
            kopf["Content-Type"] = "application/x-www-form-urlencoded"
        if glas:
            kopf["Cookie"] = "; ".join(k + "=" + w for k, w in glas.items())
        verbindung.request(methode, pfad, body=koerper, headers=kopf)
        antwort = verbindung.getresponse()
        for gesetzt in antwort.headers.get_all("Set-Cookie") or []:
            name, _, wert = gesetzt.split(";")[0].partition("=")
            glas[name] = wert
        ergebnis = (antwort.status, antwort.getheader("Location", ""),
                    antwort.read().decode("utf-8"))
        verbindung.close()
        return ergebnis

    print("Ohne Anmeldung")
    for pfad in ("/helfer/bereiche", "/helfer/bereich/neu", "/helfer/goodies"):
        status, ort, _ = anfrage("GET", pfad)
        pruefe(status == 303 and ort.startswith("/helfer/login"), pfad + " führt zur Anmeldung")

    anfrage("POST", "/helfer/login", {"passwort": "test-passwort-123", "kuerzel": "KK",
                                      "weiter": "/helfer"})
    # Am 20.08.2026 ist ohne Wahl die AA 2026 dran; gepflegt wird zuerst sie.
    anfrage("GET", "/helfer/veranstaltung?id=" + str(VA))
    status, _, seite = anfrage("GET", "/helfer/bereiche")
    pruefe(status == 200 and "noch keinen Bereich" in seite, "leere Bereichsliste")
    CSRF = re.search(r'name="csrf" value="([^"]+)"', seite).group(1)
    pruefe('href="/helfer/bereiche"' in seite and 'href="/helfer/goodies"' in seite,
           "Bereiche und Goodies stehen in der Navigation")
    pruefe("Aus einer früheren Veranstaltung" not in seite,
           "ohne frühere Bereiche keine Vorlage zum Übernehmen")

    print("Bereich anlegen")
    status, ort, _ = anfrage("POST", "/helfer/bereich/neu", {
        "csrf": CSRF, "name": "Shuttle", "treffpunkt": "Parkplatz Talstation",
        "leitung": str(KALLE), "mindestalter": "18",
        "voraussetzungen": "Führerschein Klasse B",
        "beschreibung": "Ihr fahrt die Rennfahrer auf den Berg."})
    pruefe(status == 303 and "hinweis=angelegt" in ort, "Shuttle angelegt")
    SHUTTLE = int(re.search(r"/helfer/bereich/(\d+)", ort).group(1))
    status, _, seite = anfrage("POST", "/helfer/bereich/neu", {"csrf": CSRF, "name": "Shuttle"})
    pruefe(status == 400 and "gibt es in AA 2026 schon" in seite,
           "derselbe Name kommt mit Meldung zurück")
    status, _, seite = anfrage("POST", "/helfer/bereich/neu",
                               {"csrf": CSRF, "name": "", "treffpunkt": "nicht verlieren"})
    pruefe(status == 400 and "nicht verlieren" in seite,
           "ohne Namen kommt das Formular mit der Eingabe zurück")
    status, ort, _ = anfrage("POST", "/helfer/bereich/neu", {
        "csrf": CSRF, "name": "Orgabüro", "intern": "1"})
    ORGA = int(re.search(r"/helfer/bereich/(\d+)", ort).group(1))
    status, _, _ = anfrage("POST", "/helfer/bereich/neu", {"csrf": "falsch", "name": "X"})
    pruefe(status == 400 and len(zeilen("SELECT id FROM bereich")) == 2,
           "ohne CSRF-Token wird nichts angelegt")

    print("Schichten anlegen")
    status, _, seite = anfrage("GET", "/helfer/bereich/%d/schicht/neu" % SHUTTLE)
    pruefe(status == 200 and 'value="2026-08-28"' in seite,
           "das Formular schlägt den ersten Tag vor")
    pruefe("Freitag, 28.08.2026" in seite, "und bietet die Tage der Veranstaltung an")
    for datum, von, bis, minimum, soll, reserve in (
            ("2026-08-29", "08:00", "12:00", "2", "3", "1"),
            ("2026-08-29", "12:00", "16:00", "", "2", ""),
            ("2026-08-29", "20:00", "02:00", "1", "1", "0")):
        status, ort, _ = anfrage("POST", "/helfer/bereich/%d/schicht/neu" % SHUTTLE, {
            "csrf": CSRF, "datum": datum, "beginn": von, "ende": bis,
            "minimum": minimum, "soll": soll, "reserve": reserve})
        pruefe(status == 303 and "hinweis=angelegt" in ort, "Shuttle " + von + "–" + bis)
    pruefe(zeilen("SELECT minimum, soll, reserve FROM schicht ORDER BY beginn")
           == [(2, 3, 1), (2, 2, 0), (1, 1, 0)], "Minimum, Soll und Reserve stehen drin")
    pruefe(zeilen("SELECT ende FROM schicht WHERE beginn = '2026-08-29 20:00'")
           == [("2026-08-30 02:00",)], "die Nachtschicht endet am Folgetag")

    status, _, seite = anfrage("POST", "/helfer/bereich/%d/schicht/neu" % SHUTTLE, {
        "csrf": CSRF, "datum": "2026-08-29", "beginn": "08:00", "ende": "12:00", "soll": "1"})
    pruefe(status == 400 and "schon eine Schicht" in seite,
           "dieselbe Zeit im selben Bereich gibt es nur einmal")
    status, _, seite = anfrage("POST", "/helfer/bereich/%d/schicht/neu" % SHUTTLE, {
        "csrf": CSRF, "datum": "2026-08-30", "beginn": "08:00", "ende": "12:00",
        "minimum": "5", "soll": "3", "hinweis": "nicht verlieren"})
    pruefe(status == 400 and "über dem Soll" in seite and "nicht verlieren" in seite,
           "Minimum über Soll kommt mit der Eingabe zurück")

    status, ort, _ = anfrage("POST", "/helfer/bereich/%d/schicht/neu" % ORGA, {
        "csrf": CSRF, "datum": "2026-08-27", "beginn": "09:00", "ende": "18:00", "soll": "2"})
    pruefe(status == 303, "eine Aufbauschicht vor dem ersten Tag geht")

    print("Schichtliste und Bereich")
    _, _, seite = anfrage("GET", "/helfer/schichten")
    pruefe(seite.count("<tr data-suche=") == 4, "alle vier Schichten in der Liste")
    pruefe(seite.count('<span class="marke">intern</span>') == 1,
           "die Schicht des internen Orgabüros ist markiert")
    _, _, seite = anfrage("GET", "/helfer/schichten?bereich=%d" % SHUTTLE)
    pruefe(seite.count("<tr data-suche=") == 3, "Filter nach Bereich")
    _, _, seite = anfrage("GET", "/helfer/bereiche")
    pruefe("Parkplatz Talstation" in seite and "Kalle Beispiel" in seite
           and "0151 000000" in seite and "ab 18" in seite,
           "die Übersicht zeigt Treffpunkt, Leitung samt Nummer aus dem Konto und Alter")
    _, _, seite = anfrage("GET", "/helfer/bereich/%d" % SHUTTLE)
    pruefe(seite.count("/aendern") == 3 and "kopieren" in seite,
           "der Bereich zeigt seine Schichten zum Ändern und Kopieren")
    schicht_frueh = zeilen("SELECT id FROM schicht WHERE beginn = '2026-08-29 08:00'")[0][0]
    _, _, seite = anfrage("GET", "/helfer/bereich/%d/schicht/neu?von=%d" % (SHUTTLE, schicht_frueh))
    pruefe('value="08:00"' in seite and 'name="soll"' in seite
           and re.search(r'name="soll"[^>]*value="3"', seite.replace("\n", " ")),
           "Kopieren füllt das Formular mit der Vorlage")

    print("Schicht ändern")
    _, _, seite = anfrage("GET", "/helfer/schicht/%d" % schicht_frueh)
    pruefe("Minimum 2, Soll 3, dazu 1 Reserve" in seite and "ab 18" in seite,
           "die Einteilungsseite zeigt Zahlen und Alter")
    status, ort, _ = anfrage("POST", "/helfer/schicht/%d/aendern" % schicht_frueh, {
        "csrf": CSRF, "bereich_id": str(SHUTTLE), "datum": "2026-08-29", "beginn": "07:30",
        "ende": "12:00", "minimum": "2", "soll": "4", "reserve": "1", "mindestalter": "16"})
    pruefe(status == 303 and "hinweis=alter-gesenkt" in ort,
           "ein Alter unter dem des Bereichs wird gespeichert, aber angemerkt")
    pruefe(zeilen("SELECT beginn, soll, mindestalter FROM schicht WHERE id = ?",
                  schicht_frueh) == [("2026-08-29 07:30", 4, 16)], "geändert")
    status, ort, _ = anfrage("POST", "/helfer/schicht/%d/aendern" % schicht_frueh, {
        "csrf": CSRF, "bereich_id": str(ORGA), "datum": "2026-08-29", "beginn": "07:30",
        "ende": "12:00", "soll": "4"})
    pruefe(status == 303 and zeilen("SELECT bereich_id FROM schicht WHERE id = ?",
                                    schicht_frueh) == [(ORGA,)],
           "eine Schicht kann den Bereich wechseln")

    print("Löschen mit Bedacht")
    con = db.verbinden()
    with con:
        anna, _ = db.helfer_anlegen(con, {"name": "Anna Berg", "email": "anna@example.org"})
    con.close()
    db.einteilen(schicht_frueh, anna)
    status, ort, _ = anfrage("POST", "/helfer/schicht/%d/loeschen" % schicht_frueh,
                             {"csrf": CSRF})
    pruefe("hinweis=schicht-besetzt" in ort and zeilen(
        "SELECT id FROM schicht WHERE id = ?", schicht_frueh),
        "eine besetzte Schicht bleibt stehen")
    status, ort, _ = anfrage("POST", "/helfer/bereich/%d/loeschen" % ORGA, {"csrf": CSRF})
    pruefe("hinweis=bereich-nicht-leer" in ort, "ein Bereich mit Schichten bleibt stehen")
    status, ort, _ = anfrage("POST", "/helfer/bereich/neu", {"csrf": CSRF, "name": "Leer"})
    leer = int(re.search(r"/helfer/bereich/(\d+)", ort).group(1))
    status, ort, _ = anfrage("POST", "/helfer/bereich/%d/loeschen" % leer, {"csrf": CSRF})
    pruefe("hinweis=geloescht" in ort and not zeilen("SELECT id FROM bereich WHERE id = ?", leer),
           "ein leerer Bereich geht weg")

    print("Shirt, Verpflegung, Goodies")
    _, _, seite = anfrage("GET", "/helfer/goodies")
    pruefe(re.search(r'name="verpflegung" value="1" checked', seite)
           and not re.search(r'name="shirt" value="1" checked', seite),
           "Vorgabe: Verpflegung ja, Shirt nein")
    anfrage("POST", "/helfer/goodies/angebot", {"csrf": CSRF, "shirt": "1", "party": "1"})
    pruefe(db.angebot(VA) == {"shirt": 1, "verpflegung": 0, "party": 1}, "Angebot gespeichert")
    status, ort, _ = anfrage("POST", "/helfer/goodie/neu", {
        "csrf": CSRF, "name": "Ein Bier am Bierwagen", "schwelle": "2",
        "schwelle_art": "schichten", "mindestalter": "16", "alternative": "Eine Eistüte"})
    pruefe(status == 303, "Goodie angelegt")
    status, _, seite = anfrage("POST", "/helfer/goodie/neu", {
        "csrf": CSRF, "name": "Eis", "schwelle": "1", "alternative": "Wasser"})
    pruefe(status == 400 and "Wasser" in seite, "Alternative ohne Alter kommt zurück")
    anfrage("POST", "/helfer/goodie/neu", {"csrf": CSRF, "name": "ILRC-Cap",
                                           "schwelle": "4", "schwelle_art": "schichten"})
    _, _, seite = anfrage("GET", "/helfer/goodies")
    pruefe(seite.index("Ein Bier am Bierwagen") < seite.index("ILRC-Cap")
           and "ab 16, sonst Eine Eistüte" in seite, "nach Schwelle sortiert, mit Alternative")
    cap = zeilen("SELECT id FROM goodie WHERE name = 'ILRC-Cap'")[0][0]
    anfrage("POST", "/helfer/goodie/%d" % cap, {"csrf": CSRF, "name": "ILRC-Cap",
                                                "schwelle": "12", "schwelle_art": "stunden"})
    pruefe(zeilen("SELECT ab_schichten, ab_stunden FROM goodie WHERE id = ?", cap)
           == [(None, 12)], "von Schichten auf Stunden umgestellt")

    print("Vorlage für die nächste Veranstaltung")
    anfrage("GET", "/helfer/veranstaltung?id=" + str(NEU))
    _, _, seite = anfrage("GET", "/helfer/bereiche")
    pruefe("Aus einer früheren Veranstaltung" in seite and "AA 2026 – 2 Bereiche" in seite,
           "die AA 2026 wird als Vorlage angeboten")
    status, ort, _ = anfrage("POST", "/helfer/bereiche/vorlage", {"csrf": CSRF, "von": str(VA)})
    hinweis = urllib.parse.unquote_plus(ort)
    pruefe(status == 303 and "2 Bereiche, 4 Schichten, 2 Goodies" in hinweis
           and "308 Tage später" in hinweis, "Meldung: " + hinweis[hinweis.find("=") + 1:])
    neu_schichten = zeilen("SELECT s.beginn, s.ende, s.datum, b.name FROM schicht s"
                           " JOIN bereich b ON b.id = s.bereich_id"
                           " WHERE s.veranstaltung_id = ? ORDER BY s.beginn", NEU)
    pruefe(neu_schichten[0] == ("2027-07-01 09:00", "2027-07-01 18:00", "2027-07-01", "Orgabüro"),
           "die Aufbauschicht liegt wieder einen Tag vor dem ersten")
    pruefe(("2027-07-03 20:00", "2027-07-04 02:00", "2027-07-03", "Shuttle") in neu_schichten,
           "die Nachtschicht wandert mit")
    pruefe(zeilen("SELECT COUNT(*) FROM einteilung e JOIN schicht s ON s.id = e.schicht_id"
                  " WHERE s.veranstaltung_id = ?", NEU) == [(0,)],
           "wer damals eingeteilt war, kommt nicht mit")
    pruefe(zeilen("SELECT treffpunkt, mindestalter, voraussetzungen FROM bereich"
                  " WHERE veranstaltung_id = ? AND name = 'Shuttle'", NEU)
           == [("Parkplatz Talstation", 18, "Führerschein Klasse B")],
           "die Angaben zum Bereich kommen mit")
    pruefe(db.angebot(NEU) == {"shirt": 1, "verpflegung": 0, "party": 1},
           "das Angebot kommt mit")
    pruefe(zeilen("SELECT bl.konto_id FROM bereich_leitung bl"
                  " JOIN bereich b ON b.id = bl.bereich_id"
                  " WHERE b.veranstaltung_id = ? AND b.name = 'Shuttle'", NEU) == [(KALLE,)],
           "die Bereichsleitung kommt mit")
    status, ort, _ = anfrage("POST", "/helfer/bereiche/vorlage", {"csrf": CSRF, "von": str(VA)})
    pruefe("hinweis=vorlage-nicht" in ort and zeilen(
        "SELECT COUNT(*) FROM bereich WHERE veranstaltung_id = ?", NEU) == [(2,)],
        "ein zweites Übernehmen geht nicht")

    print("Bereichsleitung")
    # Ab jetzt mit Konten: ein Admin mit Passwort schließt das gemeinsame.
    KONTEN.anlegen(email="ada@example.org", name="Ada Admin", kuerzel="AD",
                   rolle="admin", passwort="ein-langes-passwort")
    KONTEN.passwort_setzen(KALLE, "kalles-langes-passwort")
    status, ort, _ = anfrage("GET", "/helfer/bereiche")
    pruefe(status == 303 and "login" in ort, "das gemeinsame Passwort gilt nicht mehr")
    kalle = {}
    anfrage("POST", "/helfer/login", {"email": "kalle@example.org",
                                      "passwort": "kalles-langes-passwort",
                                      "weiter": "/helfer"}, glas=kalle)
    anfrage("GET", "/helfer/veranstaltung?id=" + str(VA), glas=kalle)
    status, ort, _ = anfrage("GET", "/helfer", glas=kalle)
    pruefe(status == 303 and ort.endswith("/helfer/bereiche"),
           "die Übersicht führt eine Bereichsleitung zu ihren Bereichen")
    status, _, seite = anfrage("GET", "/helfer/bereiche", glas=kalle)
    pruefe(status == 200 and 'href="/helfer/bereich/%d"' % SHUTTLE in seite
           and 'href="/helfer/bereich/%d"' % ORGA not in seite,
           "sie sieht nur den Bereich, den sie leitet")
    pruefe("/helfer/bereich/neu" not in seite and "/helfer/goodies" not in seite,
           "und legt keine neuen an")
    pruefe("Meine Bereiche" in seite and "/helfer/funk" not in seite
           and "Einstellungen" not in seite
           and "/veranstaltungen" not in seite and "data-takt" not in seite,
           "Navigation nur mit ihren Punkten, ohne Tablet-Nachfragen")
    kcsrf = re.search(r'name="csrf" value="([^"]+)"',
                      anfrage("GET", "/helfer/bereich/%d" % SHUTTLE, glas=kalle)[2]).group(1)
    _, _, seite = anfrage("GET", "/helfer/schichten", glas=kalle)
    pruefe(seite.count("<tr data-suche=") == 2, "in der Schichtliste nur die des Shuttles")
    for pfad in ("/helfer/bereich/%d" % ORGA, "/helfer/schicht/%d" % schicht_frueh,
                 "/helfer/bereich/neu", "/helfer/helfer", "/helfer/funk",
                 "/helfer/goodies", "/helfer/import", "/helfer/stand", "/helfer/band",
                 "/helfer/helfer/export.csv"):
        status, _, seite = anfrage("GET", pfad, glas=kalle)
        pruefe(status == 403 and "Als Bereichsleitung" in seite, pfad + " bleibt zu")

    shuttle_mittag = zeilen("SELECT id FROM schicht WHERE bereich_id = ?"
                            " AND beginn = '2026-08-29 12:00'", SHUTTLE)[0][0]
    _, _, seite = anfrage("GET", "/helfer/schicht/%d" % shuttle_mittag, glas=kalle)
    pruefe("Anna Berg" in seite and "anna@example.org" not in seite,
           "beim Einteilen nur Namen, keine Adressen fremder Leute")
    status, ort, _ = anfrage("POST", "/helfer/schicht/%d/einteilen" % shuttle_mittag,
                             {"csrf": kcsrf, "helfer_id": str(anna)}, glas=kalle)
    pruefe("hinweis=eingeteilt" in ort, "sie teilt jemanden in ihre Schicht ein")
    status, _, seite = anfrage("GET", "/helfer/helfer/%d" % anna, glas=kalle)
    pruefe(status == 200 and "Shuttle" in seite and "Orgabüro" not in seite,
           "die Person sieht sie – mit den Schichten ihres Bereichs, nicht den anderen")
    fremd = zeilen("SELECT id FROM einteilung WHERE schicht_id = ?", schicht_frueh)[0][0]
    status, _, _ = anfrage("POST", "/helfer/einteilung/%d/austragen" % fremd,
                           {"csrf": kcsrf}, glas=kalle)
    pruefe(status == 403 and zeilen("SELECT id FROM einteilung WHERE id = ?", fremd),
           "aus fremden Schichten trägt sie niemanden aus")
    status, _, _ = anfrage("POST", "/helfer/bereich/%d/loeschen" % SHUTTLE,
                           {"csrf": kcsrf}, glas=kalle)
    pruefe(status == 403, "ihren Bereich löscht sie nicht")
    status, ort, _ = anfrage("POST", "/helfer/bereich/%d" % SHUTTLE, {
        "csrf": kcsrf, "name": "Shuttle", "treffpunkt": "Parkplatz Talstation, Tor 2",
        "mindestalter": "18", "voraussetzungen": "Führerschein Klasse B"}, glas=kalle)
    pruefe("hinweis=gespeichert" in ort
           and zeilen("SELECT treffpunkt FROM bereich WHERE id = ?", SHUTTLE)
           == [("Parkplatz Talstation, Tor 2",)], "die Angaben ändert sie selbst")
    pruefe(zeilen("SELECT konto_id FROM bereich_leitung WHERE bereich_id = ?", SHUTTLE)
           == [(KALLE,)], "wer leitet, bleibt dabei stehen")
    anfrage("POST", "/helfer/schicht/%d/aendern" % shuttle_mittag, {
        "csrf": kcsrf, "bereich_id": str(ORGA), "datum": "2026-08-29", "beginn": "12:00",
        "ende": "16:00", "soll": "2"}, glas=kalle)
    pruefe(zeilen("SELECT bereich_id FROM schicht WHERE id = ?", shuttle_mittag)
           == [(SHUTTLE,)], "in einen fremden Bereich schiebt sie keine Schicht")

    ada = {}
    anfrage("POST", "/helfer/login", {"email": "ada@example.org",
                                      "passwort": "ein-langes-passwort",
                                      "weiter": "/helfer"}, glas=ada)
    anfrage("GET", "/helfer/veranstaltung?id=" + str(VA), glas=ada)
    _, _, seite = anfrage("GET", "/helfer/bereiche", glas=ada)
    pruefe("Orgabüro" in seite and "/helfer/bereich/neu" in seite,
           "der Admin sieht weiter alles")
    _, _, seite = anfrage("GET", "/helfer/bereich/%d" % ORGA, glas=ada)
    pruefe('name="leitung" value="%d"' % KALLE in seite and "Ada Admin" in seite,
           "zur Wahl stehen alle Konten mit Zugang zum Helferbereich")

    print("Veranstaltung löschen")
    meldung = ""
    try:
        db.VERANSTALTUNGEN.loeschen(NEU)
    except va.Fehler as ausnahme:
        meldung = str(ausnahme)
    pruefe("Bereiche" in meldung and db.VERANSTALTUNGEN.laden(NEU) is not None,
           "eine Veranstaltung mit Bereichen lässt sich nicht löschen: " + meldung)

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
