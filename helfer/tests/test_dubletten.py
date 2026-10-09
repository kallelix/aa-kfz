"""Dubletten zusammenführen (Lastenheft 3.2: I-06).

    python helfer/tests/test_dubletten.py

Lena Müller und Lena Mueller sind ein Mensch, zweimal angelegt. Nach dem
Zusammenführen ist sie einmal da – mit allem, was an beiden hing:
Schichten, Warteliste, Springer-Zeiten, Teilnahme, Grenzen, Ausleihe,
Shirt und Unterschrift, Absage, Mails, Verlauf, wen sie mitgebracht hat.
Was doppelt wäre, bleibt einmal; ein so frei gewordener Platz geht an die
Reserve. Und zwei, die nur so aussehen, lassen sich auseinanderhalten.
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


db_url = testdb.wegwerf("helfer_dubletten")
os.environ.update({"DATABASE_URL": db_url, "APP_SECRET_KEY": "test-schluessel",
                   "JETZT_FEST": "2027-06-01 10:00"})

from app import db  # noqa: E402

db.init()
VA = db.VERANSTALTUNGEN.anlegen({"name": "Die absolute Abfahrt 2027", "kurz": "AA 2027",
                                 "beginn": "2027-07-01", "ende": "2027-07-04",
                                 "ort": "Ilmenau", "status": "offen"})
BEREICH = db.bereich_anlegen(VA, {"name": "Strecke", "beschreibung": "", "treffpunkt": "",
                                  "mindestalter": None, "voraussetzungen": "", "intern": 0})


def schicht(von, bis, soll, reserve=0):
    return db.schicht_anlegen(VA, BEREICH, {
        "datum": "2027-07-02", "beginn": f"2027-07-02 {von}", "ende": f"2027-07-02 {bis}",
        "minimum": 1, "soll": soll, "reserve": reserve, "mindestalter": None,
        "ort": "", "hinweis": "", "intern": 0})


S1 = schicht("08:00", "10:00", 2, reserve=1)
S2 = schicht("10:00", "12:00", 2, reserve=2)
S3 = schicht("12:00", "14:00", 1)


def sql(text, *parameter):
    return testdb.abfrage(db_url, "helfer", text, parameter)


def person(name, email, **mehr):
    nummer, _ = db.helfer_von_hand({"name": name, "email": email})
    if mehr:
        sql("UPDATE helfer SET " + ", ".join(k + " = ?" for k in mehr) + " WHERE id = ?",
            *mehr.values(), nummer)
    return nummer


def einteilen(schicht_id, helfer_id, art="platz"):
    sql("INSERT INTO einteilung (schicht_id, helfer_id, quelle, art, eingeteilt_am)"
        " VALUES (?, ?, 'selbst', ?, '2027-05-01 10:00')", schicht_id, helfer_id, art)


LENA = person("Lena Müller", "lena@example.org", bemerkung="kommt mit dem Rad")
LENA2 = person("Lena Mueller", "lena@example.org", telefon="+491511234567", tshirt="M",
               veggie=1, tshirt_ausgegeben_am="2027-05-20 18:00", tshirt_ausgegeben="M",
               tshirt_kuerzel="KK", bemerkung="isst vegetarisch")
DORA = person("Dora Reserve", "dora@example.org")
KIND = person("Kai Mueller", "lena@example.org", angemeldet_von=LENA2)

# Beide auf S1 – derselbe Mensch zweimal, ein Platz zu viel. Dora wartet als
# Reserve.
einteilen(S1, LENA)
einteilen(S1, LENA2)
einteilen(S1, DORA, "reserve")
einteilen(S2, LENA2, "reserve")
sql("INSERT INTO warteliste (schicht_id, helfer_id, angelegt_am) VALUES (?, ?, '2027-05-02 10:00')",
    S3, LENA2)
for helfer_id, vorlieben, bemerkung in ((LENA, "{strecke}", "mit Rad"),
                                       (LENA2, "{menschen}", "vegetarisch bitte")):
    sql("INSERT INTO teilnahme (veranstaltung_id, helfer_id, quelle, vorlieben, bemerkung,"
        " angemeldet_am) VALUES (?, ?, 'selbst', ?, ?, '2027-05-01 10:00')",
        VA, helfer_id, vorlieben, bemerkung)
for helfer_id, von in ((LENA, "06:00"), (LENA2, "06:00"), (LENA2, "17:00")):
    sql("INSERT INTO verfuegbarkeit (veranstaltung_id, helfer_id, beginn, ende, springer,"
        " angelegt_am) VALUES (?, ?, ?, ?, 1, '2027-05-01 10:00')",
        VA, helfer_id, "2027-07-03 " + von, "2027-07-03 " + ("13:00" if von == "06:00" else "23:00"))
for helfer_id in (LENA, LENA2):
    sql("INSERT INTO einsatzgrenze (helfer_id, bereich_id, art, angelegt_am)"
        " VALUES (?, ?, 'nur_zu_zweit', '2027-05-01 10:00')", helfer_id, BEREICH)
sql("INSERT INTO ausleihe (veranstaltung_id, helfer_id, funke, ausgegeben_am)"
    " VALUES (?, ?, 1, '2027-05-20 18:00')", VA, LENA2)
sql("INSERT INTO unterschrift (art, vorgang_id, richtung, titel, wortlaut, angefordert_am,"
    " laeuft_ab_am) VALUES ('tshirt', ?, 'ausgabe', 'T-Shirt Ausgabe', 'T-Shirt in Größe M',"
    " '2027-05-20 18:00', '2027-05-20 18:05')", LENA2)
sql("INSERT INTO absage (veranstaltung_id, schicht_id, helfer_id, name, am)"
    " VALUES (?, ?, ?, 'Lena Mueller', '2027-05-10 10:00')", VA, S3, LENA2)
sql("INSERT INTO mail_out (helfer_id, typ, empfaenger, betreff, body, angelegt_am)"
    " VALUES (?, 'test', 'lena@example.org', 'Hallo', 'Text', '2027-05-10 10:00')", LENA2)
sql("INSERT INTO protokoll (helfer_id, wer, was, am) VALUES (?, 'selbst', 'Angaben geändert',"
    " '2027-05-10 10:00')", LENA2)

# Zwei Menschen, die nur so aussehen: Geschwister mit einer Nummer.
JOERG = person("Jörg Weiß", "joerg@example.org", telefon="+491609999999")
JOERG2 = person("Joerg Weiss", "", telefon="+491609999999")

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

    glas = {}

    def anfrage(methode, pfad, daten=None):
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

    anfrage("POST", "/helfer/login", {"passwort": "test-passwort-123", "kuerzel": "KK",
                                      "weiter": "/helfer"})

    print("Erkennen")
    pruefe({(d["a_id"], d["b_id"]) for d in db.moegliche_dubletten()} >= {(LENA, LENA2), (JOERG, JOERG2)},
           "beide Paare stehen unter den möglichen Dubletten")
    _, _, seite = anfrage("GET", "/helfer")
    pruefe('href="/helfer/zusammenfuehren?a=%d&b=%d"' % (LENA, LENA2) in seite,
           "die Übersicht führt zum Vergleich")
    _, _, seite = anfrage("GET", "/helfer/helfer/%d" % LENA)
    pruefe('id="zusammenfuehren"' in seite and "Lena Mueller" in seite
           and "Diese Person hat Nr. %d." % LENA in seite,
           "die Personenseite auch – mit Nummer zum Eintippen")

    print("Vergleichen")
    status, _, seite = anfrage("GET", "/helfer/zusammenfuehren?a=%d&b=%d" % (LENA, LENA2))
    csrf = re.search(r'name="csrf" value="([^"]+)"', seite).group(1)
    pruefe(status == 200 and "Lena Müller" in seite and "Lena Mueller" in seite
           and "+491511234567" in seite, "beide nebeneinander")
    pruefe(re.search(r'value="%d"\s+checked' % LENA2, seite),
           "vorgeschlagen ist, wer mehr mitbringt")
    status, ort, _ = anfrage("GET", "/helfer/zusammenfuehren?a=%d&b=%d" % (LENA, LENA))
    pruefe(status == 303 and "hinweis=zusammen-nr" in ort, "mit sich selbst geht es nicht")
    status, ort, _ = anfrage("GET", "/helfer/zusammenfuehren?a=%d&b=99999" % LENA)
    pruefe(status == 303 and ort.startswith("/helfer/helfer/%d" % LENA), "eine unbekannte Nummer auch nicht")

    print("Zusammenführen")
    status, ort, _ = anfrage("POST", "/helfer/zusammenfuehren",
                             {"csrf": csrf, "a": LENA, "b": LENA2, "behalten": LENA})
    pruefe(status == 303 and ort.startswith("/helfer/helfer/%d" % LENA)
           and "zusammengefuehrt" in ort, "Lena bleibt, Lena Mueller geht in ihr auf")
    pruefe(not sql("SELECT 1 FROM helfer WHERE id = ?", LENA2), "der zweite Eintrag ist weg")

    def zeilen(text, *parameter):
        return [tuple(z.values()) for z in sql(text, *parameter)]

    pruefe(zeilen("SELECT schicht_id, art FROM einteilung WHERE helfer_id = ? ORDER BY schicht_id",
                  LENA) == [(S1, "platz"), (S2, "reserve")],
           "Schichten: S1 einmal, S2 kam dazu")
    pruefe(zeilen("SELECT art FROM einteilung WHERE helfer_id = ?", DORA) == [("platz",)],
           "der doppelte Platz auf S1 ist frei geworden – Dora rückt aus der Reserve auf")
    pruefe(zeilen("SELECT schicht_id FROM warteliste WHERE helfer_id = ?", LENA) == [(S3,)],
           "die Warteliste wandert mit")
    t = sql("SELECT vorlieben, bemerkung FROM teilnahme WHERE helfer_id = ?", LENA)
    pruefe(len(t) == 1 and list(t[0][0]) == ["strecke", "menschen"]
           and t[0][1] == "mit Rad\nvegetarisch bitte",
           "eine Teilnahme, mit beiden Vorlieben und beiden Bemerkungen: " + str(t))
    pruefe(zeilen("SELECT beginn FROM verfuegbarkeit WHERE helfer_id = ? ORDER BY beginn", LENA)
           == [("2027-07-03 06:00",), ("2027-07-03 17:00",)],
           "Springer-Zeiten: die gleiche einmal, die andere dazu")
    pruefe(len(sql("SELECT 1 FROM einsatzgrenze WHERE helfer_id = ?", LENA)) == 1,
           "die Einsatzgrenze einmal")
    pruefe(sql("SELECT helfer_id FROM ausleihe")[0][0] == LENA
           and sql("SELECT vorgang_id FROM unterschrift")[0][0] == LENA
           and sql("SELECT helfer_id FROM absage")[0][0] == LENA
           and sql("SELECT helfer_id FROM mail_out")[0][0] == LENA,
           "Ausleihe, Shirt-Unterschrift, Absage und Mail hängen jetzt an Lena")
    pruefe(sql("SELECT angemeldet_von FROM helfer WHERE id = ?", KIND)[0][0] == LENA,
           "Kai hat jetzt Lena mitangemeldet")
    h = sql("SELECT * FROM helfer WHERE id = ?", LENA)[0]
    pruefe(h["telefon"] == "+491511234567" and h["tshirt"] == "M" and h["veggie"] == 1
           and h["tshirt_ausgegeben"] == "M" and h["name"] == "Lena Müller",
           "was Lena fehlte, kam dazu – ihr Name bleibt")
    pruefe(h["bemerkung"] == "kommt mit dem Rad\nisst vegetarisch", "beide Bemerkungen")
    verlauf = [z["was"] for z in sql("SELECT was FROM protokoll WHERE helfer_id = ? ORDER BY id", LENA)]
    pruefe(verlauf == ["Angaben geändert", "Zusammengeführt mit Lena Mueller (Nr. %d)" % LENA2],
           "der Verlauf wandert mit, und das Zusammenführen steht darin: " + str(verlauf))
    _, _, seite = anfrage("GET", "/helfer/helfer/%d?hinweis=zusammengefuehrt" % LENA)
    pruefe("Zusammengeführt. Was zur anderen Person gehörte" in seite, "die Seite sagt es")
    pruefe((LENA, LENA2) not in {(d["a_id"], d["b_id"]) for d in db.moegliche_dubletten()},
           "das Paar steht nicht mehr unter den Dubletten")

    print("Zwei verschiedene Menschen")
    status, ort, _ = anfrage("POST", "/helfer/zusammenfuehren/verschieden",
                             {"csrf": csrf, "a": JOERG2, "b": JOERG})
    pruefe(status == 303 and "verschieden" in ort, "vermerkt")
    pruefe((JOERG, JOERG2) not in {(d["a_id"], d["b_id"]) for d in db.moegliche_dubletten()},
           "Jörg und Joerg stehen nicht mehr unter den Dubletten")
    pruefe(sql("SELECT COUNT(*) FROM helfer WHERE id IN (?, ?)", JOERG, JOERG2)[0][0] == 2,
           "und beide gibt es weiter")
    status, _, _ = anfrage("POST", "/helfer/zusammenfuehren",
                           {"csrf": "falsch", "a": JOERG, "b": JOERG2, "behalten": JOERG})
    pruefe(status == 400 and sql("SELECT COUNT(*) FROM helfer WHERE id = ?", JOERG2)[0][0] == 1,
           "ohne gültigen CSRF-Token passiert nichts")
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
