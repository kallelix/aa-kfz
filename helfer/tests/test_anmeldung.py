"""Die öffentliche Anmeldung (Lastenheft 2.2).

    python helfer/tests/test_anmeldung.py

Erst das Prüfen der Angaben ohne Server, dann der ganze Weg über HTTP:
Startseite, Schichtliste, Angaben, Danke – mit Platz, Reserve und voll,
Überschneidungen, Mindestalter, Mitanmeldung, Springer und vorgemerktem
Interesse.
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
GEHEIM = "test-schluessel"

fehler = []


def pruefe(bedingung, text):
    print(("  ok   " if bedingung else "  FEHL ") + text)
    if not bedingung:
        fehler.append(text)


def freier_hafen():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def tupel(zeilen):
    return [tuple(z.values()) for z in zeilen]


db_url = testdb.wegwerf("helfer_anmeldung")
os.environ["DATABASE_URL"] = db_url

from app import db, normalisieren
from app import selbstanmeldung as anmeldung  # noqa: E402

# --- Prüfen ohne Datenbank -------------------------------------------------

ANGEBOT = {"goodies": 1, "shirt": 1, "schnitte": 1, "verpflegung": 1, "party": 0}
STICHTAG = date(2027, 7, 1)
GUT = {"ich-vorname": " Anna ", "ich-nachname": "Berg", "ich-email": "Anna@Example.org",
       "ich-telefon": "0151 234 56 78", "ich-volljaehrig": "ja", "ich-tshirt": "M",
       "ich-schnitt": "damen", "ich-verpflegung": "vegetarisch"}

print("Angaben prüfen")
werte, f = anmeldung.person_pruefen(GUT, "ich-", ANGEBOT, STICHTAG, True)
pruefe(not f, "vollständige Angaben gehen durch")
pruefe(werte["name"] == "Anna Berg" and werte["email"] == "anna@example.org",
       "Name zusammengesetzt, Adresse klein")
pruefe(werte["telefon"] == "+49 1512345678", "die Nummer in einheitlicher Form (I-04)")
pruefe(werte["tshirt"] == "M" and werte["tshirt_roh"] == "Damen M" and werte["veggie"] == 1,
       "Shirt mit Schnitt, vegetarisch")
_, f = anmeldung.person_pruefen({**GUT, "ich-nachname": ""}, "ich-", ANGEBOT, STICHTAG, True)
pruefe("ich-nachname" in f, "ohne Nachnamen nicht (I-01)")
_, f = anmeldung.person_pruefen({**GUT, "ich-email": "anna@"}, "ich-", ANGEBOT, STICHTAG, True)
pruefe("ich-email" in f, "eine halbe Adresse wird gemeldet")
_, f = anmeldung.person_pruefen({**GUT, "ich-telefon": "ruf mich an"}, "ich-", ANGEBOT, STICHTAG, True)
pruefe("ich-telefon" in f, "Buchstaben sind keine Nummer")
_, f = anmeldung.person_pruefen({**GUT, "ich-volljaehrig": ""}, "ich-", ANGEBOT, STICHTAG, True)
pruefe("ich-volljaehrig" in f, "das Alter muss gefragt sein")
werte, f = anmeldung.person_pruefen({**GUT, "ich-volljaehrig": "nein",
                                     "ich-geburtsdatum": "2011-03-01"}, "ich-", ANGEBOT, STICHTAG, True)
pruefe(not f and werte["alter"] == 16 and werte["volljaehrig"] == 0, "16 Jahre am ersten Tag")
_, f = anmeldung.person_pruefen({**GUT, "ich-volljaehrig": "nein",
                                 "ich-geburtsdatum": "2016-01-01"}, "ich-", ANGEBOT, STICHTAG, True)
pruefe("ich-geburtsdatum" in f, "unter 12 geht es nicht (D-06)")
_, f = anmeldung.person_pruefen({**GUT, "ich-schnitt": ""}, "ich-", ANGEBOT, STICHTAG, True)
pruefe("ich-schnitt" in f, "mit zwei Schnitten muss einer gewählt sein")
werte, f = anmeldung.person_pruefen({**GUT, "ich-tshirt": "kein", "ich-schnitt": ""},
                                    "ich-", ANGEBOT, STICHTAG, True)
pruefe(not f and werte["tshirt"] is None and werte["tshirt_roh"] == "kein Shirt",
       "„kein Shirt“ geht, dann ohne Schnitt")
werte, f = anmeldung.person_pruefen({"ich-vorname": "A", "ich-nachname": "B",
                                     "ich-email": "a@b.de", "ich-volljaehrig": "ja"},
                                    "ich-", {"shirt": 0, "verpflegung": 0}, STICHTAG, True)
pruefe(not f and werte["tshirt"] is None and werte["veggie"] is None,
       "ohne Shirt und Verpflegung fragt die Anmeldung danach nicht (I-02)")
werte, f = anmeldung.person_pruefen({"p0-vorname": "Ben", "p0-nachname": "Berg",
                                     "p0-volljaehrig": "ja", "p0-tshirt": "L",
                                     "p0-schnitt": "herren", "p0-verpflegung": "fleisch"},
                                    "p0-", ANGEBOT, STICHTAG, False)
pruefe(not f and werte["email"] == "", "wer mitkommt, braucht keine eigene Adresse (A-08)")

print("Springer-Zeiten und Überschneidungen")
tage = [date(2027, 7, d) for d in (1, 2, 3, 4)]
fenster = anmeldung.springer_fenster(["2027-07-03|abend", "2027-07-03|frueh", "2027-08-01|frueh",
                                      "2027-07-03|quatsch"], tage)
pruefe(fenster == [("2027-07-03|frueh", "2027-07-03 06:00", "2027-07-03 13:00"),
                   ("2027-07-03|abend", "2027-07-03 17:00", "2027-07-04 00:00")],
       "nach Zeit sortiert, der Abend endet um Mitternacht, Fremdes fällt weg")
pruefe(anmeldung.ueberschneidungen([("A", "2027-07-02 07:00", "2027-07-02 12:00"),
                                    ("B", "2027-07-02 12:00", "2027-07-02 17:00"),
                                    ("C", "2027-07-02 11:00", "2027-07-02 13:00")])
       == [("A", "C"), ("B", "C")], "Anschluss ist keine Überschneidung, Überlappung schon")
pruefe(normalisieren.kurzadresse("AA 2027") == "aa-2027", "der Kurzlink der Veranstaltung")

# --- Über HTTP --------------------------------------------------------------

db.init()
GRUND = {"name": "Die absolute Abfahrt 2027", "kurz": "AA 2027", "beginn": "2027-07-01",
         "ende": "2027-07-04", "ort": "Ilmenau", "status": "offen"}
VA = db.VERANSTALTUNGEN.anlegen(GRUND)
db.angebot_setzen(VA, {"goodies": 1, "shirt": 1, "schnitte": 1, "verpflegung": 1, "party": 1})
LEER = {"beschreibung": "", "treffpunkt": "", "mindestalter": None, "voraussetzungen": "",
        "intern": 0}
SHUTTLE = db.bereich_anlegen(VA, {**LEER, "name": "Shuttle", "treffpunkt": "Parkplatz Talstation",
                                  "mindestalter": 18, "voraussetzungen": "Führerschein Klasse B",
                                  "beschreibung": "Ihr fahrt die Rennfahrer auf den Berg."})
STRECKE = db.bereich_anlegen(VA, {**LEER, "name": "Streckenposten", "treffpunkt": "Zelt am Ziel"})
ORGA = db.bereich_anlegen(VA, {**LEER, "name": "Orgabüro", "intern": 1})


def schicht(bereich, tag, von, bis, soll, reserve=0, minimum=None):
    return db.schicht_anlegen(VA, bereich, {
        "datum": tag, "beginn": f"{tag} {von}", "ende": f"{tag} {bis}",
        "minimum": soll if minimum is None else minimum, "soll": soll, "reserve": reserve,
        "mindestalter": None, "ort": "", "hinweis": "", "intern": 0})


FRUEH = schicht(SHUTTLE, "2027-07-02", "07:00", "12:00", 1, reserve=1)
MITTAG = schicht(SHUTTLE, "2027-07-02", "12:00", "17:00", 2)
POSTEN = schicht(STRECKE, "2027-07-02", "08:00", "13:00", 3, minimum=2)
POSTEN_SA = schicht(STRECKE, "2027-07-03", "08:00", "13:00", 2)
BUERO = schicht(ORGA, "2027-07-01", "09:00", "18:00", 2)

hafen = freier_hafen()
prozess = subprocess.Popen(
    [str(PYTHON), "-m", "app"], cwd=str(WURZEL),
    env={**os.environ, "DATABASE_URL": db_url, "BIND": f"127.0.0.1:{hafen}",
         "ADMIN_PASSWORD_HASH": HASH, "APP_SECRET_KEY": GEHEIM, "COOKIE_SECURE": "0",
         "ZEITPLAN_SERIEN": "", "JETZT_FEST": "2027-06-01 10:00", "PYTHONIOENCODING": "utf-8"},
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def zeilen(sql, *parameter):
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

    kekse = {}

    def anfrage(methode, pfad, daten=None):
        verbindung = http.client.HTTPConnection("127.0.0.1", hafen, timeout=10)
        koerper = urllib.parse.urlencode(daten, doseq=True).encode() if daten else None
        kopf = {"Content-Type": "application/x-www-form-urlencoded"} if koerper else {}
        if kekse:
            kopf["Cookie"] = "; ".join(k + "=" + w for k, w in kekse.items())
        verbindung.request(methode, pfad, body=koerper, headers=kopf)
        antwort = verbindung.getresponse()
        for gesetzt in antwort.headers.get_all("Set-Cookie") or []:
            name, _, wert = gesetzt.split(";")[0].partition("=")
            kekse[name] = wert
        ergebnis = (antwort.status, antwort.getheader("Location", ""),
                    antwort.read().decode("utf-8"))
        verbindung.close()
        return ergebnis

    def angaben(schichten, person=None, weitere=(), springer=(), **extra):
        daten = [("s", s) for s in schichten] + [("z", z) for z in springer]
        daten += list({**GUT, **(person or {})}.items())
        daten += [("weitere", len(weitere)), ("aktion", "anmelden")]
        for i, w in enumerate(weitere):
            daten += [(f"p{i}-{k}", v) for k, v in w.items()]
        daten += list(extra.items())
        return anfrage("POST", "/aa-2027/angaben", daten)

    print("Startseite und Liste")
    status, ort, _ = anfrage("GET", "/")
    pruefe(status == 303 and ort == "/aa-2027", "/ führt zur einzigen offenen Veranstaltung")
    status, _, seite = anfrage("GET", "/aa-2027")
    pruefe(status == 200 and 'href="/aa-2027/schichten"' in seite and "1. bis 4. Juli 2027" in seite,
           "die Startseite der Veranstaltung mit dem Weg zur Liste")
    status, _, seite = anfrage("GET", "/aa-2027/schichten")
    pruefe(status == 200 and "Shuttle" in seite and "Streckenposten" in seite
           and "Orgabüro" not in seite, "die Liste ohne interne Schichten (V-06)")
    pruefe("noch 1 frei" in seite and "noch 3 frei" in seite and "ab 18" in seite
           and "Führerschein Klasse B" in seite, "freie Plätze, Alter und Voraussetzung (A-06)")
    pruefe("Freitag, 02.07." in seite and 'name="z" value="2027-07-03|frueh"' in seite,
           "nach Tag gegliedert, darunter die Springer-Zeiten")
    pruefe('data-filter="tag" hidden' in seite and "anmeldung.js" in seite,
           "Filter nur mit Skript")
    status, ort, _ = anfrage("GET", "/aa-2027/angaben")
    pruefe(status == 303 and "hinweis=leer" in ort, "ohne Auswahl zurück zur Liste")
    status, _, seite = anfrage("GET", f"/aa-2027/angaben?s={FRUEH}&s={BUERO}")
    pruefe(status == 200 and "Shuttle" in seite and "Orgabüro" not in seite
           and "Ich habe: Führerschein Klasse B" in seite,
           "die Angaben zeigen die Auswahl, ohne Internes, mit der Voraussetzung")
    pruefe('name="ich-schnitt"' in seite and 'name="ich-verpflegung"' in seite,
           "Shirt mit Schnitt und Essen, weil die Veranstaltung beides bietet")

    print("Anmelden: Platz, Reserve, voll")
    status, _, seite = angaben([FRUEH])
    pruefe(status == 400 and "bestätigen" in seite, "ohne bestätigte Voraussetzung nicht")
    status, ort, _ = angaben([FRUEH], voraussetzung="Führerschein Klasse B")
    pruefe(status == 303 and "/aa-2027/danke?p=" in ort, "Anna ist angemeldet")
    anna = int(re.search(r"p=(\d+)", ort).group(1))
    status, _, seite = anfrage("GET", ort)
    pruefe(status == 200 and "Danke, Anna!" in seite and "Shuttle" in seite
           and "Reserve" not in seite, "die Dankeseite zeigt ihre Schicht")
    status, _, _ = anfrage("GET", ort.replace("&t=", "&t=0"))
    pruefe(status == 404, "ohne das richtige Siegel keine fremde Dankeseite")
    pruefe(zeilen("SELECT vorname, nachname, telefon, tshirt, tshirt_roh, veggie, volljaehrig"
                  " FROM helfer WHERE id = ?", anna)
           == [("Anna", "Berg", "+49 1512345678", "M", "Damen M", 1, 1)],
           "ihre Angaben stehen in helfer")
    pruefe(zeilen("SELECT quelle, art FROM einteilung WHERE helfer_id = ?", anna)
           == [("selbst", "platz")], "auf einem Platz, selbst eingetragen")
    pruefe(zeilen("SELECT quelle FROM teilnahme WHERE helfer_id = ? AND veranstaltung_id = ?",
                  anna, VA) == [("selbst",)], "und als Teilnahme an der AA")

    status, ort, _ = angaben([FRUEH], {"ich-vorname": "Bert", "ich-email": "bert@example.org"},
                             voraussetzung="Führerschein Klasse B")
    bert = int(re.search(r"p=(\d+)", ort).group(1))
    _, _, seite = anfrage("GET", ort)
    pruefe("Du bist Reserve" in seite, "ist das Soll erreicht, wird man Reserve (R-03)")
    status, _, seite = angaben([FRUEH], {"ich-vorname": "Cleo", "ich-email": "cleo@example.org"},
                               voraussetzung="Führerschein Klasse B")
    pruefe(status == 409 and "inzwischen voll" in seite, "ist auch die Reserve voll, geht es nicht")
    _, _, seite = anfrage("GET", "/aa-2027/schichten")
    pruefe(f'name="s" value="{FRUEH}"' not in seite, "eine volle Schicht ist nicht mehr wählbar")

    print("Überschneidungen und Doppeltes")
    status, _, seite = angaben([MITTAG, POSTEN], {"ich-vorname": "Dora", "ich-email": "dora@example.org"},
                               voraussetzung="Führerschein Klasse B")
    pruefe(status == 409 and "überschneiden sich" in seite, "zwei Schichten zur selben Zeit nicht (K-01)")
    status, _, seite = angaben([POSTEN], voraussetzung="Führerschein Klasse B")
    pruefe(status == 409 and "überschneidet sich mit Shuttle" in seite,
           "auch nicht mit dem, was jemand schon hat")
    status, _, seite = angaben([FRUEH], voraussetzung="Führerschein Klasse B")
    pruefe(status == 409 and "schon eingetragen" in seite, "dieselbe Schicht nicht zweimal")
    status, ort, _ = angaben([POSTEN_SA])
    pruefe(status == 303 and zeilen("SELECT COUNT(*) FROM einteilung WHERE helfer_id = ?", anna)
           == [(2,)], "wer wiederkommt, bekommt die neue Schicht dazu – derselbe Mensch")

    print("Alter und Mitanmeldung")
    jung = {"ich-vorname": "Emil", "ich-email": "emil@example.org", "ich-volljaehrig": "nein",
            "ich-geburtsdatum": "2011-03-01"}
    status, _, seite = angaben([MITTAG], jung, voraussetzung="Führerschein Klasse B")
    pruefe(status == 409 and "erst ab 18" in seite, "mit 16 nicht beim Shuttle (D-07)")
    status, _, seite = angaben([POSTEN], {**jung, "ich-geburtsdatum": "2018-01-01"})
    pruefe(status == 400 and "ab 12 Jahren" in seite, "unter 12 gar nicht (D-06)")
    status, ort, _ = angaben([POSTEN], jung)
    pruefe(status == 303, "mit 16 an die Strecke geht")
    familie = [{"vorname": "Fritz", "nachname": "Feld", "volljaehrig": "ja", "tshirt": "L",
                "schnitt": "herren", "verpflegung": "fleisch"}]
    status, ort, _ = angaben([MITTAG], {"ich-vorname": "Frieda", "ich-nachname": "Feld",
                                        "ich-email": "feld@example.org"},
                             weitere=familie, voraussetzung="Führerschein Klasse B")
    pruefe(status == 303, "Frieda meldet Fritz mit an (A-08)")
    frieda = int(re.search(r"p=(\d+)", ort).group(1))
    pruefe(zeilen("SELECT name, email, angemeldet_von FROM helfer WHERE angemeldet_von = ?", frieda)
           == [("Fritz Feld", "", frieda)], "Fritz ohne eigene Adresse, Frieda bleibt Ansprechpartnerin")
    pruefe(zeilen("SELECT COUNT(*) FROM einteilung WHERE schicht_id = ? AND art = 'platz'", MITTAG)
           == [(2,)], "beide zählen eigens")
    _, _, seite = anfrage("GET", ort)
    pruefe("Schichten von Fritz" in seite, "die Dankeseite nennt beide")
    status, _, seite = angaben([MITTAG], {"ich-vorname": "Gert", "ich-email": "gert@example.org"},
                               weitere=[{**familie[0], "vorname": "Gerda"}],
                               voraussetzung="Führerschein Klasse B")
    pruefe(status == 409 and ("voll" in seite or "nicht mehr für alle" in seite),
           "für zwei weitere ist kein Platz mehr")

    print("Weitere Person dazu und weg, ohne Skript")
    basis = [("s", POSTEN_SA)] + list(GUT.items())
    status, _, seite = anfrage("POST", "/aa-2027/angaben", basis + [("weitere", 0), ("aktion", "dazu")])
    pruefe(status == 200 and "Weitere Person 1" in seite and 'value=" Anna "' in seite,
           "„+ Weitere Person“ bringt einen Block, die Eingabe bleibt")
    status, _, seite = anfrage("POST", "/aa-2027/angaben",
                               basis + [("weitere", 1), ("p0-vorname", "X"), ("aktion", "weg-0")])
    pruefe(status == 200 and "Weitere Person 1" not in seite, "und „entfernen“ nimmt ihn wieder weg")

    print("Springer")
    status, ort, _ = angaben([], {"ich-vorname": "Hanna", "ich-email": "hanna@example.org"},
                             springer=["2027-07-03|frueh", "2027-07-03|abend"])
    pruefe(status == 303, "nur als Springer geht auch (R-05)")
    hanna = int(re.search(r"p=(\d+)", ort).group(1))
    pruefe(zeilen("SELECT beginn, ende, springer FROM verfuegbarkeit WHERE helfer_id = ?"
                  " ORDER BY beginn", hanna)
           == [("2027-07-03 06:00", "2027-07-03 13:00", 1), ("2027-07-03 17:00", "2027-07-04 00:00", 1)],
           "mit ihren Zeitfenstern")
    status, _, seite = angaben([POSTEN_SA], {"ich-vorname": "Ida", "ich-email": "ida@example.org"},
                               springer=["2027-07-03|frueh"])
    pruefe(status == 409 and "Springer" in seite, "Springer-Zeit und Schicht zugleich nicht (K-04)")

    print("Roboter und Backoffice")
    vorher = zeilen("SELECT COUNT(*) FROM helfer")
    status, ort, _ = angaben([POSTEN_SA], {"ich-vorname": "Bot", "ich-email": "bot@example.org"},
                             webseite="http://spam.example")
    pruefe(status == 303 and zeilen("SELECT COUNT(*) FROM helfer") == vorher,
           "wer das unsichtbare Feld füllt, legt nichts an")
    anfrage("POST", "/helfer/login", {"passwort": "test-passwort-123", "kuerzel": "KK",
                                      "weiter": "/helfer"})
    _, _, seite = anfrage("GET", f"/helfer/schicht/{FRUEH}")
    pruefe("selbst angemeldet" in seite and "Reserve" in seite and "Anna Berg" in seite,
           "das Backoffice zeigt, wer sich selbst eingetragen hat und wer Reserve ist")
    pruefe("1 von 1" in seite and "(1 belegt)" in seite, "Reserve zählt nicht als besetzt")

    print("Angekündigt, geschlossen, in Planung")
    db.VERANSTALTUNGEN.aendern(VA, {**GRUND, "status": "angekuendigt",
                                    "anmeldung_ab": "2027-06-15"})
    status, _, seite = anfrage("GET", "/aa-2027")
    pruefe(status == 200 and "15.06.2027" in seite and 'action="/aa-2027/interesse"' in seite,
           "angekündigt: wann es losgeht, und Interesse vormerken (V-02)")
    status, ort, _ = anfrage("GET", "/aa-2027/schichten")
    pruefe(status == 303, "die Liste gibt es noch nicht")
    status, _, seite = anfrage("POST", "/aa-2027/interesse", {"email": "ich@example.org"})
    pruefe(status == 400 and "Häkchen" in seite, "ohne Einverständnis wird nichts vorgemerkt")
    status, ort, _ = anfrage("POST", "/aa-2027/interesse", {"email": "Ich@Example.org",
                                                           "vorname": "Jo", "einverstanden": "1"})
    anfrage("POST", "/aa-2027/interesse", {"email": "ich@example.org", "einverstanden": "1"})
    pruefe(status == 303 and "vorgemerkt=1" in ort
           and zeilen("SELECT email, vorname FROM interesse") == [("ich@example.org", "Jo")],
           "vorgemerkt – einmal, auch beim zweiten Mal")
    db.VERANSTALTUNGEN.aendern(VA, {**GRUND, "status": "geschlossen"})
    _, _, seite = anfrage("GET", "/aa-2027")
    pruefe("geschlossen" in seite and "/aa-2027/schichten" not in seite, "geschlossen: kein Weg zur Liste")
    db.VERANSTALTUNGEN.aendern(VA, {**GRUND, "status": "planung"})
    status, _, _ = anfrage("GET", "/aa-2027")
    pruefe(status == 404, "in Planung gibt es öffentlich nichts")
    status, _, seite = anfrage("GET", "/")
    pruefe(status == 200 and "suchen wir keine Helfer" in seite, "und die Startseite sagt das")

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
