"""Abruf der Helferliste statt Hochladen der beiden CSV-Dateien.

    python helfer/tests/test_abruf.py

Ohne Netz: an die Stelle des Öffners tritt ein nachgebauter, der aufschreibt,
was abgerufen wurde, und vorbereitete Antworten zurückgibt. Geprüft wird
dadurch die Logik, auf die es ankommt – Reihenfolge, gemeinsame Sitzung,
Erkennen der Anmeldeseite –, und nicht, ob urllib funktioniert.

Die echten Adressen stehen hier nirgends: sie enthalten Zugangstoken und das
Repository ist öffentlich. Der erfundene Token unten dient dazu, zu prüfen,
dass er in keine Meldung gerät.
"""

import os
import sqlite3
import sys
import tempfile
import uuid
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WURZEL))

verzeichnis = Path(tempfile.mkdtemp(prefix="helfer-abruf-"))
os.environ["DB_PATH"] = str(verzeichnis / "abruf.db")
os.environ["APP_SECRET_KEY"] = "test-schluessel"
os.environ["TAGE"] = "2026-08-28,2026-08-29,2026-08-30"

from app import config, csv_import, db  # noqa: E402

fehler = []


def pruefe(bedingung, text):
    print(("  ok   " if bedingung else "  FEHL ") + text)
    if not bedingung:
        fehler.append(text)


# Ein erfundener Token. Er darf in keiner Fehlermeldung auftauchen - genau
# das wird unten geprueft.
TOKEN = "GEHEIM-" + uuid.uuid4().hex[:8]
LOGIN = "https://dienst.example/home.php?i=" + TOKEN
VERGEBEN = "https://dienst.example/helfer.php?t=" + TOKEN + "&download_csv=1"
OFFEN = "https://dienst.example/helfer.php?t=" + TOKEN + "&download_csv=2"

CSV_VERGEBEN = (
    "Name,Zusatz1,Zusatz2,Liste,Datum,Zeit,Aufgabe,Email,Phone\r\n"
    "Anna Berg,Damen M,vegetarisch,Streckenposten,28.08.2026,"
    "10:00 - 18:00,,anna@example.org,0170 1\r\n"
    "Bert Öhl,Herren L,,Streckenposten,28.08.2026,"
    "10:00 - 18:00,,bert@example.org,\r\n"
    "Clara Dorn,Damen S,,Shuttle,29.08.2026,08:00 - 12:00,Fahren,"
    "clara@example.org,\r\n"
).encode("utf-8")

CSV_OFFEN = (
    "Liste,Datum,Zeit,Aufgabe\r\n"
    "Streckenposten,28.08.2026,10:00 - 18:00,\r\n"
    "Shuttle,29.08.2026,08:00 - 12:00,Fahren\r\n"
).encode("utf-8")

ANMELDESEITE = (
    "<!DOCTYPE html><html><head><title>Login zur Helferliste</title></head>"
    "<body><form method=post><input name=vergessen></form></body></html>"
).encode("utf-8")


# --- Der nachgebaute Öffner -------------------------------------------------

class Antwort:
    """So viel von urlopen(), wie _seite_holen() anfasst."""

    def __init__(self, inhalt, typ="text/csv", ziel=None):
        self._inhalt = inhalt
        self._typ = typ
        self._ziel = ziel
        self.headers = self

    def read(self, groesse=-1):
        return self._inhalt

    def geturl(self):
        return self._ziel

    def get_content_type(self):
        return self._typ

    def __enter__(self):
        return self

    def __exit__(self, *rest):
        return False


class Oeffner:
    def __init__(self, antworten):
        self.antworten = antworten
        self.aufgerufen = []

    def open(self, anfrage, timeout=None):
        url = anfrage.full_url
        self.aufgerufen.append(url)
        for teil, antwort in self.antworten:
            if teil in url:
                antwort._ziel = antwort._ziel or url
                return antwort
        raise AssertionError("nicht vorgesehene Adresse: " + url)


def stellen(login_url=LOGIN, vergeben_url=VERGEBEN, offen_url=OFFEN,
            antworten=None):
    """Konfiguration und Öffner setzen, wie sie dieser Prüfung dienen."""
    config.IMPORT_LOGIN_URL = login_url
    config.IMPORT_URL_VERGEBEN = vergeben_url
    config.IMPORT_URL_OFFEN = offen_url
    config.IMPORT_ABRUF_MOEGLICH = bool(login_url and vergeben_url and offen_url)

    oeffner = Oeffner(antworten if antworten is not None else [
        ("home.php", Antwort(b"<html>Dashboard</html>", "text/html")),
        ("download_csv=1", Antwort(CSV_VERGEBEN)),
        ("download_csv=2", Antwort(CSV_OFFEN)),
    ])
    csv_import._oeffner = lambda: oeffner
    return oeffner


def zeilen(sql, *parameter):
    con = sqlite3.connect(os.environ["DB_PATH"])
    con.row_factory = sqlite3.Row
    try:
        return con.execute(sql, parameter).fetchall()
    finally:
        con.close()


db.init()

print("Ohne Konfiguration geht es nicht")
stellen(login_url="", vergeben_url="", offen_url="")
try:
    csv_import.abrufen("KK")
    pruefe(False, "es haette einen Fehler geben muessen")
except csv_import.Fehler as f:
    pruefe("IMPORT_LOGIN_URL" in str(f) and "IMPORT_URL_OFFEN" in str(f),
           "die Meldung nennt, was fehlt: " + str(f)[:70])

print("Zwei von drei Adressen reichen auch nicht")
stellen(offen_url="")
pruefe(not config.IMPORT_ABRUF_MOEGLICH,
       "ohne die dritte steht der Abruf gar nicht erst bereit")

print("Der Abruf")
oeffner = stellen()
bericht = csv_import.abrufen("KK")
pruefe([a.split("?")[0].rsplit("/", 1)[-1] for a in oeffner.aufgerufen]
       == ["home.php", "helfer.php", "helfer.php"],
       "drei Aufrufe: erst anmelden, dann die beiden Listen")
pruefe("download_csv=1" in oeffner.aufgerufen[1]
       and "download_csv=2" in oeffner.aufgerufen[2],
       "vergebene vor offenen Posten")
pruefe(bericht["zeilen_vergeben"] == 3 and bericht["zeilen_offen"] == 2,
       "die Zeilen sind gelesen: %d vergeben, %d offen"
       % (bericht["zeilen_vergeben"], bericht["zeilen_offen"]))
pruefe(bericht["bedarf"] == 5,
       "der Bedarf ist die Summe aus beiden Dateien: %d" % bericht["bedarf"])
pruefe(bericht["personen"] == 3, "drei Helfer")

print("Was im Protokoll steht")
lauf = zeilen("SELECT * FROM import_lauf ORDER BY id DESC LIMIT 1")[0]
pruefe(lauf["datei"] == "Helferliste (Abruf)",
       "ein fester Name, nicht der des Dienstes: " + lauf["datei"])
pruefe(TOKEN not in lauf["datei"] and TOKEN not in lauf["bericht"],
       "und nirgends der Token")
pruefe(lauf["kuerzel"] == "KK", "mit dem Kuerzel dessen, der abgerufen hat")

print("Derselbe Abruf ein zweites Mal")
vorher = zeilen("SELECT COUNT(*) FROM schicht")[0][0]
zweiter = csv_import.abrufen("KK")
pruefe(zeilen("SELECT COUNT(*) FROM schicht")[0][0] == vorher,
       "legt nichts doppelt an")
pruefe(zweiter["schichten_neu"] == 0 and zweiter["ersetzt"] == 3,
       "sondern ersetzt die Einteilungen des ersten Laufs")

print("Anmeldeseite statt Datei")
for name, antworten in (
        ("nach Kopfzeile text/html", [
            ("home.php", Antwort(b"<html>Dashboard</html>", "text/html")),
            ("download_csv=1", Antwort(ANMELDESEITE, "text/html")),
        ]),
        ("nach dem Inhalt, trotz text/csv", [
            ("home.php", Antwort(b"<html>Dashboard</html>", "text/html")),
            ("download_csv=1", Antwort(ANMELDESEITE, "text/csv")),
        ])):
    stellen(antworten=antworten)
    try:
        csv_import.abrufen("KK")
        pruefe(False, name + ": es haette einen Fehler geben muessen")
    except csv_import.Fehler as f:
        pruefe("Login-Link" in str(f) and "Vergebene Posten" in str(f),
               name + " – die Meldung sagt, was zu tun ist")
        pruefe(TOKEN not in str(f), "und verraet den Token nicht")

print("Nur https")
stellen(login_url=LOGIN.replace("https://", "http://"))
try:
    csv_import.abrufen("KK")
    pruefe(False, "es haette einen Fehler geben muessen")
except csv_import.Fehler as f:
    pruefe("https" in str(f), "http wird abgelehnt: " + str(f))
    pruefe(TOKEN not in str(f), "ohne den Token in der Meldung")

print("Auch eine Umleitung darf nicht aus https herausfuehren")
stellen(antworten=[
    ("home.php", Antwort(b"<html>Dashboard</html>", "text/html")),
    ("download_csv=1", Antwort(CSV_VERGEBEN, "text/csv",
                               ziel="http://dienst.example/anders.csv")),
])
try:
    csv_import.abrufen("KK")
    pruefe(False, "es haette einen Fehler geben muessen")
except csv_import.Fehler as f:
    pruefe("https" in str(f), "die Umleitung wird bemerkt: " + str(f)[:70])

print("Ein Fehler schreibt nichts")
staende = (zeilen("SELECT COUNT(*) FROM schicht")[0][0],
           zeilen("SELECT COUNT(*) FROM einteilung")[0][0],
           zeilen("SELECT COUNT(*) FROM import_lauf")[0][0])
pruefe(staende[2] == 2,
       "nach zwei geglueckten und vier gescheiterten Laeufen stehen zwei "
       "Vermerke da")

print()
if fehler:
    print("FEHLGESCHLAGEN (" + str(len(fehler)) + "):")
    for eintrag in fehler:
        print("  - " + eintrag)
    sys.exit(1)
print("alle Pruefungen bestanden")
print("Wegwerf-Datenbank lag in " + str(verzeichnis))
