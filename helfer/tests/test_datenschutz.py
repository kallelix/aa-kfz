"""Datenschutz, Einwilligungen, Eltern und das Löschwerkzeug (Lastenheft 2.9).

    python helfer/tests/test_datenschutz.py

Der Hinweis an der Stelle der Erhebung und die ausführliche Seite (D-01,
D-02), die freiwillige Einwilligung in den Helferstamm und ihr Widerruf
(D-03, D-05), unter 18 das Einverständnis der Eltern – per Mail, mit Frist,
oder gleich mit, wenn sie selbst anmelden (D-06) –, die Richtschnur für
Jugendliche (D-07) und deploy/daten-loeschen.py, das jetzt nur Vergangenes
anfasst und den Helferstamm behält.
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


def tupel(zeilen):
    return [tuple(z.values()) for z in zeilen]


db_url = testdb.wegwerf("helfer_datenschutz")
os.environ.update({"DATABASE_URL": db_url, "APP_SECRET_KEY": "test-schluessel",
                   "JETZT_FEST": "2027-06-01 10:00", "BASIS_URL": "https://helfer.example.de",
                   "VERANTWORTLICH": "Musterverein e. V., Musterstraße 1, 12345 Musterstadt"})

from app import db, versand, zugang  # noqa: E402

db.init()
VA = db.VERANSTALTUNGEN.anlegen({"name": "Die absolute Abfahrt 2027", "kurz": "AA 2027",
                                 "beginn": "2027-07-01", "ende": "2027-07-04",
                                 "ort": "Ilmenau", "status": "offen"})
LEER = {"beschreibung": "", "treffpunkt": "", "mindestalter": None, "voraussetzungen": "",
        "intern": 0}
db.angebot_setzen(VA, {"goodies": 0, "shirt": 0, "schnitte": 0, "verpflegung": 0, "party": 0})
STRECKE = db.bereich_anlegen(VA, {**LEER, "name": "Streckenposten"})


def schicht(vid, bereich, tag, von, bis, soll=5):
    return db.schicht_anlegen(vid, bereich, {
        "datum": tag, "beginn": f"{tag} {von}", "ende": f"{tag} {bis}", "minimum": 1,
        "soll": soll, "reserve": 0, "mindestalter": None, "ort": "", "hinweis": "",
        "intern": 0})


POSTEN = schicht(VA, STRECKE, "2027-07-02", "08:00", "13:00")
LANG = schicht(VA, STRECKE, "2027-07-03", "06:00", "17:00")

hafen = freier_hafen()
prozess = subprocess.Popen(
    [str(PYTHON), "-m", "app"], cwd=str(WURZEL),
    env={**os.environ, "BIND": f"127.0.0.1:{hafen}", "ADMIN_PASSWORD_HASH": HASH,
         "COOKIE_SECURE": "0", "ZEITPLAN_SERIEN": "", "PYTHONIOENCODING": "utf-8"},
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def zeilen(sql, *parameter):
    return tupel(testdb.abfrage(db_url, "helfer", sql, parameter))


def mails(typ, empfaenger):
    return [b for (b,) in zeilen("SELECT body FROM mail_out WHERE typ = ? AND empfaenger = ?"
                                 " ORDER BY id", typ, empfaenger)]


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

    def melde_an(vorname, schichten, weitere=(), jung="", eltern=("", ""), **extra):
        daten = [("s", s) for s in schichten]
        daten += [("ich-vorname", vorname), ("ich-nachname", "Berg"),
                  ("ich-email", vorname.lower() + "@example.org"),
                  ("ich-volljaehrig", "nein" if jung else "ja"), ("ich-geburtsdatum", jung),
                  ("ich-eltern_name", eltern[0]), ("ich-eltern_email", eltern[1]),
                  ("weitere", len(weitere)), ("aktion", "anmelden")]
        for i, (name, geboren, e_name, e_mail) in enumerate(weitere):
            daten += [(f"p{i}-vorname", name), (f"p{i}-nachname", "Berg"),
                      (f"p{i}-volljaehrig", "nein" if geboren else "ja"),
                      (f"p{i}-geburtsdatum", geboren), (f"p{i}-eltern_name", e_name),
                      (f"p{i}-eltern_email", e_mail)]
        daten += list(extra.items())
        status, ort, seite = anfrage("POST", "/aa-2027/angaben", daten)
        nummer = int(re.search(r"p=(\d+)", ort).group(1)) if status == 303 else None
        return status, ort, seite, nummer

    print("Datenschutzhinweis (D-01, D-02)")
    status, _, seite = anfrage("GET", "/datenschutz")
    pruefe(status == 200 and "Musterverein e. V." in seite and "Art. 6 Abs. 1 lit. b" in seite
           and "lit. f" in seite and "lit. a" in seite, "die Seite mit Verantwortlichem und Rechtsgrundlagen")
    _, _, seite = anfrage("GET", f"/aa-2027/angaben?s={POSTEN}")
    pruefe('href="/datenschutz"' in seite and 'name="stamm" value="1"\n' in seite
           and 'name="stamm" value="1"\n             checked' not in seite,
           "im Formular: kurz mit Link, und das Häkchen für den Helferstamm ist nicht gesetzt (D-03)")
    _, _, seite = anfrage("GET", "/aa-2027")
    pruefe('href="/datenschutz"' in seite, "der Link steht auf jeder Seite")

    print("Einwilligung in den Helferstamm (D-03, D-05)")
    status, danke, _, ANNA = melde_an(
        "Anna", [POSTEN], weitere=[("Ben", "2014-05-01", "Anna Berg", "anna@example.org")], stamm="1")
    BEN = zeilen("SELECT id FROM helfer WHERE angemeldet_von = ?", ANNA)[0][0]
    pruefe(status == 303 and zeilen("SELECT stamm_einwilligung_am IS NOT NULL FROM helfer WHERE id = ?",
                                    ANNA) == [(True,)], "Anna willigt ein")
    pruefe(not mails("eltern", "anna@example.org")
           and zeilen("SELECT eltern_bestaetigt_am FROM helfer WHERE id = ?", BEN) == [(None,)],
           "Ben (13): Anna ist selbst erziehungsberechtigt – keine eigene Elternmail")
    db.bestaetigen(ANNA)
    pruefe(zeilen("SELECT eltern_bestaetigt_am IS NOT NULL FROM helfer WHERE id = ?", BEN) == [(True,)],
           "mit Annas Bestätigung gilt auch das Einverständnis für Ben")
    platz = "/platz/" + zugang.token(zugang.PLATZ, db.helfer_laden(ANNA))
    _, _, seite = anfrage("GET", platz + "/angaben")
    pruefe(re.search(r'name="stamm" value="1"\s+checked', seite), "in Mein Helferplatz angehakt")
    anfrage("POST", platz + "/angaben", {"ich-telefon": ""})
    pruefe(zeilen("SELECT stamm_einwilligung_am FROM helfer WHERE id = ?", ANNA) == [(None,)]
           and ("selbst", "Einwilligung Helferstamm widerrufen") in zeilen(
               "SELECT wer, was FROM protokoll WHERE helfer_id = ?", ANNA),
           "ohne Häkchen gespeichert: widerrufen, mit Protokoll – so einfach wie hinein")

    print("Unter 18: Einverständnis der Eltern (D-06)")
    status, _, seite, _ = melde_an("Mia", [POSTEN], jung="2011-03-01")
    pruefe(status == 400 and "erziehungsberechtigte Person" in seite, "ohne Eltern geht es nicht")
    status, danke, _, MIA = melde_an("Mia", [LANG], jung="2011-03-01",
                                     eltern=("Eva Berg", "eva@example.org"))
    pruefe(status == 303, "mit Eltern geht die Anmeldung durch")
    post = mails("eltern", "eva@example.org")
    pruefe(len(post) == 1 and "Mia Berg möchte bei Die absolute Abfahrt 2027" in post[0]
           and "/eltern/" in post[0] and "Streckenposten" in post[0],
           "Eva bekommt eine Mail mit Mias Schicht und einem Link")
    _, _, seite = anfrage("GET", danke)
    pruefe("Einverständnis der Eltern" in seite, "die Dankeseite sagt, dass es noch fehlt")
    link = re.search(r"(https://\S+/eltern/\S+)", post[0]).group(1).replace("https://helfer.example.de", "")
    status, _, seite = anfrage("GET", link)
    pruefe(status == 200 and "Ich bin einverstanden" in seite
           and zeilen("SELECT eltern_bestaetigt_am FROM helfer WHERE id = ?", MIA) == [(None,)],
           "der Link zeigt nur den Knopf")
    status, _, seite = anfrage("POST", link)
    pruefe(status == 200 and "ist dabei" in seite and zeilen(
        "SELECT eltern_bestaetigt_am IS NOT NULL FROM helfer WHERE id = ?", MIA) == [(True,)],
        "der Knopf gibt das Einverständnis")

    status, _, _, CARL = melde_an("Carl", [POSTEN],
                                  weitere=[("Cora", "2013-01-01", "Dana Berg", "dana@example.org")])
    CORA = zeilen("SELECT id FROM helfer WHERE angemeldet_von = ?", CARL)[0][0]
    pruefe(len(mails("eltern", "dana@example.org")) == 1, "Cora (14): Dana bekommt die Mail")
    db.bestaetigen(CARL)
    platz_carl = "/platz/" + zugang.token(zugang.PLATZ, db.helfer_laden(CARL))
    _, _, seite = anfrage("GET", platz_carl)
    pruefe("Einverständnis der Eltern fehlt" in seite, "Carl sieht, dass es für Cora noch fehlt")
    status, ort, _ = anfrage("POST", platz_carl + f"/eltern/{CORA}")
    pruefe("hinweis=eltern" in ort and len(mails("eltern", "dana@example.org")) == 2,
           "und kann die Mail noch einmal schicken")
    admin = {}
    anfrage("POST", "/helfer/login", {"passwort": "test-passwort-123", "kuerzel": "KK",
                                      "weiter": "/helfer"}, admin)
    _, _, seite = anfrage("GET", f"/helfer/schicht/{POSTEN}", glas=admin)
    pruefe("Eltern fehlen" in seite, "im Backoffice an der Schicht vermerkt")
    testdb.abfrage(db_url, "helfer", "UPDATE teilnahme SET angemeldet_am = '2027-05-31 08:00:00'"
                   " WHERE helfer_id = %d" % CORA)
    versand.fristen()
    pruefe(len(mails("eltern", "dana@example.org")) == 3
           and zeilen("SELECT eltern_erinnert_am IS NOT NULL FROM helfer WHERE id = ?", CORA) == [(True,)],
           "nach 24 Stunden eine Erinnerung an Dana")
    testdb.abfrage(db_url, "helfer", "UPDATE teilnahme SET angemeldet_am = '2027-05-29 08:00:00'"
                   " WHERE helfer_id = %d" % CORA)
    versand.fristen()
    pruefe(zeilen("SELECT COUNT(*) FROM helfer WHERE id = ?", CORA) == [(0,)]
           and zeilen("SELECT COUNT(*) FROM einteilung WHERE helfer_id = ?", CARL) == [(1,)],
           "nach 72 Stunden ohne Einverständnis: Coras Platz ist frei, Carls bleibt")
    pruefe(len(mails("eltern_verfallen", "carl@example.org")) == 1, "Carl bekommt Bescheid")

    print("Richtschnur für Jugendliche (D-07)")
    _, _, seite = anfrage("GET", "/helfer", glas=admin)
    pruefe("Jugendliche: mehr als 8 Stunden" in seite and "Mia Berg" in seite
           and "11.0 Stunden" in seite and "vor 6 oder nach 20 Uhr" not in seite,
           "Mia (16) hat 11 Stunden an einem Tag – ein Hinweis, keine Sperre")

    print("Löschwerkzeug")
    ALT = db.VERANSTALTUNGEN.anlegen({"name": "Die absolute Abfahrt 2026", "kurz": "AA 2026",
                                      "beginn": "2026-08-28", "ende": "2026-08-30",
                                      "ort": "Ilmenau", "status": "archiviert"})
    URALT = db.VERANSTALTUNGEN.anlegen({"name": "Die absolute Abfahrt 2022", "kurz": "AA 2022",
                                        "beginn": "2022-08-26", "ende": "2022-08-28",
                                        "ort": "Ilmenau", "status": "archiviert"})
    alt_bereich = db.bereich_anlegen(ALT, {**LEER, "name": "Streckenposten"})
    ur_bereich = db.bereich_anlegen(URALT, {**LEER, "name": "Streckenposten"})
    ALT_POSTEN = schicht(ALT, alt_bereich, "2026-08-29", "08:00", "13:00")
    UR_POSTEN = schicht(URALT, ur_bereich, "2022-08-27", "08:00", "13:00")

    def person(name, einwilligung):
        nummer, _ = db.helfer_von_hand({"name": name, "email": name.split()[0].lower() + "@example.org"})
        if einwilligung:
            testdb.abfrage(db_url, "helfer", "UPDATE helfer SET stamm_einwilligung_am ="
                           " '2026-08-01 10:00:00' WHERE id = %d" % nummer)
        return nummer

    OLAF = person("Olaf Alt", False)
    PETRA = person("Petra Stamm", True)
    QUINN = person("Quinn Lange", True)
    db.einteilen(ALT_POSTEN, OLAF)
    db.einteilen(ALT_POSTEN, PETRA)
    db.einteilen(UR_POSTEN, QUINN)
    testdb.abfrage(db_url, "helfer", "UPDATE helfer SET stamm_einwilligung_am = '2022-08-01 10:00:00'"
                   " WHERE id = %d" % QUINN)
    for vid, wer in ((ALT, PETRA), (VA, ANNA)):
        db.material_standard(vid)
        funk = next(m["id"] for m in db.materialien(vid) if m["name"] == "Funkgerät")
        db.ausgeben(vid, wer, "", [{"material_id": funk, "menge": 1}])
    skript = [str(PYTHON), str(WURZEL.parent / "deploy" / "daten-loeschen.py"), "--art", "helfer",
              "--url", db_url]
    probe = subprocess.run(skript, capture_output=True, text=True, encoding="utf-8",
                           env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    pruefe(probe.returncode == 0 and "Nichts geschrieben" in probe.stdout
           and zeilen("SELECT COUNT(*) FROM helfer WHERE id = ?", OLAF) == [(1,)],
           "ohne --wirklich nur die Aufstellung")
    lauf = subprocess.run(skript + ["--wirklich", "--ohne-sicherung"], capture_output=True,
                          text=True, encoding="utf-8", env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    pruefe(lauf.returncode == 0, "der Lauf geht durch" + ("" if lauf.returncode == 0 else ": " + lauf.stderr[-300:]))
    da = {nummer for (nummer,) in zeilen("SELECT id FROM helfer")}
    pruefe(OLAF not in da, "Olaf ohne Einwilligung, nur 2026 dabei: gelöscht")
    pruefe(PETRA in da and zeilen("SELECT COUNT(*) FROM einteilung WHERE helfer_id = ?", PETRA) == [(1,)],
           "Petra mit Einwilligung bleibt – samt ihrer Teilnahme 2026 (D-04 rechnet von dort)")
    pruefe(QUINN not in da, "Quinn: Einwilligung, aber zuletzt 2022 dabei – nach drei Jahren gelöscht")
    pruefe(ANNA in da and MIA in da and BEN in da,
           "wer 2027 dabei ist, bleibt – auch ohne Einwilligung")
    pruefe(zeilen("SELECT veranstaltung_id FROM ausgabe") == [(VA,)],
           "Ausgaben nur der vergangenen Veranstaltung sind weg")
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
