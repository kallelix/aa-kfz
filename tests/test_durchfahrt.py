"""Durchfahrtsliste für die Straßensperre.

    python tests/test_durchfahrt.py

Startet den Server selbst und legt eigene Testdaten an – kein Seed nötig.

Gefiltert wird im Browser (app/static/durchfahrt.js), deshalb prüft dieser Test
nur die Serverseite: dass alle Berechtigten in der Seite stehen und dass die
vorgekauten Suchwerte in den data-Attributen stimmen. Die Filterlogik selbst
liegt in tests/test_durchfahrt_js.js.
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


# --- Normalisierung ----------------------------------------------------------
print("Kennzeichen-Normalisierung")
from app import db as db_modul  # noqa: E402

PROBEN = ["ka-xy 123", "KA XY 123", "kaxy123", "  M-JS 2000  ", "HH-DO 4",
          "ka.ab/101", "-", "", "Öztürk"]

for roh, erwartet in [
    ("ka-xy 123", "KAXY123"),
    ("KA XY 123", "KAXY123"),
    ("kaxy123", "KAXY123"),
    ("  M-JS 2000  ", "MJS2000"),
    ("-", ""),
    ("", ""),
]:
    pruefe(db_modul.kfz_normalisieren(roh) == erwartet,
           repr(roh) + " -> " + repr(db_modul.kfz_normalisieren(roh)))

# Die Naht zwischen den Sprachen: der Server schreibt data-kfz, der Browser
# richtet die Eingabe zu. Weichen die beiden voneinander ab, findet die Suche
# nichts – und zwar lautlos.
print("Python und JavaScript normalisieren gleich")
try:
    skript = (
        "const {kfzNormalisieren} = require(process.argv[1]);"
        "console.log(JSON.stringify(JSON.parse(process.argv[2]).map(kfzNormalisieren)));"
    )
    import json
    ausgabe = subprocess.run(
        ["node", "-e", skript, str(WURZEL / "app" / "static" / "durchfahrt.js"),
         json.dumps(PROBEN)],
        capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    if ausgabe.returncode != 0:
        pruefe(False, "node lief nicht: " + (ausgabe.stderr or "").strip()[:120])
    else:
        aus_js = json.loads(ausgabe.stdout)
        aus_py = [db_modul.kfz_normalisieren(wert) for wert in PROBEN]
        pruefe(aus_js == aus_py,
               "beide Seiten liefern dasselbe: " + str(aus_py))
        if aus_js != aus_py:
            for wert, js, py in zip(PROBEN, aus_js, aus_py):
                if js != py:
                    print("      " + repr(wert) + ": js=" + repr(js) + " py=" + repr(py))
except FileNotFoundError:
    print("  ---  node nicht gefunden, Abgleich uebersprungen")


def freier_hafen():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


verzeichnis = Path(tempfile.mkdtemp(prefix="abfahrt-sperre-"))
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

    print("Ohne Anmeldung")
    status, ort, _ = anfrage("GET", "/admin/durchfahrt")
    pruefe(status == 303 and ort.startswith("/admin/login"),
           "Durchfahrtsliste ohne Anmeldung fuehrt zur Anmeldeseite")

    LEUTE = [
        ("Andrea", "Berger", "KA-AB 101", "local"),
        ("Dennis", "Öztürk", "HH-DO 4", "vip"),
        ("Frank", "Weißmüller", "KA-FW 3", "expo"),
        ("Lars", "Brinkmann", "SB-LB 9", "vip"),
    ]
    for vorname, nachname, kennzeichen, kategorie in LEUTE:
        anfrage("POST", "/", {
            "vorname": vorname, "nachname": nachname, "funktion": "Aufbau",
            "kategorie": kategorie, "kennzeichen": kennzeichen,
            "telefon": "030 111",
        })

    anfrage("POST", "/admin/login", {"passwort": "test-passwort-123", "weiter": "/admin"})

    _, _, detail = anfrage("GET", "/admin/antrag/1")
    CSRF = re.search(r'name="csrf" value="([^"]+)"', detail).group(1)

    anfrage("POST", "/admin/sammelaktion", {"csrf": CSRF, "ids": ["1", "2"], "zurueck": "/admin"})
    anfrage("POST", "/admin/antrag/2/status", {"csrf": CSRF, "ziel": "ausgegeben"})
    anfrage("POST", "/admin/antrag/4/ablehnen", {"csrf": CSRF, "begruendung": "Kein Platz."})

    print("Nur Berechtigte")
    status, _, seite = anfrage("GET", "/admin/durchfahrt")
    pruefe(status == 200, "Durchfahrtsliste laedt")
    pruefe("Berger" in seite, "genehmigter Antrag steht drauf")
    pruefe("Öztürk" in seite, "ausgegebener Antrag steht drauf")
    pruefe("Weißmüller" not in seite, "unentschiedener Antrag steht NICHT drauf")
    pruefe("Brinkmann" not in seite, "abgelehnter Antrag steht NICHT drauf")
    pruefe(seite.count("<tr data-name=") == 2, "genau zwei Zeilen in der Tabelle")

    print("Nur die vier gewuenschten Spalten")
    spaltenkoepfe = re.findall(r'data-spalte="(\d)">\s*([A-Za-zÄÖÜäöüß]+)', seite)
    pruefe([name for _, name in spaltenkoepfe] == ["Vorname", "Name", "Kennzeichen", "Kategorie"],
           "vier Spalten in dieser Reihenfolge: " + str(spaltenkoepfe))
    for weg in ("Funktion", "Status", "Eingang", "Kontakt"):
        pruefe(">" + weg + " <" not in seite and "<th>" + weg + "</th>" not in seite,
               "Spalte " + weg + " fehlt zu Recht")

    print("Sortieren per Tippen auf die Ueberschrift")
    pruefe(seite.count('class="sortknopf"') == 4, "jede Ueberschrift ist ein Knopf")
    pruefe(seite.count('type="button"') >= 4,
           "type=button – ein Klick darf nichts abschicken")
    pruefe([n for _, n in spaltenkoepfe] and
           [z for z in ("0", "1", "2", "3") if 'data-spalte="' + z + '"' in seite] ==
           ["0", "1", "2", "3"],
           "die Spaltennummern 0 bis 3 sind vergeben")
    pruefe(seite.count('aria-sort=') == 4, "jede Spalte meldet ihren Sortierzustand")
    pruefe(seite.count('aria-sort="ascending"') == 1,
           "genau eine Spalte ist vorsortiert – die, nach der der Server liefert")
    vorsortiert = re.search(
        r'aria-sort="ascending">\s*<button[^>]*>\s*([A-Za-zÄÖÜäöüß]+)', seite)
    pruefe(vorsortiert is not None and vorsortiert.group(1) == "Name",
           "und zwar Name: " + (vorsortiert.group(1) if vorsortiert else "keine"))
    pruefe("sortpfeil" in seite, "Platz fuer die Richtungsmarke ist da")
    pruefe("Aufbau" not in seite, "die Funktion taucht auch im Inhalt nicht auf")
    pruefe("zaehler-kachel" not in seite, "keine Zusammenfassung oben")
    pruefe("030 111" not in seite, "keine Telefonnummern")

    print("Vorgekaute Suchwerte")
    zeilen = dict(re.findall(r'<tr data-name="([^"]*)" data-kfz="([^"]*)">', seite))
    pruefe(zeilen.get("andrea berger") == "KAAB101",
           "Berger: data-name klein, data-kfz ohne Trennzeichen -> " + str(zeilen))
    pruefe(zeilen.get("dennis öztürk") == "HHDO4", "Öztürk ebenso")
    pruefe(all(name == name.lower() for name in zeilen),
           "alle Namen sind kleingeschrieben")

    print("Ohne Netz filterbar")
    pruefe('src="/static/durchfahrt.js"' in seite, "das Filterskript ist eingebunden")
    # Das Suchfeld darf in keinem Formular stecken: ein Druck auf Enter wuerde
    # sonst neu laden, und ohne Netz kaeme die Seite nicht wieder.
    pruefe('action="/admin/durchfahrt"' not in seite and "?suche=" not in seite,
           "die Suche loest keine Anfrage aus")
    vor_suchfeld = seite[: seite.find('id="suche"')]
    pruefe(vor_suchfeld.count("<form") == vor_suchfeld.count("</form>"),
           "das Suchfeld steht ausserhalb jedes Formulars")
    status, _, skript = anfrage("GET", "/static/durchfahrt.js")
    pruefe(status == 200 and "kfzNormalisieren" in skript, "das Skript wird ausgeliefert")
    pruefe("<noscript>" in seite, "ohne JavaScript gibt es einen Hinweis")

    print("Reiter")
    _, _, liste = anfrage("GET", "/admin")
    pruefe('href="/admin/durchfahrt">Durchfahrtsliste' in liste,
           "der Reiter steht im Backoffice")

    print("Offener Link: ohne Token kein Zugang")
    status, _, _ = anfrage("GET", "/durchfahrt/irgendwas")
    pruefe(status == 404, "solange kein Link erzeugt ist, gibt es keinen offenen Zugang")

    _, _, seite = anfrage("GET", "/admin/durchfahrt")
    pruefe("Link erzeugen" in seite, "das Backoffice bietet an, einen zu erzeugen")
    pruefe('class="teilen-url"' not in seite, "und zeigt noch keinen Link")

    print("Offener Link: erzeugen")
    status, _, _ = anfrage("POST", "/admin/durchfahrt/link",
                           {"csrf": "falsch", "aktion": "erzeugen"})
    pruefe(status == 400, "erzeugen ohne CSRF-Token -> 400")
    pruefe(anfrage("GET", "/durchfahrt/irgendwas")[0] == 404, "und es entstand keiner")

    _, ort, _ = anfrage("POST", "/admin/durchfahrt/link", {"csrf": CSRF, "aktion": "erzeugen"})
    _, _, seite = anfrage("GET", ort)
    treffer = re.search(r'class="teilen-url"[^>]*>.*?/durchfahrt/([A-Za-z0-9_-]+)', seite, re.S)
    pruefe(treffer is not None, "der Link steht jetzt im Backoffice")
    token = treffer.group(1)
    pruefe(len(token) >= 32, "der Token ist lang genug zum Nichterraten: " + str(len(token)))
    pruefe("Neuer Link erzeugt" in seite, "mit Rueckmeldung")

    print("Offener Link: funktioniert und zeigt dasselbe")
    status, _, offen = anfrage("GET", "/durchfahrt/" + token)
    pruefe(status == 200, "der Link oeffnet die Liste ohne Anmeldung")
    pruefe("Berger" in offen and "Öztürk" in offen, "mit denselben Berechtigten")
    pruefe("Weißmüller" not in offen and "Brinkmann" not in offen,
           "und ohne die Unberechtigten")
    pruefe(offen.count("<tr data-name=") == 2, "genau zwei Zeilen")
    pruefe('src="/static/durchfahrt.js"' in offen, "auch hier wird im Browser gefiltert")

    print("Offener Link: verraet nichts weiter")
    for verboten, was in [
        ("/admin", "kein Verweis ins Backoffice"),
        ("Abmelden", "kein Abmelden-Knopf"),
        ("Telefonisch", "kein Reiter zur Telefonliste"),
        ("030 111", "keine Telefonnummern"),
        ("Aufbau", "keine Funktion"),
        ("csrf", "kein CSRF-Token"),
    ]:
        pruefe(verboten not in offen, was)
    pruefe('name="referrer" content="no-referrer"' in offen,
           "no-referrer, damit der Token nicht per Klick nach draussen wandert")
    pruefe("noindex" in offen, "noindex fuer Suchmaschinen")

    print("Offener Link: falsche Token")
    for falsch in (token[:-1], token + "x", token.upper(), "", "../admin"):
        status, _, _ = anfrage("GET", "/durchfahrt/" + urllib.parse.quote(falsch, safe=""))
        pruefe(status in (404, 307), "falscher Token " + repr(falsch[:12]) + " -> " + str(status))

    print("Offener Link: erneuern macht den alten tot")
    anfrage("POST", "/admin/durchfahrt/link", {"csrf": CSRF, "aktion": "erzeugen"})
    _, _, seite = anfrage("GET", "/admin/durchfahrt")
    neuer = re.search(r'class="teilen-url"[^>]*>.*?/durchfahrt/([A-Za-z0-9_-]+)', seite, re.S).group(1)
    pruefe(neuer != token, "der Token hat sich geaendert")
    pruefe(anfrage("GET", "/durchfahrt/" + token)[0] == 404, "der alte Link ist tot")
    pruefe(anfrage("GET", "/durchfahrt/" + neuer)[0] == 200, "der neue funktioniert")

    print("Offener Link: zuruecknehmen")
    status, _, _ = anfrage("POST", "/admin/durchfahrt/link",
                           {"csrf": "falsch", "aktion": "zuruecknehmen"})
    pruefe(status == 400, "zuruecknehmen ohne CSRF-Token -> 400")
    pruefe(anfrage("GET", "/durchfahrt/" + neuer)[0] == 200, "der Link lebt noch")

    _, ort, _ = anfrage("POST", "/admin/durchfahrt/link", {"csrf": CSRF, "aktion": "zuruecknehmen"})
    pruefe(anfrage("GET", "/durchfahrt/" + neuer)[0] == 404, "danach ist er tot")
    _, _, seite = anfrage("GET", ort)
    pruefe("Link zurückgezogen" in seite, "mit Rueckmeldung")
    pruefe("Link erzeugen" in seite, "und dem Angebot, einen neuen zu erzeugen")

    print("Offener Link braucht keine Anmeldung")
    anfrage("POST", "/admin/durchfahrt/link", {"csrf": CSRF, "aktion": "erzeugen"})
    _, _, seite = anfrage("GET", "/admin/durchfahrt")
    letzter = re.search(r'class="teilen-url"[^>]*>.*?/durchfahrt/([A-Za-z0-9_-]+)', seite, re.S).group(1)
    keks["wert"] = ""
    status, _, ohne_anmeldung = anfrage("GET", "/durchfahrt/" + letzter)
    pruefe(status == 200 and "Berger" in ohne_anmeldung,
           "ohne Sitzungscookie erreichbar – genau darum geht es")
    pruefe(anfrage("GET", "/admin/durchfahrt")[0] == 303,
           "das Backoffice bleibt trotzdem zu")
    anfrage("POST", "/admin/login", {"passwort": "test-passwort-123", "weiter": "/admin"})
    # Neue Sitzung, neuer CSRF-Token – der alte ist daran gebunden und jetzt wertlos.
    _, _, detail = anfrage("GET", "/admin/antrag/1")
    CSRF = re.search(r'name="csrf" value="([^"]+)"', detail).group(1)
    anfrage("POST", "/admin/durchfahrt/link", {"csrf": CSRF, "aktion": "zuruecknehmen"})

    print("Leere Liste")
    anfrage("POST", "/admin/antrag/1/status", {"csrf": CSRF, "ziel": "neu"})
    anfrage("POST", "/admin/antrag/2/status", {"csrf": CSRF, "ziel": "neu"})
    _, _, leer = anfrage("GET", "/admin/durchfahrt")
    pruefe("Noch ist niemand genehmigt" in leer, "leere Liste sagt es deutlich")

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
