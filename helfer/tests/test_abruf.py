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

print("Selbsttaetig: was nach einem Ausfall aussieht, wird nicht uebernommen")
# Eine Ausfuhr mit nur Kopfzeilen ist technisch tadellos - sie laeuft ohne
# Fehler durch, setzt aber jeden Bedarf auf null und loescht alle
# Einteilungen aus dem Import. Von Hand sieht man "0 Zeilen" im Bericht,
# einem Lauf um vier Uhr morgens sieht niemand zu.
ENDE = (chr(13) + chr(10)).encode()
NUR_KOPF_VERGEBEN = b"Name,Zusatz1,Zusatz2,Liste,Datum,Zeit,Aufgabe,Email,Phone" + ENDE
NUR_KOPF_OFFEN = b"Liste,Datum,Zeit,Aufgabe" + ENDE

stand = (zeilen("SELECT COUNT(*) FROM schicht")[0][0],
         zeilen("SELECT COUNT(*) FROM einteilung")[0][0],
         zeilen("SELECT SUM(bedarf) FROM schicht")[0][0])
stellen(antworten=[
    ("home.php", Antwort(b"<html>Dashboard</html>", "text/html")),
    ("download_csv=1", Antwort(NUR_KOPF_VERGEBEN)),
    ("download_csv=2", Antwort(NUR_KOPF_OFFEN)),
])
try:
    csv_import.abrufen("automatisch", automatisch=True)
    pruefe(False, "eine leere Ausfuhr haette abgelehnt werden muessen")
except csv_import.Fehler as f:
    pruefe("keine einzige Zeile" in str(f),
           "die leere Ausfuhr wird abgelehnt: " + str(f)[:60])
pruefe((zeilen("SELECT COUNT(*) FROM schicht")[0][0],
        zeilen("SELECT COUNT(*) FROM einteilung")[0][0],
        zeilen("SELECT SUM(bedarf) FROM schicht")[0][0]) == stand,
       "und der Bestand steht unveraendert da: " + str(stand))

# Dasselbe eine Stufe milder: die Haelfte fehlt.
HALB_VERGEBEN = (
    b"Name,Zusatz1,Zusatz2,Liste,Datum,Zeit,Aufgabe,Email,Phone" + ENDE
    + "Anna Berg,Damen M,,Streckenposten,28.08.2026,10:00 - 18:00,,anna@example.org,".encode()
    + ENDE)
stellen(antworten=[
    ("home.php", Antwort(b"<html>Dashboard</html>", "text/html")),
    ("download_csv=1", Antwort(HALB_VERGEBEN)),
    ("download_csv=2", Antwort(NUR_KOPF_OFFEN)),
])
try:
    csv_import.abrufen("automatisch", automatisch=True)
    pruefe(False, "der Schwund haette auffallen muessen")
except csv_import.Fehler as f:
    pruefe("zuletzt waren es" in str(f),
           "starker Schwund wird abgelehnt: " + str(f)[:80])

print("Gescheiterte Laeufe hinterlassen einen Vermerk")
letzter = zeilen("SELECT * FROM import_lauf ORDER BY id DESC LIMIT 1")[0]
pruefe(letzter["erfolg"] == 0, "als gescheitert vermerkt")
pruefe("zuletzt waren es" in letzter["bericht"],
       "mit dem Grund: " + letzter["bericht"][:60])
pruefe(letzter["kuerzel"] == "automatisch", "und wer es war")

print("Von Hand fragt niemand nach")
stellen(antworten=[
    ("home.php", Antwort(b"<html>Dashboard</html>", "text/html")),
    ("download_csv=1", Antwort(HALB_VERGEBEN)),
    ("download_csv=2", Antwort(NUR_KOPF_OFFEN)),
])
bericht = csv_import.abrufen("KK")
pruefe(bericht["zeilen_vergeben"] == 1 and bericht["zeilen_offen"] == 0,
       "derselbe Abruf geht von Hand durch - wer hinschaut, darf das")
pruefe(zeilen("SELECT erfolg FROM import_lauf ORDER BY id DESC LIMIT 1")[0][0] == 1,
       "und steht als geglueckt drin")

print("Eine gestellte Uhr haelt die Automatik an")
# Sonst traegt jeder Lauf denselben Zeitstempel und liesse sich vom vorigen
# nicht unterscheiden - und eine Vorfuehrung fragte fremde Server ab.
from app import main as hauptmodul  # noqa: E402

gemerkt = config.JETZT_FEST
config.JETZT_FEST = ""
pruefe(hauptmodul._abruf_takt() == config.IMPORT_TAKT_MINUTEN,
       "mit echter Uhr gilt der eingestellte Takt: "
       + str(hauptmodul._abruf_takt()))
config.JETZT_FEST = "2026-08-29T10:30:00"
pruefe(hauptmodul._abruf_takt() == 0,
       "mit gestellter Uhr verspricht die Importseite keinen Takt")
config.JETZT_FEST = gemerkt

# Die Schleifen selbst haengen an derselben Bedingung. Sie laufen zu lassen,
# nur um zuzusehen, dauerte Minuten - hier reicht, dass der Start sie
# ueberhaupt daran knuepft.
quelle = (WURZEL / "app" / "main.py").read_text(encoding="utf-8")
pruefe("von_selbst = not config.JETZT_FEST" in quelle,
       "der Start knuepft die Schleifen an die Uhr")
for muster in ("if von_selbst and config.serien()",
               "if von_selbst and config.IMPORT_ABRUF_MOEGLICH"):
    pruefe(muster in quelle, "und zwar beide: " + muster)

print("Der Takt")
pruefe(config.IMPORT_TAKT_MINUTEN >= 5 or config.IMPORT_TAKT_MINUTEN == 0,
       "unter fuenf Minuten laesst sich der Takt nicht stellen: "
       + str(config.IMPORT_TAKT_MINUTEN))

print()
if fehler:
    print("FEHLGESCHLAGEN (" + str(len(fehler)) + "):")
    for eintrag in fehler:
        print("  - " + eintrag)
    sys.exit(1)
print("alle Pruefungen bestanden")
print("Wegwerf-Datenbank lag in " + str(verzeichnis))
