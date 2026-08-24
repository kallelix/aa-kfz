"""Monitoransicht: Token, Inhalt, Zeitfenster (Schritt 8).

    python helfer/tests/test_monitor.py

Startet den Server mit gestellter Uhr (JETZT_FEST), damit sich prüfen lässt,
was zu einem bestimmten Zeitpunkt auf dem Bildschirm steht.
"""

import http.client
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

# Samstag mitten im Renntag.
JETZT = "2026-08-29T10:30:00"

fehler = []


def pruefe(bedingung, text):
    print(("  ok   " if bedingung else "  FEHL ") + text)
    if not bedingung:
        fehler.append(text)


def freier_hafen():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


verzeichnis = Path(tempfile.mkdtemp(prefix="helfer-monitor-"))
db_pfad = verzeichnis / "helfer.db"

# Datenbank vor dem Start füllen – der Server liest sie dann nur noch.
os.environ["DB_PATH"] = str(db_pfad)
os.environ["TAGE"] = "2026-08-28,2026-08-29,2026-08-30"
from app import db  # noqa: E402

db.init()
con = db.verbinden()
with con:
    # Läuft gerade, mit Lücke.
    lueckig, _ = db.schicht_sichern(con, "Ordner Zeltplatz",
                                    "2026-08-29 08:00", "2026-08-29 13:00",
                                    "2026-08-29", bedarf=4)
    # Läuft gerade, voll besetzt.
    voll, _ = db.schicht_sichern(con, "Orgabüro", "2026-08-29 09:00",
                                 "2026-08-29 18:00", "2026-08-29", bedarf=2)
    # Beginnt in 90 Minuten – im Vorschaufenster.
    bald, _ = db.schicht_sichern(con, "Shuttle", "2026-08-29 12:00",
                                 "2026-08-29 18:00", "2026-08-29", bedarf=3)
    # Beginnt erst in fünf Stunden – außerhalb des Fensters.
    spaeter, _ = db.schicht_sichern(con, "Merchandise", "2026-08-29 15:30",
                                    "2026-08-29 18:00", "2026-08-29", bedarf=2)
    # Schon vorbei.
    vorbei, _ = db.schicht_sichern(con, "Aufbau", "2026-08-29 06:00",
                                   "2026-08-29 09:00", "2026-08-29", bedarf=2)
    # Nachtschicht über Mitternacht, läuft am Abend.
    nacht, _ = db.schicht_sichern(con, "Nachtwache", "2026-08-29 20:00",
                                  "2026-08-30 08:00", "2026-08-29", bedarf=2)

    anna, _ = db.helfer_anlegen(con, {"name": "Anna Berg",
                                      "email": "anna@example.org"})
    bert, _ = db.helfer_anlegen(con, {"name": "Bert Öhl",
                                      "email": "bert@example.org"})
    for schicht, leute in ((lueckig, [anna]), (voll, [anna, bert]),
                           (bald, [bert]), (nacht, [anna, bert])):
        for person in leute:
            db.einteilen(schicht, person, quelle="import", con=con)

    for titel, beginn, ende, roh in (
            ("Pflichttraining", "2026-08-29 10:00", "2026-08-29 12:00",
             "10.00 - 12.00 Uhr"),
            ("Streckensperrung", "2026-08-29 13:00", "2026-08-29 13:30",
             "13.00 - 13.30 Uhr"),
            ("Seeding Run", "2026-08-29 13:30", None, "ab 13.30 Uhr"),
            ("Siegerehrung", None, None, "anschließend")):
        con.execute(
            "INSERT INTO programm (serie, titel, datum, beginn, ende,"
            " tag_roh, zeit_roh, angelegt_am) VALUES ('dhc', ?, ?, ?, ?,"
            " 'Samstag', ?, ?)",
            (titel, "2026-08-29", beginn, ende, roh, db.jetzt()))
con.close()

TOKEN = db.monitor_token(anlegen=True)
hafen = freier_hafen()

prozess = subprocess.Popen(
    [str(PYTHON), "-m", "app"],
    cwd=str(WURZEL),
    env={**os.environ, "DB_PATH": str(db_pfad), "BIND": f"127.0.0.1:{hafen}",
         "ADMIN_PASSWORD_HASH": HASH, "APP_SECRET_KEY": "test-schluessel",
         "COOKIE_SECURE": "0", "JETZT_FEST": JETZT,
         "MONITOR_VORSCHAU": "120", "MONITOR_WARNUNG": "1",
         "ZEITPLAN_SERIEN": "", "PYTHONIOENCODING": "utf-8"},
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
                    antwort.headers, antwort.read().decode("utf-8"))
        verbindung.close()
        return ergebnis

    print("Token")
    status, _, _, seite = anfrage("GET", "/monitor/" + TOKEN)
    pruefe(status == 200, "der richtige Token oeffnet die Ansicht")
    status, _, _, _ = anfrage("GET", "/monitor/" + TOKEN[:-1] + "X")
    pruefe(status == 404, "ein falscher Token gibt 404, nicht 403")
    status, _, _, _ = anfrage("GET", "/monitor/")
    pruefe(status in (404, 405), "ohne Token gibt es nichts")
    status, _, _, _ = anfrage("GET", "/monitor/" + TOKEN + "/inhalt")
    pruefe(status == 200, "das Bruchstueck laedt mit Token")
    status, _, _, _ = anfrage("GET", "/monitor/falsch/inhalt")
    pruefe(status == 404, "und nicht ohne")

    print("Ohne Anmeldung")
    pruefe("admin" not in seite.lower() or "/admin/login" not in seite,
           "auf der Monitorseite steht kein Weg ins Backoffice")
    pruefe("csrf" not in seite, "und kein CSRF-Token")

    print("Kopfzeile")
    pruefe("Samstag, 29.08.2026" in seite,
           "der Wochentag steht auf Deutsch drauf")
    pruefe('id="uhr">10:30<' in seite, "die gestellte Uhr wird angezeigt")
    pruefe('data-jetzt="2026-08-29T10:30:00"' in seite,
           "die Serverzeit steht fuer den Browser im Markup")

    print("Jetzt im Dienst")
    laufend = seite.split("tafel-programm")[0]
    pruefe("Ordner Zeltplatz" in laufend, "die laufende Schicht steht drauf")
    pruefe("Orgabüro" in laufend, "die zweite auch")
    pruefe("Aufbau" not in laufend, "die beendete nicht")
    pruefe("Merchandise" not in laufend, "die spaetere nicht")
    pruefe("Nachtwache" not in laufend, "die Nachtschicht am Abend auch nicht")
    pruefe("Anna Berg" in laufend, "die Namen stehen dabei")

    print("Besetzung")
    pruefe(re.search(r"Ordner Zeltplatz.*?1<span class=\"von\">/4", laufend, re.S)
           is not None, "1 von 4 bei der lueckigen Schicht")
    pruefe(re.search(r"Orgabüro.*?2<span class=\"von\">/2", laufend, re.S)
           is not None, "2 von 2 bei der vollen")
    pruefe("3 fehlen" in seite, "die Summe der Luecken steht in der Ueberschrift")
    pruefe(laufend.count("schicht-luecke") == 1,
           "genau eine laufende Schicht ist als lueckig markiert")

    print("Programm")
    pruefe("Pflichttraining" in seite, "was gerade laeuft, steht drauf")
    pruefe("programm-laufend" in seite, "und ist als laufend hervorgehoben")
    pruefe("Streckensperrung" in seite, "das Kommende auch")
    pruefe("Siegerehrung" in seite, "und der Punkt ohne Uhrzeit")
    pruefe("anschließend" in seite, "mit seinem Wortlaut")

    print("Als Naechstes")
    kommend = seite.split("tafel-naechst")[1]
    pruefe("Shuttle" in kommend, "was im Fenster beginnt, steht drauf")
    pruefe("Merchandise" not in kommend,
           "was erst in fuenf Stunden beginnt, nicht")
    pruefe("Nachtwache" not in kommend, "die Nachtschicht auch nicht")

    print("Verbindungswarnung")
    pruefe('id="warnung" hidden' in seite,
           "die Warnleiste liegt bereit, ist aber aus")
    pruefe("Stand von" in seite, "und nennt spaeter den Zeitpunkt")

    print("Selbstauffrischung")
    pruefe('data-quelle="/monitor/' + TOKEN + '/inhalt"' in seite,
           "das Skript kennt seine Quelle")
    pruefe("monitor.js" in seite, "das Skript ist eingebunden")
    pruefe("http-equiv=\"refresh\"" in seite and "<noscript>" in seite,
           "ohne JavaScript laedt die Seite selbst neu")

    status, _, kopf, bruchstueck = anfrage("GET", "/monitor/" + TOKEN + "/inhalt")
    pruefe("no-store" in kopf.get("cache-control", ""),
           "das Bruchstueck wird nicht zwischengespeichert")
    pruefe("<html" not in bruchstueck.lower(),
           "es ist wirklich nur ein Ausschnitt")
    pruefe("Ordner Zeltplatz" in bruchstueck, "mit demselben Inhalt")

    print("Backoffice")
    anfrage("POST", "/admin/login",
            {"passwort": "test-passwort-123", "kuerzel": "KK",
             "weiter": "/admin"})
    status, _, _, verwaltung = anfrage("GET", "/admin/monitor")
    pruefe(status == 200 and TOKEN in verwaltung, "der Link steht im Backoffice")
    CSRF = re.search(r'name="csrf" value="([^"]+)"', verwaltung).group(1)

    print("Neuer Link")
    status, ort, _, _ = anfrage("POST", "/admin/monitor",
                                {"csrf": CSRF, "aktion": "neu"})
    pruefe("hinweis=neuer-link" in ort, "meldet Erfolg")
    status, _, _, _ = anfrage("GET", "/monitor/" + TOKEN)
    pruefe(status == 404, "der alte Link gilt nicht mehr")

    _, _, _, verwaltung = anfrage("GET", "/admin/monitor")
    NEU = re.search(r"/monitor/([A-Za-z0-9_-]{20,})", verwaltung).group(1)
    pruefe(NEU != TOKEN, "es ist wirklich ein anderer")
    status, _, _, _ = anfrage("GET", "/monitor/" + NEU)
    pruefe(status == 200, "und der neue oeffnet die Ansicht")

    print("Widerrufen")
    status, ort, _, _ = anfrage("POST", "/admin/monitor",
                                {"csrf": CSRF, "aktion": "widerrufen"})
    pruefe("hinweis=widerrufen" in ort, "meldet Erfolg")
    status, _, _, _ = anfrage("GET", "/monitor/" + NEU)
    pruefe(status == 404, "danach oeffnet gar kein Link mehr")
    status, _, _, _ = anfrage("GET", "/monitor/")
    pruefe(status in (404, 405), "auch der leere nicht")

    print("CSRF")
    status, _, _, _ = anfrage("POST", "/admin/monitor",
                              {"csrf": "falsch", "aktion": "neu"})
    pruefe(status == 400, "ohne Token wird nichts erzeugt")

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
