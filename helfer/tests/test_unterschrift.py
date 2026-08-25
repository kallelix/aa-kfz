"""Unterschriften auf dem Tablet.

    python helfer/tests/test_unterschrift.py

Geprüft wird vor allem, was im Betrieb schiefgehen kann: dass die Übergabe
nicht an der Unterschrift hängt, dass eine abgelaufene Anforderung nicht mehr
angezeigt wird, und dass in den gespeicherten Pfad nichts hineinkommt, was
später als Markup ausgeliefert würde.
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
from datetime import timedelta
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


verzeichnis = Path(tempfile.mkdtemp(prefix="helfer-unterschrift-"))
db_pfad = verzeichnis / "helfer.db"
os.environ["DB_PATH"] = str(db_pfad)
os.environ["TAGE"] = "2026-08-28,2026-08-29,2026-08-30"

from app import db, unterschriften  # noqa: E402

print("Was in einen Pfad darf")
for roh, gut in (("M10,10L20,30", True),
                 ("M1.5,2.5L3,4 L5,6", True),
                 ("M-10,10L20,-30", True),
                 ("", False),
                 ("L10,10", False),
                 ('M10,10"/><script>alert(1)</script>', False),
                 ("M10,10Z", False),
                 ("M<>10", False),
                 ("M" + "1," * 40000, False)):
    ergebnis = bool(unterschriften.pfad_pruefen(roh))
    pruefe(ergebnis == gut, repr(roh[:34]) + " -> " + ("angenommen" if ergebnis
                                                       else "abgewiesen"))

db.init()
con = db.verbinden()
with con:
    anna, _ = db.helfer_anlegen(con, {"name": "Anna Berg",
                                      "email": "anna@example.org",
                                      "tshirt": "M"})
con.close()
db.tshirt_ausgeben(anna, "L", "KK")
ausleihe = db.ausleihen(anna, {"funke": 1, "ersatzakku": 2}, "2026-08-29",
                        kuerzel="KK")
fahrzeug, _ = db.fahrzeug_sichern("IL-A 1", "Anna Berg")
schluessel = db.schluessel_ausgeben(fahrzeug, "Anna Berg", kuerzel="KK")

print("Wortlaut")
titel, text, person = unterschriften.wortlaut("material", ausleihe, "ausgabe")
pruefe("Funkgerät" in text and "2× Ersatzakku" in text,
       "das Material steht ausgeschrieben drin: " + text)
pruefe(person == "Anna Berg", "mit der Person")
titel, text, _ = unterschriften.wortlaut("tshirt", anna, "ausgabe")
pruefe("Größe L" in text, "beim T-Shirt die AUSGEGEBENE Größe: " + text)
titel, text, _ = unterschriften.wortlaut("schluessel", schluessel, "rueckgabe")
pruefe("IL-A 1" in text and "Rückgabe" in titel, "beim Schlüssel das Kennzeichen")
titel, _, _ = unterschriften.wortlaut("material", 999999, "ausgabe")
pruefe(titel == "", "ein unbekannter Vorgang ergibt nichts")

TOKEN = db.tablet_token(anlegen=True)
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
        v = http.client.HTTPConnection("127.0.0.1", hafen, timeout=10)
        koerper = urllib.parse.urlencode(daten, doseq=True).encode() if daten else None
        kopf = {}
        if koerper is not None:
            kopf["Content-Type"] = "application/x-www-form-urlencoded"
        if keks["wert"]:
            kopf["Cookie"] = keks["wert"]
        v.request(methode, pfad, body=koerper, headers=kopf)
        a = v.getresponse()
        g = a.getheader("Set-Cookie", "")
        if g:
            keks["wert"] = g.split(";")[0]
        t = (a.status, a.getheader("Location", ""), a.read().decode("utf-8"))
        v.close()
        return t

    print("Der Tablet-Link")
    status, _, seite = anfrage("GET", "/unterschrift/" + TOKEN)
    pruefe(status == 200 and "Bereit" in seite,
           "mit richtigem Token steht dort „Bereit“")
    status, _, _ = anfrage("GET", "/unterschrift/" + TOKEN[:-1] + "X")
    pruefe(status == 404, "ein falscher Token gibt 404, nicht 403")
    status, _, _ = anfrage("GET", "/unterschrift/" + TOKEN + "/stand")
    pruefe(status == 200, "das Bruchstück lädt")
    status, _, _ = anfrage("POST", "/unterschrift/falsch/zeichnen",
                           {"id": "1", "pfad": "M1,1L2,2"})
    pruefe(status == 404, "und ohne Token wird nichts angenommen")

    pruefe("csrf" not in seite, "auf dem Tablet gibt es keinen CSRF-Token")
    pruefe("/admin" not in seite, "und keinen Weg ins Backoffice")

    print("Anfordern")
    anfrage("POST", "/admin/login",
            {"passwort": "test-passwort-123", "kuerzel": "KK",
             "weiter": "/admin"})
    _, _, verwaltung = anfrage("GET", "/admin/unterschriften")
    CSRF = re.search(r'name="csrf" value="([^"]+)"', verwaltung).group(1)

    status, ort, _ = anfrage("POST", "/admin/unterschrift/anfordern", {
        "csrf": CSRF, "art": "material", "vorgang_id": str(ausleihe),
        "richtung": "ausgabe", "weiter": "/admin/funk"})
    pruefe("hinweis=angefordert" in ort, "meldet Erfolg")
    pruefe(ort.startswith("/admin/funk"), "und kehrt dorthin zurück, wo man war")

    _, _, stand = anfrage("GET", "/unterschrift/" + TOKEN + "/stand")
    pruefe("Material Ausgabe" in stand, "das Tablet zeigt den Vorgang")
    pruefe("Anna Berg" in stand, "mit der Person")
    pruefe("Funkgerät" in stand, "und dem Wortlaut")
    pruefe("Bereit" not in stand, "und nicht mehr den Wartezustand")
    nummer = int(re.search(r'name="id" value="(\d+)"', stand).group(1))

    status, ort, _ = anfrage("POST", "/admin/unterschrift/anfordern", {
        "csrf": "falsch", "art": "material", "vorgang_id": str(ausleihe),
        "richtung": "ausgabe"})
    pruefe(status == 400, "ohne CSRF-Token wird nichts angefordert")

    status, ort, _ = anfrage("POST", "/admin/unterschrift/anfordern", {
        "csrf": CSRF, "art": "erfunden", "vorgang_id": "1",
        "richtung": "ausgabe"})
    pruefe("hinweis=unbekannt" in ort, "eine erfundene Art wird abgewiesen")

    print("Bei jeder Ausgabe wird sofort angefordert")
    unterschriften.abbrechen()
    status, ort, _ = anfrage("POST", "/admin/schluessel/ausgeben", {
        "csrf": CSRF, "kennzeichen": "IL-Z 9", "name": "Sofort Sofortski"})
    pruefe("hinweis=" in ort, "Ausgabe laeuft")
    _, _, stand = anfrage("GET", "/unterschrift/" + TOKEN + "/stand")
    pruefe("Schlüssel Ausgabe" in stand,
           "die Unterschrift steht ohne zweiten Klick auf dem Tablet")
    pruefe("Sofort Sofortski" in stand, "mit dem Namen im Feld")

    status, ort, _ = anfrage("POST", "/admin/helfer/%d/tshirt" % anna,
                             {"csrf": CSRF, "groesse": "XL"})
    _, _, stand = anfrage("GET", "/unterschrift/" + TOKEN + "/stand")
    pruefe("T-Shirt Ausgabe" in stand,
           "auch die T-Shirt-Ausgabe fordert von selbst an")
    unterschriften.abbrechen()

    print("Rücknahme nennt, was zurückkam")
    anfrage("POST", "/admin/ausleihe/%d/zurueck" % ausleihe,
            {"csrf": CSRF, "teilweise": "1", "funke": "1", "ersatzakku": "0"})
    _, _, stand = anfrage("GET", "/unterschrift/" + TOKEN + "/stand")
    pruefe("Material Rückgabe" in stand,
           "die Rücknahme fordert ebenfalls von selbst an")
    wortlaut = re.search(r'vorgang-wortlaut">(.*?)</p>', stand, re.S).group(1)
    wortlaut = " ".join(wortlaut.split())
    pruefe(wortlaut.startswith("1× Funkgerät"),
           "im Wortlaut steht zuerst, was zurückkam: " + wortlaut)
    pruefe("noch draußen: 2× Ersatzakku" in wortlaut,
           "und danach, was noch fehlt – wer das Funkgerät bringt und den "
           "Akku behält, soll nicht quittieren, alles abgegeben zu haben")
    unterschriften.abbrechen()

    print("Nur eine Warteschlange")
    anfrage("POST", "/admin/unterschrift/anfordern", {
        "csrf": CSRF, "art": "schluessel", "vorgang_id": str(schluessel),
        "richtung": "ausgabe", "weiter": "/admin/schluessel"})
    _, _, stand = anfrage("GET", "/unterschrift/" + TOKEN + "/stand")
    pruefe("Schlüssel Ausgabe" in stand, "die neue Anforderung löst die alte ab")
    pruefe(zeilen("SELECT abgebrochen_am FROM unterschrift WHERE id = ?",
                  nummer)[0][0] is not None,
           "die alte gilt als abgebrochen – ein Stapel wäre nur eine Falle "
           "für den Nächsten")
    zweite = int(re.search(r'name="id" value="(\d+)"', stand).group(1))

    print("Unterschreiben")
    pruefe('name="name"' in stand and "Anna Berg" in stand,
           "der Name steht als Feld da, vorbelegt")
    status, ort, _ = anfrage("POST", "/unterschrift/" + TOKEN + "/zeichnen",
                             {"id": str(zweite), "pfad": "M10,10L20,30L40,15",
                              "name": "Anna Berg"})
    pruefe(ort.endswith("/unterschrift/" + TOKEN),
           "kehrt ohne Meldung zurueck – der gruene Haken im Wartezustand "
           "sagt dasselbe und bliebe nicht in der Adresse stehen: " + ort)
    beleg = zeilen("SELECT * FROM unterschrift WHERE id = ?", zweite)[0]
    pruefe(beleg["bild"] == "M10,10L20,30L40,15", "der Pfad steht drin")
    pruefe(bool(beleg["unterschrieben_am"]), "mit Zeitpunkt")
    pruefe(len(beleg["pruefsumme"]) == 64, "und einer Prüfsumme")
    pruefe(beleg["wortlaut"] and "IL-A 1" in beleg["wortlaut"],
           "der Wortlaut ist mitgespeichert, nicht nur ein Verweis – wird der "
           "Vorgang später korrigiert, belegt er weiter den Stand von damals")

    _, _, stand = anfrage("GET", "/unterschrift/" + TOKEN + "/stand")
    pruefe("Bereit" in stand, "danach steht das Tablet wieder bereit")

    status, ort, _ = anfrage("POST", "/unterschrift/" + TOKEN + "/zeichnen",
                             {"id": str(zweite), "pfad": "M1,1L2,2"})
    pruefe("hinweis=weg" in ort, "zweimal unterschreiben geht nicht")
    pruefe(zeilen("SELECT bild FROM unterschrift WHERE id = ?",
                  zweite)[0][0] == "M10,10L20,30L40,15",
           "und ändert das Bild nicht")

    print("Was der Pfad nicht sein darf")
    anfrage("POST", "/admin/unterschrift/anfordern", {
        "csrf": CSRF, "art": "tshirt", "vorgang_id": str(anna),
        "richtung": "ausgabe", "weiter": "/admin/helfer"})
    _, _, stand = anfrage("GET", "/unterschrift/" + TOKEN + "/stand")
    dritte = int(re.search(r'name="id" value="(\d+)"', stand).group(1))
    for pfad, was in (("", "leer"),
                      ('M1,1"/><script>x</script>', "Markup"),
                      ("L1,1L2,2", "ohne M"),
                      ("M" + "1," * 40000, "zu lang")):
        status, ort, _ = anfrage("POST", "/unterschrift/" + TOKEN + "/zeichnen",
                                 {"id": str(dritte), "pfad": pfad})
        pruefe("hinweis=leer" in ort, was + " wird abgewiesen")
    pruefe(zeilen("SELECT bild FROM unterschrift WHERE id = ?",
                  dritte)[0][0] is None, "und nichts gespeichert")

    print("Abgelaufene Anforderung")

    def ablauf_setzen(nummer, minuten_zurueck):
        """Stellt das Ablaufdatum um so viele Minuten in die Vergangenheit."""
        zeitpunkt = (db.jetzt_lokal()
                     - timedelta(minutes=minuten_zurueck)
                     ).strftime("%Y-%m-%d %H:%M:%S")
        con = sqlite3.connect(db_pfad)
        with con:
            con.execute("UPDATE unterschrift SET laeuft_ab_am = ? WHERE id = ?",
                        (zeitpunkt, nummer))
        con.close()

    # Gerade eben abgelaufen: nicht mehr anzeigen, aber noch annehmen.
    ablauf_setzen(dritte, 1)
    _, _, stand = anfrage("GET", "/unterschrift/" + TOKEN + "/stand")
    pruefe("Bereit" in stand,
           "das Tablet zeigt sie nicht mehr – solange nichts ansteht, kann ein "
           "abhandengekommener Link nichts anrichten")
    status, ort, _ = anfrage("POST", "/unterschrift/" + TOKEN + "/zeichnen",
                             {"id": str(dritte), "pfad": "M1,1L2,2"})
    pruefe(ort.endswith("/unterschrift/" + TOKEN),
           "innerhalb der Nachfrist wird sie trotzdem angenommen – wer beim "
           "Ablaufen gerade zeichnet, soll nicht von vorn anfangen")

    # Lange abgelaufen: auch nicht mehr annehmen.
    anfrage("POST", "/admin/unterschrift/anfordern", {
        "csrf": CSRF, "art": "material", "vorgang_id": str(ausleihe),
        "richtung": "rueckgabe", "weiter": "/admin/funk"})
    _, _, stand = anfrage("GET", "/unterschrift/" + TOKEN + "/stand")
    vierte = int(re.search(r'name="id" value="(\d+)"', stand).group(1))
    ablauf_setzen(vierte, 60)
    status, ort, _ = anfrage("POST", "/unterschrift/" + TOKEN + "/zeichnen",
                             {"id": str(vierte), "pfad": "M1,1L2,2"})
    pruefe("hinweis=zu-spaet" in ort, "lange danach nicht mehr")

    print("Eine Unterschrift zum Material")
    anfrage("POST", "/admin/unterschrift/anfordern", {
        "csrf": CSRF, "art": "material", "vorgang_id": str(ausleihe),
        "richtung": "ausgabe", "weiter": "/admin/funk"})
    _, _, stand = anfrage("GET", "/unterschrift/" + TOKEN + "/stand")
    fuenfte = int(re.search(r'name="id" value="(\d+)"', stand).group(1))
    status, ort, _ = anfrage("POST", "/unterschrift/" + TOKEN + "/zeichnen",
                             {"id": str(fuenfte), "pfad": "M5,5L9,9"})
    pruefe(ort.endswith("/unterschrift/" + TOKEN), "wird angenommen")

    print("Ein korrigierter Name landet im Bestand")
    unterschriften.abbrechen()
    anfrage("POST", "/admin/unterschrift/anfordern", {
        "csrf": CSRF, "art": "material", "vorgang_id": str(ausleihe),
        "richtung": "ausgabe", "weiter": "/admin/funk"})
    _, _, stand = anfrage("GET", "/unterschrift/" + TOKEN + "/stand")
    sechste = int(re.search(r'name="id" value="(\d+)"', stand).group(1))
    anfrage("POST", "/unterschrift/" + TOKEN + "/zeichnen",
            {"id": str(sechste), "pfad": "M2,2L8,8",
             "name": "Anna Bergmann-Richtig"})
    pruefe(zeilen("SELECT name FROM helfer WHERE id = ?", anna)[0][0]
           == "Anna Bergmann-Richtig",
           "der Helfer heißt jetzt so – die importierten Namen sind "
           "stellenweise unbrauchbar, und hier stand die Person, die es "
           "besser weiß")
    pruefe(zeilen("SELECT person FROM unterschrift WHERE id = ?",
                  sechste)[0][0] == "Anna Bergmann-Richtig",
           "und der Beleg trägt den bestätigten Namen")

    print("Abbrechen vom Tablet")
    anfrage("POST", "/admin/unterschrift/anfordern", {
        "csrf": CSRF, "art": "material", "vorgang_id": str(ausleihe),
        "richtung": "rueckgabe", "weiter": "/admin/funk"})
    status, ort, _ = anfrage("POST", "/unterschrift/" + TOKEN + "/abbrechen", {})
    pruefe("hinweis=abgebrochen" in ort, "geht ohne Anmeldung – wer abbricht, "
           "steht am Tablet und nicht am Rechner")
    _, _, stand = anfrage("GET", "/unterschrift/" + TOKEN + "/stand")
    pruefe("Bereit" in stand, "danach ist das Tablet frei")

    print("Der Ausschnitt wird aus dem Pfad bestimmt")
    # x von 10 bis 40, y von 10 bis 30, je 8 Rand: 2/2, 46 breit, 36 hoch.
    pruefe(unterschriften.ausschnitt("M10,10L20,30L40,15") == "2.0 2.0 46.0 36.0",
           "eng um die Unterschrift: "
           + unterschriften.ausschnitt("M10,10L20,30L40,15"))
    pruefe(unterschriften.ausschnitt("M300,120L340,160")
           != unterschriften.ausschnitt("M10,10L20,30"),
           "zwei verschieden platzierte Unterschriften bekommen verschiedene "
           "Ausschnitte - eine feste viewBox liess sie verrutschen")
    pruefe(unterschriften.ausschnitt("") == "0 0 100 40",
           "ohne Pfad ein brauchbarer Vorgabewert")
    flach = unterschriften.ausschnitt("M0,100L400,101").split()
    pruefe(float(flach[2]) / float(flach[3]) <= 4.01,
           "eine sehr flache Unterschrift wird nicht bis zur Unkenntlichkeit "
           "gestreckt: " + str(flach))

    print("Keine Erfolgsmeldung, die stehen bleibt")
    _, _, seite = anfrage("GET", "/unterschrift/" + TOKEN)
    pruefe("meldung-gut" not in seite,
           "nach dem Unterschreiben steht keine gruene Leiste da – sie bliebe "
           "in der Adresse und schoebe die Knoepfe aus dem Bild")
    pruefe("bereit-zeichen" in seite, "der Haken im Wartezustand sagt dasselbe")
    _, _, seite = anfrage("GET", "/unterschrift/" + TOKEN + "?hinweis=ok")
    pruefe("meldung" not in seite.split("<main")[0],
           "auch von Hand angehaengt kommt sie nicht zurueck")
    _, _, seite = anfrage("GET", "/unterschrift/" + TOKEN + "?hinweis=weg")
    pruefe('id="meldung"' in seite,
           "eine Warnung dagegen schon – sie erklaert etwas")

    print("Backoffice")
    _, _, seite = anfrage("GET", "/admin/unterschriften")
    # Drei: Schluessel, T-Shirt und Material. Die vierte Anforderung war zu
    # spaet dran und wurde deshalb gerade nicht gespeichert.
    pruefe(seite.count("unterschriftbild") >= 3,
           "die Belege stehen drauf: " + str(seite.count("unterschriftbild")))
    pruefe('d="M10,10L20,30L40,15"' in seite,
           "der Pfad steckt als Inline-SVG drin, nicht als data:-URI – den "
           "wiese die CSP ab")
    pruefe("qualifizierte" in seite and "Signatur" in seite,
           "und es steht dabei, was das Ganze NICHT ist")
    pruefe("non-scaling-stroke" in seite,
           "die Strichstaerke haengt nicht am Ausschnitt")
    pruefe('viewBox="0 0 600 200"' not in seite,
           "keine feste viewBox mehr")

    _, _, funk = anfrage("GET", "/admin/funk")
    pruefe("unterschrieben" in funk,
           "in der Liste ist zu sehen, wo eine Unterschrift vorliegt")

    print("Ohne Tablet-Link")
    anfrage("POST", "/admin/unterschriften/link",
            {"csrf": CSRF, "aktion": "widerrufen"})
    status, _, _ = anfrage("GET", "/unterschrift/" + TOKEN)
    pruefe(status == 404, "der alte Link gilt nicht mehr")
    status, ort, _ = anfrage("POST", "/admin/unterschrift/anfordern", {
        "csrf": CSRF, "art": "material", "vorgang_id": str(ausleihe),
        "richtung": "ausgabe", "weiter": "/admin/funk"})
    pruefe("hinweis=kein-tablet" in ort,
           "und ohne Link wird gar nicht erst angefordert")
    _, _, funk = anfrage("GET", "/admin/funk")
    pruefe("unterschrift/anfordern" not in funk,
           "die Knöpfe verschwinden dann auch aus den Zeilen")

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
