"""Der Assistent (Lastenheft 3.1: A-01 bis A-05).

    python helfer/tests/test_assistent.py

Wann hast du Zeit, was liegt dir, was passt – die dringendsten zuerst. Und
der Springer für alle, die flexibel sind oder nichts finden. Die Rechnerei
ohne Server, dann der Weg durch die Seiten bis zur Anmeldung, und die Haken
am Bereich im Backoffice.
"""

import http.client
import os
import re
import socket
import subprocess
import sys
import time
import urllib.parse
from datetime import date
from html import unescape
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


from app import selbstanmeldung as sa  # noqa: E402

print("Zeiten (A-02)")
TAGE = [date(2027, 7, d) for d in range(1, 5)]
pruefe(sa.zeitspannen(["2027-07-02|frueh", "2027-07-02|mittag"], TAGE)
       == [("2027-07-02 06:00", "2027-07-02 18:00")],
       "Vormittag und Nachmittag verschmelzen zu einer Spanne")
pruefe(sa.zeitspannen(["2027-07-02|abend"], TAGE) == [("2027-07-02 17:00", "2027-07-03 03:00")],
       "der Abend reicht für die Vorschläge bis drei Uhr")
pruefe(sa.zeitspannen(["2027-08-01|frueh", "2027-07-02|nachts"], TAGE) == [],
       "fremde Tage und unbekannte Zeiten fallen weg")
FRUEH = sa.zeitspannen(["2027-07-02|frueh"], TAGE)
pruefe(sa.passt_zur_zeit("2027-07-02 08:00", "2027-07-02 14:00", FRUEH),
       "8 bis 14 Uhr passt zu Vormittag allein – fünf von sechs Stunden")
pruefe(not sa.passt_zur_zeit("2027-07-02 10:00", "2027-07-02 18:00", FRUEH),
       "10 bis 18 Uhr nicht – nur drei von acht")
pruefe(sa.passt_zur_zeit("2027-07-02 20:00", "2027-07-03 02:00",
                         sa.zeitspannen(["2027-07-02|abend"], TAGE)),
       "die Nachtschicht gehört zum Abend ihres ersten Tages")

print("Vorlieben (A-03)")
pruefe(sa.vorlieben_aus(["fahren", "quatsch", "strecke", "egal"]) == ["strecke", "fahren", "egal"],
       "in fester Reihenfolge, Unbekanntes fällt weg")
pruefe(sa.passt_zu_vorlieben(["strecke"], ["strecke", "menschen"]), "gemeinsamer Haken passt")
pruefe(not sa.passt_zu_vorlieben(["fahren"], ["strecke"]), "ohne gemeinsamen nicht")
pruefe(sa.passt_zu_vorlieben([], ["strecke"]), "ein Bereich ohne Haken passt zu allem")
pruefe(sa.passt_zu_vorlieben(["fahren"], []) and sa.passt_zu_vorlieben(["fahren"], ["egal"]),
       "ohne Wahl oder mit „egal“ passt alles")

db_url = testdb.wegwerf("helfer_assistent")
os.environ.update({"DATABASE_URL": db_url, "APP_SECRET_KEY": "test-schluessel",
                   "JETZT_FEST": "2027-06-01 10:00"})

from app import db  # noqa: E402

db.init()
VA = db.VERANSTALTUNGEN.anlegen({"name": "Die absolute Abfahrt 2027", "kurz": "AA 2027",
                                 "beginn": "2027-07-01", "ende": "2027-07-04",
                                 "ort": "Ilmenau", "status": "offen"})
db.angebot_setzen(VA, {"goodies": 0, "shirt": 0, "schnitte": 0, "verpflegung": 0, "party": 0})
LEER = {"beschreibung": "", "treffpunkt": "", "mindestalter": None, "voraussetzungen": "",
        "intern": 0}


def bereich(name, vorlieben, **mehr):
    return db.bereich_anlegen(VA, {**LEER, "name": name, "vorlieben": vorlieben, **mehr})


B = {"Aufbau": bereich("Aufbau", ["anpacken"]),
     "Strecke": bereich("Streckenposten", ["strecke"]),
     "Merch": bereich("Merchandise", ["menschen"]),
     "Shuttle": bereich("Shuttle", ["fahren"], mindestalter=18),
     "Orga": bereich("Orgabüro", []),
     "Voll": bereich("Zeltplatz", ["strecke"])}


def schicht(name, tag, von, bis, soll, minimum, reserve=0):
    ende_tag = tag if bis > von else "2027-07-%02d" % (int(tag[-2:]) + 1)
    return db.schicht_anlegen(VA, B[name], {
        "datum": tag, "beginn": f"{tag} {von}", "ende": f"{ende_tag} {bis}",
        "minimum": minimum, "soll": soll, "reserve": reserve, "mindestalter": None,
        "ort": "", "hinweis": "", "intern": 0})


AUFBAU = schicht("Aufbau", "2027-06-30", "08:00", "14:00", 4, 2)
STRECKE_FRUEH = schicht("Strecke", "2027-07-02", "08:00", "13:00", 3, 3)
STRECKE_SPAET = schicht("Strecke", "2027-07-02", "13:00", "18:00", 3, 1)
MERCH = schicht("Merch", "2027-07-02", "09:00", "12:00", 1, 0, reserve=1)
NACHT = schicht("Shuttle", "2027-07-02", "20:00", "02:00", 1, 1)
ORGA = schicht("Orga", "2027-07-03", "08:00", "12:00", 2, 1)
VOLL = schicht("Voll", "2027-07-02", "08:00", "12:00", 1, 1)


def person(name):
    nummer, _ = db.helfer_von_hand({"name": name, "email": name.split()[0].lower() + "@example.org"})
    return nummer


db.einteilen(STRECKE_FRUEH, person("Anna Berg"))
db.einteilen(STRECKE_SPAET, person("Bert Berg"))
db.einteilen(MERCH, person("Cleo Berg"))
db.einteilen(VOLL, person("Dora Berg"))

hafen = freier_hafen()
prozess = subprocess.Popen(
    [str(PYTHON), "-m", "app"], cwd=str(WURZEL),
    env={**os.environ, "BIND": f"127.0.0.1:{hafen}", "ADMIN_PASSWORD_HASH": HASH,
         "COOKIE_SECURE": "0", "ZEITPLAN_SERIEN": "", "PYTHONIOENCODING": "utf-8"},
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

try:
    for _ in range(100):
        try:
            with socket.create_connection(("127.0.0.1", hafen), timeout=0.2):
                break
        except OSError:
            time.sleep(0.1)
    else:
        raise RuntimeError("Server ist nicht hochgekommen")

    def anfrage(methode, pfad, daten=None, glas=None):
        glas = {} if glas is None else glas
        verbindung = http.client.HTTPConnection("127.0.0.1", hafen, timeout=10)
        koerper = urllib.parse.urlencode(daten, doseq=True).encode() if daten else None
        kopf = {"Content-Type": "application/x-www-form-urlencoded"} if koerper else {}
        if glas:
            kopf["Cookie"] = "; ".join(k + "=" + w for k, w in glas.items())
        verbindung.request(methode, pfad, body=koerper, headers=kopf)
        antwort = verbindung.getresponse()
        for gesetzt in antwort.headers.get_all("Set-Cookie") or []:
            name, _, wert = gesetzt.split(";")[0].partition("=")
            glas[name] = wert
        ergebnis = (antwort.status, antwort.getheader("Location", ""),
                    unescape(antwort.read().decode("utf-8")))
        verbindung.close()
        return ergebnis

    def abfrage(pfad, paare):
        return pfad + "?" + urllib.parse.urlencode(paare)

    def vorschlaege(seite):
        """Die vorgeschlagenen Schichten, in der Reihenfolge der Seite."""
        return [int(x) for x in re.findall(r'name="s" value="(\d+)"', seite)]

    FREITAG = [("zeit", "2027-07-02|" + z) for z in ("frueh", "mittag", "abend")]

    print("Startseite (A-01)")
    status, _, seite = anfrage("GET", "/aa-2027")
    pruefe(status == 200 and 'href="/aa-2027/zeit"' in seite
           and seite.index("/aa-2027/zeit") < seite.index("/aa-2027/schichten"),
           "zwei Wege – der Assistent zuerst, die Liste darunter")

    print("Schritt 1: Zeit (A-02)")
    status, _, seite = anfrage("GET", "/aa-2027/zeit")
    pruefe(status == 200 and "<h2 class=\"gruppe-kopf\">Aufbau</h2>" in seite
           and "<h2 class=\"gruppe-kopf\">Veranstaltung</h2>" in seite
           and seite.index(">Aufbau<") < seite.index(">Veranstaltung<"),
           "Aufbau und Veranstaltung getrennt, der Aufbau zuerst")
    pruefe('value="2027-06-30|frueh"' in seite and 'value="2027-07-04|abend"' in seite,
           "der Aufbautag mit Schicht steht dabei, die Veranstaltungstage auch")
    status, ort, _ = anfrage("GET", "/aa-2027/vorlieben")
    pruefe(status == 303 and ort.endswith("/aa-2027/zeit?hinweis=leer"),
           "ohne angetippte Zeit geht es nicht weiter")
    _, _, seite = anfrage("GET", "/aa-2027/zeit?hinweis=leer")
    pruefe("Tippe mindestens eine Zeit an." in seite, "und die Seite sagt, warum")

    print("Schritt 2: Vorlieben (A-03)")
    status, _, seite = anfrage("GET", abfrage("/aa-2027/vorlieben", FREITAG + [("vorliebe", "fahren")]))
    pruefe(status == 200 and seite.count('name="vorliebe"') == 5
           and re.search(r'value="fahren"\s+checked', seite),
           "fünf Möglichkeiten, die gewählte angehakt")
    pruefe(seite.count('type="hidden" name="zeit"') == 3, "die Zeiten reisen mit")
    pruefe('href="/aa-2027/zeit?zeit=2027-07-02%7Cfrueh' in seite, "und zurück auch")

    print("Schritt 3: Vorschläge (A-04)")
    status, _, seite = anfrage("GET", abfrage("/aa-2027/vorschlaege", FREITAG))
    liste = vorschlaege(seite)
    pruefe(status == 200 and liste == [STRECKE_FRUEH, NACHT, STRECKE_SPAET, MERCH],
           "unter Minimum zuerst, dann unter Soll, dann Reserve – je nach Beginn: " + str(liste))
    pruefe(VOLL not in liste and AUFBAU not in liste and ORGA not in liste,
           "nichts Volles, nichts außerhalb der Zeiten")
    pruefe("Wird dringend gebraucht" in seite and "als Reserve" in seite and "ab 18" in seite,
           "mit den Marken wie in der Liste")
    pruefe("data-auswahl" in seite and "/static/anmeldung.js" in seite,
           "dasselbe Formular wie die Liste – mit Skript graut es Überschneidungen aus")

    _, _, seite = anfrage("GET", abfrage("/aa-2027/vorschlaege",
                                         FREITAG + [("zeit", "2027-07-03|frueh"),
                                                    ("vorliebe", "strecke")]))
    liste = vorschlaege(seite)
    pruefe(liste == [STRECKE_FRUEH, ORGA, STRECKE_SPAET],
           "nur die Strecke – und der Bereich ohne Haken, der passt zu allem; unter "
           "Minimum auch am Samstag vor dem gelben Freitag: " + str(liste))
    _, _, seite = anfrage("GET", abfrage("/aa-2027/vorschlaege",
                                         FREITAG + [("vorliebe", "strecke"), ("s", MERCH)]))
    pruefe(MERCH in vorschlaege(seite) and re.search(r'value="%d" checked' % MERCH, seite),
           "was schon gewählt war, bleibt stehen, auch wenn es nicht mehr passt")

    print("Springer (A-05)")
    pruefe('<details class="karte">' in seite and 'name="z" value="2027-07-02|frueh"' in seite,
           "für die angetippten Zeiten – zugeklappt, solange etwas passt")
    _, _, seite = anfrage("GET", abfrage("/aa-2027/vorschlaege", FREITAG + [("vorliebe", "egal")]))
    pruefe('<details class="karte" open>' in seite and len(vorschlaege(seite)) == 4,
           "mit „egal“ alles – und der Springer steht offen")
    _, _, seite = anfrage("GET", abfrage("/aa-2027/vorschlaege", [("zeit", "2027-07-04|abend")]))
    pruefe("Gerade passt nichts genau" in seite and not vorschlaege(seite)
           and '<details class="karte" open>' in seite
           and 'name="z" value="2027-07-04|abend"' in seite,
           "passt nichts, steht der Springer offen da")
    status, ort, _ = anfrage("GET", abfrage("/aa-2027/vorschlaege", [("zeit", "2027-08-01|frueh")]))
    pruefe(status == 303 and ort.endswith("/zeit?hinweis=leer"), "ohne gültige Zeit zurück")

    print("Weiter zu den Angaben")
    weg = FREITAG + [("vorliebe", "strecke"), ("vorliebe", "menschen")]
    status, ort, _ = anfrage("GET", abfrage("/aa-2027/angaben", weg))
    pruefe(status == 303 and "/aa-2027/vorschlaege?" in ort and "hinweis=leer" in ort
           and "vorliebe=menschen" in ort, "nichts gewählt: zurück zu den Vorschlägen")
    _, _, seite = anfrage("GET", abfrage("/aa-2027/vorschlaege", weg) + "&hinweis=leer")
    pruefe("Tipp eine Schicht an" in seite, "mit einem Satz dazu")
    status, _, seite = anfrage("GET", abfrage("/aa-2027/angaben",
                                              weg + [("s", STRECKE_FRUEH), ("z", "2027-06-30|frueh")]))
    pruefe(status == 200 and 'href="/aa-2027/vorschlaege?s=%d' % STRECKE_FRUEH in seite,
           "„Auswahl ändern“ führt zurück zu den Vorschlägen")
    pruefe(seite.count('type="hidden" name="zeit"') == 3
           and 'type="hidden" name="vorliebe" value="menschen"' in seite,
           "Zeiten und Vorlieben stehen im Formular")
    pruefe("Springer</strong> · Mi 30.06. Vormittag" in seite,
           "Springer geht auch am Aufbautag")

    status, ort, _ = anfrage("POST", "/aa-2027/angaben", weg + [
        ("s", STRECKE_FRUEH), ("z", "2027-06-30|frueh"),
        ("ich-vorname", "Erik"), ("ich-nachname", "Assistent"),
        ("ich-email", "erik@example.org"), ("ich-volljaehrig", "ja"),
        ("weitere", 0), ("aktion", "anmelden")])
    pruefe(status == 303 and "/aa-2027/danke" in ort, "die Anmeldung geht durch: " + ort)
    zeile = testdb.abfrage(db_url, "helfer",
                           "SELECT t.vorlieben FROM teilnahme t JOIN helfer h ON h.id = t.helfer_id"
                           " WHERE h.email = 'erik@example.org'")
    pruefe(zeile and zeile[0][0] in (["strecke", "menschen"], "{strecke,menschen}"),
           "die Vorlieben stehen an der Teilnahme: " + str(zeile))
    zeile = testdb.abfrage(db_url, "helfer",
                           "SELECT v.beginn, v.ende FROM verfuegbarkeit v JOIN helfer h"
                           " ON h.id = v.helfer_id WHERE h.email = 'erik@example.org'")
    pruefe(zeile and (zeile[0][0], zeile[0][1]) == ("2027-06-30 06:00", "2027-06-30 13:00"),
           "und die Springer-Zeit am Aufbautag: " + str(zeile))

    print("Die Liste kennt den Aufbautag auch")
    _, _, seite = anfrage("GET", "/aa-2027/schichten")
    pruefe('name="z" value="2027-06-30|frueh"' in seite, "Springer am Aufbautag auch in der Liste")

    print("Backoffice: wozu ein Bereich passt")
    admin = {}
    anfrage("POST", "/helfer/login", {"passwort": "test-passwort-123", "kuerzel": "KK",
                                      "weiter": "/helfer"}, admin)
    status, _, seite = anfrage("GET", "/helfer/bereich/%d" % B["Merch"], glas=admin)
    pruefe(status == 200 and re.search(r'name="vorliebe-menschen" value="1"\s+checked', seite)
           and not re.search(r'name="vorliebe-strecke" value="1"\s+checked', seite),
           "die Haken stehen im Formular")
    csrf = re.search(r'name="csrf" value="([^"]+)"', seite).group(1)
    erik = testdb.abfrage(db_url, "helfer",
                          "SELECT id FROM helfer WHERE email = 'erik@example.org'")[0][0]
    _, _, seite = anfrage("GET", "/helfer/helfer/%d" % erik, glas=admin)
    pruefe("<dt>Macht gern</dt><dd>Draußen an der Strecke, Mit Menschen</dd>" in seite,
           "die Orga sieht bei der Person, was ihr liegt")
    status, _, _ = anfrage("POST", "/helfer/bereich/%d" % B["Merch"], {
        "csrf": csrf, "name": "Merchandise", "vorliebe-menschen": "1",
        "vorliebe-anpacken": "1"}, admin)
    zeile = testdb.abfrage(db_url, "helfer", "SELECT vorlieben FROM bereich WHERE id = %d" % B["Merch"])
    pruefe(status == 303 and zeile[0][0] in (["menschen", "anpacken"], "{menschen,anpacken}"),
           "und werden gespeichert: " + str(zeile))
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
