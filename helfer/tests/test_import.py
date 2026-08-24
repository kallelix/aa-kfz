"""CSV-Import und Backoffice des Helfer-Dashboards (Schritte 1 bis 4).

    python helfer/tests/test_import.py

Startet den Server selbst und arbeitet auf einer Wegwerf-Datenbank. Die
Testdaten stehen hier im Code – die echten CSVs liegen nicht im Repository.
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
import uuid
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


# Nachgebaute Auszüge aus den beiden Dateien des alten Tools. Enthalten mit
# Absicht alles, was in den echten Daten weh tut: eine Schicht über
# Mitternacht, dieselbe Person zweimal auf einer Schicht, zwei Namen unter
# einer Adresse, eine Größe in der Verpflegungsspalte, krumme Schreibweisen
# und eine kaputte Zeile.
OFFEN = """Liste,Datum,Zeit,Aufgabe
Streckenposten,28.08.2026,10:00 - 18:00,
Streckenposten,28.08.2026,10:00 - 18:00,
Nachtwache,30.08.2026,20:00 - 08:00,
Aufbau,27.08.2026,08:00 - 14:00,
Aufbau,27.08.2026,kaputt,
"""

VERGEBEN = """Name,Zusatz1,Zusatz2,Liste,Datum,Zeit,Aufgabe,Email,Phone
Anna Berg,Vegetarisch,Damen L,Streckenposten,28.08.2026,10:00 - 18:00,,anna@example.org,
Bert Öhl,Fleisch,4xl,Streckenposten,28.08.2026,10:00 - 18:00,,bert@example.org,0170 1
Clara Groß,L,,Nachtwache,30.08.2026,20:00 - 08:00,,clara@example.org,
Doppel Dieter,Fleisch,m,Nachtwache,30.08.2026,20:00 - 08:00,,dieter@example.org,
Doppel Dieter,Fleisch,m,Nachtwache,30.08.2026,20:00 - 08:00,,dieter@example.org,
Team1,,XXXL,Aufbau,27.08.2026,08:00 - 14:00,,sammel@example.org,
Team2,,Shirt Gr.M,Aufbau,27.08.2026,08:00 - 14:00,,sammel@example.org,
Anna Berg,,,Aufbau,27.08.2026,08:00 - 14:00,,anna@example.org,
"""

verzeichnis = Path(tempfile.mkdtemp(prefix="helfer-"))
db_pfad = verzeichnis / "helfer.db"
hafen = freier_hafen()

prozess = subprocess.Popen(
    [str(PYTHON), "-m", "app"],
    cwd=str(WURZEL),
    env={**os.environ, "DB_PATH": str(db_pfad), "BIND": f"127.0.0.1:{hafen}",
         "ADMIN_PASSWORD_HASH": HASH, "APP_SECRET_KEY": "test-schluessel",
         "COOKIE_SECURE": "0", "PYTHONIOENCODING": "utf-8"},
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

    def anfrage(methode, pfad, daten=None, dateien=None):
        verbindung = http.client.HTTPConnection("127.0.0.1", hafen, timeout=10)
        kopf = {}
        koerper = None
        if dateien is not None:
            grenze = "----" + uuid.uuid4().hex
            teile = []
            for name, wert in (daten or {}).items():
                teile.append("--" + grenze)
                teile.append('Content-Disposition: form-data; name="%s"' % name)
                teile.append("")
                teile.append(wert)
            for name, (dateiname, inhalt) in dateien.items():
                teile.append("--" + grenze)
                teile.append(
                    'Content-Disposition: form-data; name="%s"; filename="%s"'
                    % (name, dateiname))
                teile.append("Content-Type: text/csv")
                teile.append("")
                teile.append(inhalt)
            teile.append("--" + grenze + "--")
            teile.append("")
            koerper = "\r\n".join(teile).encode("utf-8")
            kopf["Content-Type"] = "multipart/form-data; boundary=" + grenze
        elif daten is not None:
            koerper = urllib.parse.urlencode(daten, encoding="utf-8",
                                             doseq=True).encode("utf-8")
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
    for pfad in ("/admin", "/admin/schichten", "/admin/helfer", "/admin/import"):
        status, ort, _ = anfrage("GET", pfad)
        pruefe(status == 303 and ort.startswith("/admin/login"),
               pfad + " fuehrt zur Anmeldung")

    status, ort, _ = anfrage("GET", "/")
    pruefe(status == 303 and ort == "/admin", "/ leitet ins Backoffice")

    print("Anmelden")
    anfrage("POST", "/admin/login",
            {"passwort": "test-passwort-123", "kuerzel": "KK", "weiter": "/admin"})
    status, _, seite = anfrage("GET", "/admin")
    pruefe(status == 200, "Uebersicht laedt")
    pruefe("Noch keine Daten" in seite, "leere Datenbank wird als solche erklaert")
    CSRF = re.search(r'name="csrf" value="([^"]+)"', seite).group(1)

    print("Import ohne CSRF")
    status, _, _ = anfrage("POST", "/admin/import", {"csrf": "falsch"},
                           dateien={"offen": ("o.csv", OFFEN),
                                    "vergeben": ("v.csv", VERGEBEN)})
    pruefe(status == 400, "wird abgewiesen")

    print("Import mit nur einer Datei")
    status, _, seite = anfrage("POST", "/admin/import", {"csrf": CSRF},
                               dateien={"offen": ("o.csv", OFFEN)})
    pruefe(status == 400, "wird abgewiesen")
    pruefe("beide Dateien" in seite, "und erklaert, warum")
    pruefe(len(zeilen("SELECT id FROM schicht")) == 0, "nichts wurde geschrieben")

    print("Import mit falschen Spalten")
    status, _, seite = anfrage("POST", "/admin/import", {"csrf": CSRF},
                               dateien={"offen": ("o.csv", "a,b,c\n1,2,3\n"),
                                        "vergeben": ("v.csv", VERGEBEN)})
    pruefe(status == 400, "wird abgewiesen")
    pruefe("es fehlen die Spalten" in seite, "nennt die fehlenden Spalten")
    pruefe(len(zeilen("SELECT id FROM schicht")) == 0, "nichts wurde geschrieben")

    print("Import")
    status, _, seite = anfrage("POST", "/admin/import", {"csrf": CSRF},
                               dateien={"offen": ("offen.csv", OFFEN),
                                        "vergeben": ("vergeben.csv", VERGEBEN)})
    pruefe(status == 200, "laeuft durch")
    pruefe("Import fertig" in seite, "meldet Erfolg")

    schichten = {(z["liste"], z["beginn"]): z for z in
                 zeilen("SELECT * FROM schicht")}
    pruefe(len(schichten) == 3, "drei Schichten: " + str(len(schichten)))

    strecke = schichten[("Streckenposten", "2026-08-28 10:00")]
    pruefe(strecke["bedarf"] == 4, "Bedarf ist offen + vergeben, nicht nur eines")
    pruefe(strecke["ende"] == "2026-08-28 18:00", "Ende am selben Tag")

    nacht = schichten[("Nachtwache", "2026-08-30 20:00")]
    pruefe(nacht["ende"] == "2026-08-31 08:00", "Nachtschicht endet am Folgetag")
    pruefe(nacht["datum"] == "2026-08-30", "steht aber beim Vortag")
    pruefe(nacht["bedarf"] == 4, "Bedarf der Nachtschicht: " + str(nacht["bedarf"]))

    print("Kaputte Zeile")
    pruefe("Übersprungene Zeilen" in seite, "wird als uebersprungen gemeldet")
    pruefe("Zeile 6" in seite, "mit Zeilennummer: " + str("Zeile 6" in seite))
    aufbau = schichten[("Aufbau", "2026-08-27 08:00")]
    pruefe(aufbau["bedarf"] == 4,
           "die kaputte Zeile zaehlt nicht mit: " + str(aufbau["bedarf"]))

    print("Helfer")
    leute = {z["name"]: z for z in zeilen("SELECT * FROM helfer")}
    pruefe(len(leute) == 6, "sechs Personen: " + str(sorted(leute)))
    pruefe(leute["Anna Berg"]["veggie"] == 1, "vegetarisch erkannt")
    pruefe(leute["Bert Öhl"]["veggie"] == 0, "Fleisch erkannt")
    pruefe(leute["Bert Öhl"]["tshirt"] == "4XL", "'4xl' normalisiert")
    pruefe(leute["Anna Berg"]["tshirt"] == "L", "'Damen L' normalisiert")
    pruefe(leute["Anna Berg"]["tshirt_roh"] == "Damen L", "Rohwert bleibt stehen")
    pruefe(leute["Team1"]["tshirt"] == "3XL", "'XXXL' wird zu 3XL")
    pruefe(leute["Team2"]["tshirt"] == "M", "'Shirt Gr.M' wird zu M")

    print("Groesse in der Verpflegungsspalte")
    pruefe(leute["Clara Groß"]["tshirt"] == "L", "wird als Groesse uebernommen")
    pruefe(leute["Clara Groß"]["veggie"] is None, "Verpflegung bleibt offen")
    pruefe("Verpflegungsspalte" in seite, "und es steht im Bericht")

    print("Mehrere Namen unter einer Adresse")
    pruefe(leute["Team1"]["id"] != leute["Team2"]["id"],
           "bleiben zwei Personen")
    pruefe("2 Namen unter sammel@example.org" in seite, "steht im Bericht")

    print("Dieselbe Person zweimal auf einer Schicht")
    pruefe(len(zeilen(
        "SELECT e.id FROM einteilung e JOIN helfer h ON h.id = e.helfer_id"
        " WHERE h.name = 'Doppel Dieter'")) == 2, "beide Plaetze bleiben")
    pruefe("belegt 2 Plätze derselben Schicht" in seite, "steht im Bericht")

    print("Uebersicht nach dem Import")
    _, _, seite = anfrage("GET", "/admin")
    pruefe("Noch keine Daten" not in seite, "zeigt jetzt Zahlen")
    pruefe(">12<" in seite, "Bedarf 12 steht drauf")
    pruefe("Mehrfach auf derselben Schicht" in seite, "Doppelbelegung wird gemeldet")

    print("Zweiter Lauf derselben Dateien")
    _, _, seite = anfrage("POST", "/admin/import", {"csrf": CSRF},
                          dateien={"offen": ("offen.csv", OFFEN),
                                   "vergeben": ("vergeben.csv", VERGEBEN)})
    pruefe(len(zeilen("SELECT id FROM schicht")) == 3, "keine neuen Schichten")
    pruefe(len(zeilen("SELECT id FROM helfer")) == 6, "keine neuen Helfer")
    pruefe(zeilen("SELECT SUM(bedarf) FROM schicht")[0][0] == 12,
           "der Bedarf verdoppelt sich nicht")
    pruefe(len(zeilen("SELECT id FROM einteilung")) == 8,
           "die Einteilungen verdoppeln sich nicht")

    print("Schichtliste")
    status, _, liste = anfrage("GET", "/admin/schichten")
    pruefe(status == 200, "laedt")
    pruefe(liste.count("<tr data-suche=") == 3, "drei Zeilen")
    pruefe('data-wert="2026-08-30 20:00"' in liste, "Sortierwert steht dran")
    pruefe("hat-luecke" in liste, "Luecken sind markiert")

    _, _, liste = anfrage("GET", "/admin/schichten?liste=Nachtwache")
    pruefe(liste.count("<tr data-suche=") == 1, "Filter nach Liste greift")
    _, _, liste = anfrage("GET", "/admin/schichten?tag=2026-08-27")
    pruefe(liste.count("<tr data-suche=") == 1, "Filter nach Tag greift")
    _, _, liste = anfrage("GET", "/admin/schichten?luecken=1")
    pruefe(liste.count("<tr data-suche=") == 3, "alle drei haben Luecken")

    print("Einteilen von Hand")
    strecke_id = strecke["id"]
    anna_id = leute["Anna Berg"]["id"]
    status, ort, _ = anfrage(
        "POST", "/admin/schicht/%d/einteilen" % strecke_id,
        {"csrf": CSRF, "helfer_id": str(anna_id)})
    pruefe("hinweis=schon-drin" in ort, "wer schon drauf steht, kommt nicht doppelt")

    clara_id = leute["Clara Groß"]["id"]
    status, ort, _ = anfrage(
        "POST", "/admin/schicht/%d/einteilen" % strecke_id,
        {"csrf": CSRF, "helfer_id": str(clara_id)})
    pruefe("hinweis=eingeteilt" in ort, "sonst klappt es")
    neu = zeilen("SELECT * FROM einteilung WHERE schicht_id = ? AND helfer_id = ?",
                 strecke_id, clara_id)
    pruefe(len(neu) == 1 and neu[0]["quelle"] == "hand", "als 'hand' vermerkt")
    pruefe(neu[0]["kuerzel"] == "KK", "mit Kuerzel")

    status, ort, _ = anfrage("POST", "/admin/schicht/%d/einteilen" % strecke_id,
                             {"csrf": CSRF, "helfer_id": "999999"})
    pruefe("hinweis=keiner" in ort, "unbekannter Helfer wird abgefangen")
    status, ort, _ = anfrage("POST", "/admin/schicht/999999/einteilen",
                             {"csrf": CSRF, "helfer_id": str(clara_id)})
    pruefe("hinweis=unbekannt" in ort, "unbekannte Schicht wird abgefangen")

    print("Handeinteilung ueberlebt den naechsten Import")
    anfrage("POST", "/admin/import", {"csrf": CSRF},
            dateien={"offen": ("offen.csv", OFFEN),
                     "vergeben": ("vergeben.csv", VERGEBEN)})
    pruefe(len(zeilen("SELECT id FROM einteilung WHERE quelle = 'hand'")) == 1,
           "die Handeinteilung steht noch")
    pruefe(len(zeilen("SELECT id FROM einteilung")) == 9,
           "und die Importzeilen wurden ersetzt, nicht ergaenzt")

    print("Austragen")
    einteilung_id = zeilen(
        "SELECT id FROM einteilung WHERE quelle = 'hand'")[0]["id"]
    status, ort, _ = anfrage("POST", "/admin/einteilung/%d/austragen" % einteilung_id,
                             {"csrf": CSRF, "weiter": "/admin/schicht/%d" % strecke_id})
    pruefe("hinweis=ausgetragen" in ort, "meldet Erfolg")
    pruefe(ort.startswith("/admin/schicht/"), "und kehrt dorthin zurueck: " + ort)
    pruefe(len(zeilen("SELECT id FROM einteilung WHERE quelle = 'hand'")) == 0,
           "die Zeile ist weg")

    status, ort, _ = anfrage("POST", "/admin/einteilung/%d/austragen" % einteilung_id,
                             {"csrf": CSRF, "weiter": "https://beispiel.example/"})
    pruefe(not ort.startswith("http"), "fremdes Ziel wird nicht angesprungen: " + ort)

    print("Konflikte")
    _, _, seite = anfrage("GET", "/admin")
    pruefe("Zur selben Zeit auf zwei Schichten" not in seite,
           "ohne Ueberschneidung steht dort nichts")
    anfrage("POST", "/admin/schicht/%d/einteilen" % aufbau["id"],
            {"csrf": CSRF, "helfer_id": str(leute["Bert Öhl"]["id"])})
    anfrage("POST", "/admin/schicht/%d/einteilen" % strecke_id,
            {"csrf": CSRF, "helfer_id": str(leute["Team1"]["id"])})
    _, _, seite = anfrage("GET", "/admin")
    pruefe("Zur selben Zeit auf zwei Schichten" not in seite,
           "verschiedene Tage sind kein Konflikt")

    print("Helferliste und Detail")
    status, _, seite = anfrage("GET", "/admin/helfer")
    pruefe(status == 200 and seite.count("<tr data-suche=") == 6,
           "sechs Helfer stehen drauf")
    pruefe("oehl" in seite, "der Suchtext loest Umlaute auf")

    status, _, seite = anfrage("GET", "/admin/helfer/%d" % anna_id)
    pruefe(status == 200 and "Anna Berg" in seite, "Detail laedt")
    pruefe("Damen L" in seite, "der Rohwert steht dran")
    pruefe("vegetarisch" in seite, "die Verpflegung steht dran")

    status, _, _ = anfrage("GET", "/admin/helfer/999999")
    pruefe(status == 404, "unbekannter Helfer -> 404")
    status, _, _ = anfrage("GET", "/admin/schicht/999999")
    pruefe(status == 404, "unbekannte Schicht -> 404")

    print("Schichtdetail")
    status, _, seite = anfrage("GET", "/admin/schicht/%d" % nacht["id"])
    pruefe(status == 200, "laedt")
    pruefe("20:00–08:00 (+1)" in seite,
           "die Nachtschicht wird als solche angezeigt")
    pruefe(seite.count("Doppel Dieter") == 2, "beide Plaetze werden gezeigt")

    print("CSRF ueberall")
    for pfad in ("/admin/schicht/%d/einteilen" % strecke_id,
                 "/admin/einteilung/1/austragen"):
        status, _, _ = anfrage("POST", pfad, {"csrf": "falsch"})
        pruefe(status == 400, pfad + " ohne Token -> 400")

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
