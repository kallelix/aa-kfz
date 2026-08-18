"""Kategorien: Parsen, Validierung und Darstellung über den ganzen Weg.

    python tests/test_kategorien.py

Startet den Server selbst und braucht keine Vorbereitung. Prüft alle Kategorien
aus der Konfiguration, nicht nur die zwei aus den Seed-Daten.
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

PYTHON = WURZEL / ".venv" / "Scripts" / "python.exe"
if not PYTHON.exists():
    PYTHON = WURZEL / ".venv" / "bin" / "python"
if not PYTHON.exists():
    PYTHON = Path(sys.executable)

HASH = "$2b$12$jWSkTX2jwE2Afm795IqpuuLOLzUGEL8Qruhfa67JQvzJd4fn.6fnm"

fehler = []


def pruefe(bedingung, text):
    print(("  ok   " if bedingung else "  FEHL ") + text)
    if not bedingung:
        fehler.append(text)


# --- Parsen ------------------------------------------------------------------
print("Parsen")
from app import config  # noqa: E402

ERWARTET = [
    ("camping", "Camping"),
    ("expo", "Expo"),
    ("local", "Local/Durchfahrt"),
    ("parken", "Parken"),
    ("vip", "VIP"),
]
pruefe(config.KATEGORIEN == ERWARTET, "Vorgabe sind die fuenf Kategorien: " + str(config.KATEGORIEN))
pruefe(config.KATEGORIE_LABELS["local"] == "Local/Durchfahrt",
       "ein Schraegstrich in der Beschriftung ueberlebt das Parsen")

# Der Beschreibungstext darf enthalten, was in KATEGORIEN nicht ginge.
import os as _os  # noqa: E402

_os.environ["KATEGORIE_TEXT_CAMPING"] = "Mit Komma, Doppelpunkt: und allem."
pruefe(config._kategorie_text("camping") == "Mit Komma, Doppelpunkt: und allem.",
       "Env-Text ueberschreibt und vertraegt Satzzeichen")
del _os.environ["KATEGORIE_TEXT_CAMPING"]
pruefe(config._kategorie_text("camping").startswith("Du bist Helfer"),
       "ohne Env greift der eingebaute Text")
pruefe(config._kategorie_text("gibtesnicht") == "",
       "unbekannte Kategorie hat keinen Text")

sonderfaelle = config._parse_kategorien("  a : Alpha , b:Beta:mit Doppelpunkt ,, c , ")
pruefe(sonderfaelle == [("a", "Alpha"), ("b", "Beta:mit Doppelpunkt"), ("c", "c")],
       "Leerzeichen, leere Eintraege und fehlende Beschriftung: " + str(sonderfaelle))

# --- Validierung -------------------------------------------------------------
print("Validierung")
from app import validation  # noqa: E402

for schluessel, _ in ERWARTET:
    _, meldungen = validation.pruefen({
        "vorname": "A", "nachname": "B", "funktion": "C",
        "kategorie": schluessel, "kennzeichen": "B-XY 1", "telefon": "030 1",
    })
    pruefe("kategorie" not in meldungen, "Kategorie '" + schluessel + "' wird angenommen")

for unfug in ("campingplatz", "vip_parkplatz", "CAMPING", "", "<script>"):
    _, meldungen = validation.pruefen({
        "vorname": "A", "nachname": "B", "funktion": "C",
        "kategorie": unfug, "kennzeichen": "B-XY 1", "telefon": "030 1",
    })
    pruefe("kategorie" in meldungen, "Kategorie " + repr(unfug) + " wird abgelehnt")


# --- Ueber HTTP --------------------------------------------------------------
def freier_hafen():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


verzeichnis = Path(tempfile.mkdtemp(prefix="abfahrt-kategorien-"))
db = verzeichnis / "test.db"
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
        koerper = urllib.parse.urlencode(daten or {}, encoding="utf-8") if daten else None
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

    print("Formular")
    status, _, formular = anfrage("GET", "/")
    for schluessel, beschriftung in ERWARTET:
        pruefe('value="' + schluessel + '"' in formular and beschriftung in formular,
               "Formular bietet " + beschriftung + " an")
    pruefe(formular.count('name="kategorie"') == len(ERWARTET),
           "genau fuenf Auswahlfelder: " + str(formular.count('name="kategorie"')))

    print("Beschreibungen")
    for schluessel, _ in ERWARTET:
        text = config.KATEGORIE_TEXTE.get(schluessel, "")
        pruefe(bool(text), "fuer " + schluessel + " ist ein Text hinterlegt")
        if text:
            pruefe(text in formular, "der Text zu " + schluessel + " steht im Formular")
            pruefe('id="kat-' + schluessel + '"' in formular
                   and 'aria-describedby="kat-' + schluessel + '"' in formular,
                   "der Text ist mit dem Auswahlfeld " + schluessel + " verknuepft")

    print("Absenden")
    for nummer, (schluessel, _) in enumerate(ERWARTET, start=1):
        status, ort, _ = anfrage("POST", "/", {
            "vorname": "Vor" + str(nummer), "nachname": "Nach" + str(nummer),
            "funktion": "Aufbau", "kategorie": schluessel,
            "kennzeichen": "B-XY " + str(nummer), "telefon": "030 " + str(nummer),
        })
        pruefe(status == 303, "Antrag mit Kategorie " + schluessel + " wird angenommen")

    status, _, _ = anfrage("POST", "/", {
        "vorname": "X", "nachname": "Y", "funktion": "Z",
        "kategorie": "campingplatz", "kennzeichen": "B-XY 9", "telefon": "030 9",
    })
    pruefe(status == 422, "alter Schluessel campingplatz wird abgelehnt")

    con = sqlite3.connect(db)
    gespeichert = [z[0] for z in con.execute("SELECT kategorie FROM antrag ORDER BY id")]
    con.close()
    pruefe(gespeichert == [s for s, _ in ERWARTET],
           "alle fuenf sind gespeichert: " + str(gespeichert))

    print("Backoffice")
    anfrage("POST", "/admin/login", {"passwort": "test-passwort-123", "weiter": "/admin"})
    status, _, liste = anfrage("GET", "/admin")
    pruefe(status == 200, "Liste laedt")
    for _, beschriftung in ERWARTET:
        pruefe(beschriftung in liste, "Beschriftung " + beschriftung + " steht in der Liste")
    kacheln = liste.count("zaehler-kachel")
    pruefe(kacheln == len(ERWARTET) + 1, "eine Kachel je Kategorie plus Gesamt: " + str(kacheln))

    for schluessel, beschriftung in ERWARTET:
        status, _, gefiltert = anfrage("GET", "/admin?status=&kategorie=" + schluessel)
        treffer = len(re.findall(r'href="/admin/antrag/\d+"', gefiltert))
        # Nummer und Name verweisen beide auf denselben Antrag.
        pruefe(treffer == 2, "Filter " + schluessel + " zeigt genau einen Antrag")

    status, _, csv_datei = anfrage("GET", "/admin/export.csv?status=")
    for schluessel, beschriftung in ERWARTET:
        pruefe(schluessel in csv_datei and beschriftung in csv_datei,
               "CSV nennt " + schluessel + " als Schluessel und " + beschriftung + " als Klartext")

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
