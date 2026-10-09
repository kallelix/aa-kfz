"""Noch eine Schicht?, das gemeinsame Ziel und die Druckansichten
(Lastenheft 2.6 und 2.8).

    python helfer/tests/test_druck.py

2.6: Vorschläge direkt nach dem Eintragen – am selben Tag und Ort, direkt
davor oder danach, nur was passt (G-03) – und die Tagesbalken auf der
Startseite (G-04). 2.8: Schicht, Bereich, Tag, Person und die Notfallmappe,
mit Kopf und Fuß, Abhakspalten und Telefonnummern (L-01 bis L-04), für die
Bereichsleitung nur ihre Bereiche, und nirgends eine Einsatzgrenze (K-07).
"""

import http.client
import os
import re
import socket
import subprocess
import sys
import time
import urllib.parse
from html import unescape
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WURZEL))
sys.path.insert(0, str(WURZEL.parent))
from kern import testdb  # noqa: E402
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


def freier_hafen():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def tupel(zeilen):
    return [tuple(z.values()) for z in zeilen]


db_url = testdb.wegwerf("helfer_druck")
os.environ.update({"DATABASE_URL": db_url, "APP_SECRET_KEY": "test-schluessel",
                   "JETZT_FEST": "2027-06-01 10:00", "KONTAKT_TELEFON": "0361 000000",
                   "KONTAKT_NAME": "Orga-Team Probe"})

from app import db, zugang  # noqa: E402

db.init()
VA = db.VERANSTALTUNGEN.anlegen({"name": "Die absolute Abfahrt 2027", "kurz": "AA 2027",
                                 "beginn": "2027-07-01", "ende": "2027-07-04",
                                 "ort": "Ilmenau", "status": "offen"})
db.angebot_setzen(VA, {"goodies": 1, "shirt": 1, "schnitte": 1, "verpflegung": 1, "party": 0})
db.goodie_anlegen(VA, {"name": "Bier am Bierwagen", "ab_schichten": 2, "ab_stunden": None,
                       "mindestalter": 16, "alternative": "Eistüte"})
LEER = {"beschreibung": "", "treffpunkt": "", "mindestalter": None, "voraussetzungen": "",
        "intern": 0}
SHUTTLE = db.bereich_anlegen(VA, {**LEER, "name": "Shuttle", "treffpunkt": "Parkplatz Talstation"})
STRECKE = db.bereich_anlegen(VA, {**LEER, "name": "Streckenposten", "treffpunkt": "Zelt am Ziel"})
KASSE = db.bereich_anlegen(VA, {**LEER, "name": "Kasse", "voraussetzungen": "Kassenschulung"})
ORGA = db.bereich_anlegen(VA, {**LEER, "name": "Orgabüro", "intern": 1})


def schicht(bereich, tag, von, bis, soll, reserve=0, alter=None):
    return db.schicht_anlegen(VA, bereich, {
        "datum": tag, "beginn": f"{tag} {von}", "ende": f"{tag} {bis}", "minimum": 1,
        "soll": soll, "reserve": reserve, "mindestalter": alter, "ort": "", "hinweis": "",
        "intern": 0})


FRUEH = schicht(SHUTTLE, "2027-07-02", "07:00", "12:00", 3, reserve=1)
MITTAG = schicht(SHUTTLE, "2027-07-02", "12:00", "17:00", 2)
ABEND = schicht(SHUTTLE, "2027-07-02", "17:00", "22:00", 2, alter=18)
POSTEN = schicht(STRECKE, "2027-07-02", "08:00", "13:00", 5)
POSTEN_NACHM = schicht(STRECKE, "2027-07-02", "14:00", "18:00", 2)
KASSE_FR = schicht(KASSE, "2027-07-02", "13:00", "16:00", 2)
POSTEN_SA = schicht(STRECKE, "2027-07-03", "08:00", "13:00", 4)
BUERO = schicht(ORGA, "2027-07-02", "09:00", "17:00", 2)

KONTEN = Konten(lambda: db_url)
KONTEN.anlegen(email="ada@example.org", name="Ada Admin", kuerzel="AD", rolle="admin",
               passwort="ein-langes-passwort")
KALLE = KONTEN.anlegen(email="kalle@example.org", name="Kalle Beispiel", kuerzel="KB",
                       rolle="bereichsleitung", passwort="kalles-langes-passwort",
                       telefon="0151 1111111")
db.leitung_setzen(SHUTTLE, [KALLE])

hafen = freier_hafen()
prozess = subprocess.Popen(
    [str(PYTHON), "-m", "app"], cwd=str(WURZEL),
    env={**os.environ, "BIND": f"127.0.0.1:{hafen}", "ADMIN_PASSWORD_HASH": HASH,
         "COOKIE_SECURE": "0", "ZEITPLAN_SERIEN": "", "PYTHONIOENCODING": "utf-8"},
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def zeilen(sql, *parameter):
    return tupel(testdb.abfrage(db_url, "helfer", sql, parameter))


def eingeteilt(schicht_id, helfer_id):
    return bool(zeilen("SELECT 1 FROM einteilung WHERE schicht_id = ? AND helfer_id = ?",
                       schicht_id, helfer_id))


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

    def melde_an(vorname, schichten=(), weitere=(), springer=(), volljaehrig="ja",
                 geburtsdatum="", telefon=""):
        daten = [("s", s) for s in schichten] + [("z", z) for z in springer]
        daten += [("ich-vorname", vorname), ("ich-nachname", "Berg"),
                  ("ich-email", vorname.lower() + "@example.org"), ("ich-telefon", telefon),
                  ("ich-volljaehrig", volljaehrig), ("ich-geburtsdatum", geburtsdatum),
                  ("ich-eltern_name", "Eva Berg"), ("ich-eltern_email", "eva@example.org"),
                  ("ich-tshirt", "M"), ("ich-schnitt", "damen"),
                  ("ich-verpflegung", "vegetarisch"), ("weitere", len(weitere)),
                  ("aktion", "anmelden"), ("voraussetzung", "Kassenschulung")]
        for i, w in enumerate(weitere):
            daten += [(f"p{i}-vorname", w), (f"p{i}-nachname", "Berg"),
                      (f"p{i}-volljaehrig", "ja"), (f"p{i}-tshirt", "L"),
                      (f"p{i}-schnitt", "herren"), (f"p{i}-verpflegung", "fleisch")]
        status, ort, _ = anfrage("POST", "/aa-2027/angaben", daten)
        return ort, int(re.search(r"p=(\d+)", ort).group(1)) if status == 303 else None

    print("Das gemeinsame Ziel (G-04)")
    status, _, seite = anfrage("GET", "/aa-2027")
    pruefe(status == 200 and "So weit sind wir" in seite and "Freitag, 02.07." in seite
           and "0 von 16 Plätzen besetzt" in seite and "0 von 4 Plätzen besetzt" in seite,
           "je Tag besetzt von geplant – ohne das interne Orgabüro, ohne Reserve")
    pruefe('<progress class="balken-bahn" max="16" value="0">' in seite and 'style=' not in seite,
           "als <progress> – ohne style-Attribut, das die CSP verböte")

    print("Noch eine Schicht? (G-03)")
    danke, ANNA = melde_an("Anna", [FRUEH], telefon="0151 2222222")
    _, _, seite = anfrage("GET", danke)
    vorschlaege = re.findall(r'name="s" value="(\d+)"', seite)
    pruefe("Noch eine Schicht bis: Bier am Bierwagen!" in seite,
           "Anna hat eine Schicht – die zweite reicht fürs Bier")
    pruefe(vorschlaege[:1] == [str(MITTAG)] and "direkt danach" in seite,
           "zuerst der Mittag im Shuttle, direkt danach")
    pruefe(str(POSTEN) not in vorschlaege and str(BUERO) not in vorschlaege
           and str(KASSE_FR) not in vorschlaege and len(vorschlaege) <= 3,
           "nichts, was sich überschneidet, nichts Internes, keine unbestätigte Voraussetzung")
    status, _, seite = anfrage("POST", danke.replace("/danke", "/noch"), {"s": POSTEN})
    pruefe(status == 409 and not eingeteilt(POSTEN, ANNA), "was nicht vorgeschlagen war, geht so nicht")
    status, ort, _ = anfrage("POST", danke.replace("/danke", "/noch"), {"s": MITTAG})
    pruefe(status == 303 and "hinweis=noch" in ort and eingeteilt(MITTAG, ANNA)
           and zeilen("SELECT email_bestaetigt_am FROM helfer WHERE id = ?", ANNA) == [(None,)],
           "ein Klick, und Anna steht drin – bestätigt ist damit noch nichts")
    _, _, seite = anfrage("GET", ort)
    pruefe("Eingetragen" in seite and "Noch eine Schicht bis" not in seite,
           "die Seite sagt Danke; das Bier ist erreicht")

    danke, BERT = melde_an("Bert", [POSTEN_NACHM], weitere=["Berta"])
    pruefe(danke is not None and zeilen(
        "SELECT COUNT(*) FROM einteilung WHERE schicht_id = ?", POSTEN_NACHM) == [(2,)],
        "Bert bringt Berta mit")
    _, _, seite = anfrage("GET", danke) if danke else (0, "", "")
    pruefe("Für alle eintragen" in seite and str(MITTAG) not in re.findall(r'name="s" value="(\d+)"', seite),
           "für zwei: nur, wo noch zwei Plätze frei sind")

    danke, EMIL = melde_an("Emil", [MITTAG], volljaehrig="nein", geburtsdatum="2011-03-01")
    _, _, seite = anfrage("GET", danke)
    pruefe(str(ABEND) not in re.findall(r'name="s" value="(\d+)"', seite),
           "Emil ist 16 – der Abend ab 18 wird ihm nicht vorgeschlagen")

    db.bestaetigen(ANNA)
    platz = "/platz/" + zugang.token(zugang.PLATZ, db.helfer_laden(ANNA))
    _, _, seite = anfrage("GET", platz)
    pruefe("Noch eine Schicht" not in seite, "in Mein Helferplatz nicht bei jedem Besuch")
    _, _, seite = anfrage("GET", platz + "?hinweis=dazu")
    pruefe("Noch eine Schicht" in seite and f"/aa-2027/angaben?s=" in seite,
           "aber gleich nach dem Eintragen, mit dem Weg zum Dazunehmen")

    print("Druckansichten (L-01 bis L-04)")
    melde_an("Cleo", [FRUEH])
    melde_an("Dora", [FRUEH])
    melde_an("Ida", springer=["2027-07-02|frueh"], telefon="0170 3333333")
    db.grenze_setzen(VA, ANNA, "nur_zu_zweit", bereich_id=SHUTTLE, wer="AD")
    admin = {}
    anfrage("POST", "/helfer/login", {"email": "ada@example.org", "passwort": "ein-langes-passwort",
                                      "weiter": "/helfer"}, admin)
    status, _, seite = anfrage("GET", "/helfer/druck", glas=admin)
    pruefe(status == 200 and 'href="/helfer/druck/mappe/2027-07-02"' in seite
           and f'href="/helfer/druck/bereich/{SHUTTLE}?tag=2027-07-02"' in seite,
           "die Auswahl: je Tag Liste und Notfallmappe, je Bereich und Tag")
    pruefe('href="/helfer/druck"' in seite, "Drucken steht in der Navigation")
    status, _, seite = anfrage("GET", f"/helfer/druck/schicht/{FRUEH}", glas=admin)
    pruefe(status == 200 and "Shuttle · Fr 02.07. 07:00–12:00" in seite
           and "Treffpunkt: Parkplatz Talstation" in seite
           and "Bereichsleitung: Kalle Beispiel 0151 1111111" in seite,
           "Kopf: Bereich, Zeit, Treffpunkt, Bereichsleitung mit Nummer (L-02)")
    pruefe("Anna Berg" in seite and "+49 1512222222" in seite and "Cleo Berg" in seite
           and "Damen M" in seite, "die Leute mit Nummer und Shirt")
    pruefe(seite.count("☐") >= 3 * 4 and "<th class=\"haken\">da</th>" in seite
           and "Funk</th>" in seite and "Shirt</th>" in seite, "Spalten zum Abhaken: da, Shirt, Funk (L-01)")
    pruefe("Stand 01.06.2027 10:00" in seite and "vernichten" in seite, "Fuß: Stand mit Uhrzeit")
    pruefe("zweit" not in seite and "Grenze" not in seite, "keine Einsatzgrenze auf dem Papier (K-07)")
    status, _, seite = anfrage("GET", f"/helfer/druck/schicht/{POSTEN_NACHM}", glas=admin)
    pruefe("Berta Berg" in seite and "über Bert Berg" in seite,
           "wer mitangemeldet ist, wird über die Person erreicht, die angemeldet hat")
    status, _, seite = anfrage("GET", "/helfer/druck/tag/2027-07-02", glas=admin)
    pruefe(status == 200 and "Shuttle" in seite and "Streckenposten" in seite
           and "Sa 03.07." not in seite, "der ganze Tag, ohne die anderen Tage")
    status, _, seite = anfrage("GET", "/helfer/druck/mappe/2027-07-02", glas=admin)
    pruefe(status == 200 and "Notfallmappe" in seite and "Orga-Team Probe · 0361 000000" in seite
           and "Kalle Beispiel · 0151 1111111" in seite, "Notfallmappe: Deckblatt mit Orga und Bereichsleitungen")
    pruefe("Ida Berg" in seite and "+49 1703333333" in seite and "06:00–13:00" in seite,
           "und den Springern des Tages (L-03)")
    pruefe(seite.count('class="bereich neue-seite"') >= 3, "je Bereich eine eigene Seite")
    status, _, seite = anfrage("GET", f"/helfer/druck/bereich/{SHUTTLE}?tag=2027-07-02", glas=admin)
    pruefe(status == 200 and seite.count('class="schicht"') == 3, "ein Bereich an einem Tag")
    status, _, seite = anfrage("GET", f"/helfer/druck/bereich/{STRECKE}", glas=admin)
    pruefe(seite.count('class="schicht"') == 3, "oder an allen Tagen")
    status, _, seite = anfrage("GET", f"/helfer/druck/person/{ANNA}", glas=admin)
    pruefe(status == 200 and "Anna Berg" in seite and "Parkplatz Talstation" in seite
           and "Kalle Beispiel" in seite, "die Person mit ihren Schichten")
    for pfad in ("/helfer/druck/tag/quatsch", "/helfer/druck/schicht/99999"):
        status, _, _ = anfrage("GET", pfad, glas=admin)
        pruefe(status == 404, pfad + " gibt es nicht")
    status, _, _ = anfrage("GET", "/helfer/static/druck.css")
    pruefe(status == 200, "das Druck-Stylesheet wird ausgeliefert")
    _, _, seite = anfrage("GET", f"/helfer/schicht/{FRUEH}", glas=admin)
    pruefe(f'href="/helfer/druck/schicht/{FRUEH}"' in seite, "die Schicht verweist auf ihre Liste")

    print("Bereichsleitung")
    kalle = {}
    anfrage("POST", "/helfer/login", {"email": "kalle@example.org",
                                      "passwort": "kalles-langes-passwort", "weiter": "/helfer"}, kalle)
    status, _, seite = anfrage("GET", f"/helfer/druck/schicht/{FRUEH}", glas=kalle)
    pruefe(status == 200 and "Anna Berg" in seite, "ihre Schicht druckt sie")
    status, _, _ = anfrage("GET", f"/helfer/druck/schicht/{POSTEN}", glas=kalle)
    pruefe(status == 403, "eine fremde nicht")
    status, _, seite = anfrage("GET", "/helfer/druck/mappe/2027-07-02", glas=kalle)
    pruefe(status == 200 and "Shuttle" in seite and "Streckenposten" not in seite,
           "ihre Notfallmappe hat nur ihren Bereich")
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
