"""Bestätigen, Wiedererkennen, Mein Helferplatz, Kalender (Lastenheft 2.4).

    python helfer/tests/test_helferplatz.py

Der Weg nach der Anmeldung: Bestätigung per Code und per Link (nur mit
Knopf, nie beim bloßen Aufruf), Mein Helferplatz mit Ansprechpartner und
Dazunehmen, wer wiederkommt oder sich vertippt (A-11, I-05), Link
anfordern, das Kalender-Abo und die Fristen für unbestätigte Anmeldungen.
Verschickt wird nichts – die Mails liegen in mail_out und werden dort
gelesen.
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
GEHEIM = "test-schluessel"
JETZT = "2027-06-01 10:00"

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


db_url = testdb.wegwerf("helfer_platz")
# Dieselbe Uhr und derselbe Schlüssel wie der Server: die Fristen laufen
# hier im Test, die Links rechnet er nach.
os.environ.update({"DATABASE_URL": db_url, "APP_SECRET_KEY": GEHEIM, "JETZT_FEST": JETZT,
                   "BASIS_URL": "https://helfer.example.de"})

from app import db, versand, zugang  # noqa: E402

db.init()
VA = db.VERANSTALTUNGEN.anlegen({"name": "Die absolute Abfahrt 2027", "kurz": "AA 2027",
                                 "beginn": "2027-07-01", "ende": "2027-07-04",
                                 "ort": "Ilmenau", "status": "offen"})
db.angebot_setzen(VA, {"goodies": 0, "shirt": 0, "schnitte": 0, "verpflegung": 0, "party": 0})
LEER = {"beschreibung": "", "treffpunkt": "", "mindestalter": None, "voraussetzungen": "",
        "intern": 0}
SHUTTLE = db.bereich_anlegen(VA, {**LEER, "name": "Shuttle", "treffpunkt": "Parkplatz Talstation"})
STRECKE = db.bereich_anlegen(VA, {**LEER, "name": "Streckenposten"})


def schicht(bereich, tag, von, bis, soll):
    return db.schicht_anlegen(VA, bereich, {
        "datum": tag, "beginn": f"{tag} {von}", "ende": f"{tag} {bis}", "minimum": 1,
        "soll": soll, "reserve": 0, "mindestalter": None, "ort": "", "hinweis": "",
        "intern": 0})


FRUEH = schicht(SHUTTLE, "2027-07-02", "07:00", "12:00", 3)
MITTAG = schicht(SHUTTLE, "2027-07-02", "13:00", "17:00", 1)
POSTEN_FR = schicht(STRECKE, "2027-07-02", "08:00", "13:00", 3)
POSTEN = schicht(STRECKE, "2027-07-03", "08:00", "13:00", 5)

# Kalle leitet den Shuttle – er steht in Mein Helferplatz als Ansprechpartner.
KONTEN = Konten(lambda: db_url)
KALLE = KONTEN.anlegen(email="kalle@example.org", name="Kalle Beispiel", kuerzel="KB",
                       rolle="bereichsleitung", telefon="0151 0000000")
db.leitung_setzen(SHUTTLE, [KALLE])

hafen = freier_hafen()
prozess = subprocess.Popen(
    [str(PYTHON), "-m", "app"], cwd=str(WURZEL),
    env={**os.environ, "BIND": f"127.0.0.1:{hafen}", "ADMIN_PASSWORD_HASH": HASH,
         "COOKIE_SECURE": "0", "ZEITPLAN_SERIEN": "", "PYTHONIOENCODING": "utf-8"},
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def zeilen(sql, *parameter):
    return tupel(testdb.abfrage(db_url, "helfer", sql, parameter))


def mails(typ, empfaenger):
    return [body for (body,) in zeilen(
        "SELECT body FROM mail_out WHERE typ = ? AND empfaenger = ? ORDER BY id", typ, empfaenger)]


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
                    unescape(antwort.read().decode("utf-8")), antwort.getheader("Content-Type", ""))
        verbindung.close()
        return ergebnis

    def melde_an(vorname, email, schichten, nachname="Berg", telefon="", weitere=(), **extra):
        daten = [("s", s) for s in schichten]
        daten += [("ich-vorname", vorname), ("ich-nachname", nachname), ("ich-email", email),
                  ("ich-telefon", telefon), ("ich-volljaehrig", "ja"),
                  ("weitere", len(weitere)), ("aktion", "anmelden")]
        for i, w in enumerate(weitere):
            daten += [(f"p{i}-vorname", w), (f"p{i}-nachname", nachname),
                      (f"p{i}-volljaehrig", "ja")]
        daten += list(extra.items())
        return anfrage("POST", "/aa-2027/angaben", daten)

    def pfad(link):
        return link.replace("https://helfer.example.de", "")

    print("Nach der Anmeldung: Bestätigen per Code (I-03)")
    status, danke, _, _ = melde_an("Anna", "anna@example.org", [FRUEH], weitere=["Fritz"])
    pruefe(status == 303, "Anna meldet sich mit Fritz an")
    ANNA = int(re.search(r"p=(\d+)", danke).group(1))
    FRITZ = zeilen("SELECT id FROM helfer WHERE angemeldet_von = ?", ANNA)[0][0]
    post = mails("bestaetigen", "anna@example.org")
    pruefe(len(post) == 1 and "https://helfer.example.de/bestaetigen/" in post[0]
           and re.search(r"Code ein: \d{6}", post[0]) and "Fritz" in post[0]
           and "Shuttle" in post[0], "eine Mail mit Link, Code und der Auswahl beider")
    CODE = re.search(r"Code ein: (\d{6})", post[0]).group(1)
    _, _, seite, _ = anfrage("GET", danke)
    pruefe("Fast geschafft" in seite and 'name="code"' in seite,
           "die Dankeseite bittet ums Bestätigen und nimmt den Code")
    admin = {}
    anfrage("POST", "/helfer/login", {"passwort": "test-passwort-123", "kuerzel": "KK",
                                      "weiter": "/helfer"}, admin)
    _, _, seite, _ = anfrage("GET", f"/helfer/schicht/{FRUEH}", glas=admin)
    pruefe(seite.count("unbestätigt") == 2, "im Backoffice: Anna und Fritz noch unbestätigt")
    falsch = "000000" if CODE != "000000" else "111111"
    status, _, seite, _ = anfrage("POST", danke, {"code": falsch})
    pruefe(status == 400 and "stimmt nicht" in seite
           and zeilen("SELECT code_versuche, email_bestaetigt_am FROM helfer WHERE id = ?", ANNA)
           == [(1, None)], "ein falscher Code zählt und bestätigt nichts")
    status, ort, _, _ = anfrage("POST", danke, {"code": CODE[:3] + " " + CODE[3:]})
    pruefe(status == 303 and ort.startswith("/platz/") and "hinweis=bestaetigt" in ort,
           "der richtige – auch mit Leerzeichen – führt zu Mein Helferplatz")
    PLATZ = ort.split("?")[0]
    pruefe(zeilen("SELECT email_bestaetigt_am IS NOT NULL FROM helfer WHERE id = ?", ANNA)
           == [(True,)], "Anna ist bestätigt")
    post = mails("bestaetigt", "anna@example.org")
    pruefe(len(post) == 1 and "https://helfer.example.de" + PLATZ in post[0]
           and "/kalender/" in post[0] and "15 Minuten" in post[0],
           "danach die Mail mit persönlichem Link und Kalender-Abo (A-10)")
    _, _, seite, _ = anfrage("GET", danke)
    pruefe("Du bist dabei" in seite and 'name="code"' not in seite, "die Dankeseite weiß es auch")
    status, ort, _, _ = anfrage("POST", danke, {"code": CODE})
    pruefe(status == 303 and ort == PLATZ, "ein zweites Mal Code führt einfach hin")

    print("Bestätigen per Link – erst mit dem Knopf (7.4)")
    status, danke_bert, _, _ = melde_an("Bert", "bert@example.org", [POSTEN], nachname="Öhl",
                                        telefon="0170 1234567")
    BERT = int(re.search(r"p=(\d+)", danke_bert).group(1))
    link = re.search(r"(https://\S+/bestaetigen/\S+)", mails("bestaetigen", "bert@example.org")[0]).group(1)
    status, _, seite, _ = anfrage("GET", pfad(link))
    pruefe(status == 200 and "Ja, das bin ich" in seite
           and zeilen("SELECT email_bestaetigt_am FROM helfer WHERE id = ?", BERT) == [(None,)],
           "der Link zeigt nur den Knopf – ein Mailscanner bestätigt nichts")
    status, ort, _, _ = anfrage("POST", pfad(link))
    pruefe(status == 303 and ort.startswith("/platz/")
           and zeilen("SELECT email_bestaetigt_am IS NOT NULL FROM helfer WHERE id = ?", BERT)
           == [(True,)], "der Knopf bestätigt")
    status, ort, _, _ = anfrage("GET", pfad(link))
    pruefe(status == 303 and ort.startswith("/platz/"), "danach führt der Link zu Mein Helferplatz")
    status, _, _, _ = anfrage("GET", pfad(link)[:-1] + ("0" if link[-1] != "0" else "1"))
    pruefe(status == 404, "ein verfälschter Link geht ins Leere")
    for code in ("0", "1", "2", "3", "4"):
        anfrage("POST", danke_bert, {"code": "99999" + code})
    status, _, seite, _ = anfrage("GET", danke_bert)
    pruefe("Du bist dabei" in seite, "wer bestätigt ist, dem schadet ein falscher Code nicht")

    print("Mein Helferplatz (A-09)")
    status, _, seite, _ = anfrage("GET", PLATZ)
    pruefe(status == 200 and "Hallo Anna" in seite and "Parkplatz Talstation" in seite
           and "Kalle Beispiel" in seite and "0151 0000000" in seite,
           "Schichten mit Treffpunkt und Ansprechpartner samt Nummer")
    pruefe("Fritz" in seite and "Schichten dazunehmen" in seite and "webcal://" in seite,
           "Fritz steht mit drauf; dazunehmen und Kalender abonnieren")
    for falsch in (PLATZ[:-1] + ("0" if PLATZ[-1] != "0" else "1"),
                   "/platz/" + zugang.token(zugang.KALENDER, db.helfer_laden(ANNA)),
                   "/platz/" + zugang.token(zugang.PLATZ, db.helfer_laden(FRITZ)).replace(
                       str(FRITZ) + ".", str(ANNA) + "."), "/platz/quatsch"):
        status, _, _, _ = anfrage("GET", falsch)
        pruefe(status == 404, "kein Zugang mit " + falsch[:24] + "…")

    print("Dazunehmen")
    _, _, seite, _ = anfrage("GET", PLATZ + "/aa-2027/schichten")
    pruefe("Eingetragen: du, Fritz" in seite and f'action="{PLATZ}/aa-2027/angaben"' in seite,
           "die Liste zeigt, was schon gebucht ist, und bleibt im Helferplatz")
    pruefe("überschneidet sich mit deiner Schicht Shuttle" in seite,
           "und was sich mit der eigenen Schicht beißt")
    _, _, seite, _ = anfrage("GET", PLATZ + f"/aa-2027/angaben?s={MITTAG}")
    pruefe(re.search(r'name="wer" value="%d"\s+checked' % ANNA, seite)
           and re.search(r'name="wer" value="%d"\s+>' % FRITZ, seite)
           and 'name="ich-email"' not in seite, "gefragt wird nur, wer kommt – Anna vorgewählt")

    def dazu(schichten, wer=(), neue=(), **extra):
        daten = [("s", s) for s in schichten] + [("wer", w) for w in wer]
        daten += [("aktion", "eintragen"), ("weitere", len(neue))]
        for i, n in enumerate(neue):
            daten += [(f"p{i}-vorname", n), (f"p{i}-nachname", "Berg"), (f"p{i}-volljaehrig", "ja")]
        daten += list(extra.items())
        return anfrage("POST", PLATZ + "/aa-2027/angaben", daten)

    status, _, seite, _ = dazu([MITTAG], wer=[ANNA, FRITZ])
    pruefe(status == 409 and "nicht für alle 2 Platz" in seite, "für zwei ist im Mittag kein Platz")
    status, ort, _, _ = dazu([MITTAG], wer=[ANNA])
    pruefe(status == 303 and "hinweis=dazu" in ort and zeilen(
        "SELECT COUNT(*) FROM einteilung WHERE schicht_id = ? AND helfer_id = ?", MITTAG, ANNA)
        == [(1,)], "für Anna allein schon")
    pruefe(len(mails("dazu", "anna@example.org")) == 1
           and ("selbst", "Dazugenommen: Shuttle Fr 02.07. 13:00–17:00") in zeilen(
               "SELECT wer, was FROM protokoll WHERE helfer_id = ?", ANNA),
           "mit Mail und im Protokoll (S-08)")
    status, _, seite, _ = dazu([FRUEH], wer=[ANNA])
    pruefe(status == 409 and "schon eingetragen" in seite, "dieselbe Schicht nicht zweimal")
    status, _, seite, _ = dazu([POSTEN_FR], wer=[ANNA])
    pruefe(status == 409 and "überschneidet sich" in seite, "nichts, was sich überschneidet (K-01)")
    status, _, seite, _ = dazu([POSTEN], wer=[BERT])
    pruefe(status == 409 and "gehört nicht" in seite, "nur für sich und die eigenen Leute")
    status, _, seite, _ = dazu([POSTEN])
    pruefe(status == 400 and "wer kommt" in seite, "ohne jemanden geht es nicht")
    status, ort, _, _ = dazu([POSTEN], wer=[FRITZ], neue=["Mia"])
    pruefe(status == 303 and zeilen("SELECT name FROM helfer WHERE angemeldet_von = ? ORDER BY id",
                                    ANNA) == [("Fritz Berg",), ("Mia Berg",)],
           "Fritz und eine neue, Mia, die Anna mitbringt (A-08)")

    print("Wer wiederkommt (A-11) und wer sich vertippt (I-05)")
    status, _, seite, _ = melde_an("Anna", "Anna@Example.org", [POSTEN])
    pruefe(status == 200 and "Dich kennen wir schon" in seite and "Shuttle" not in seite
           and "Fritz" not in seite, "bekannt: kein zweites Mal, und die Seite verrät nichts")
    post = mails("link", "anna@example.org")
    pruefe(len(post) == 1 and f"{PLATZ}/aa-2027/angaben?s={POSTEN}" in post[0],
           "der Link geht an Anna, mit der Auswahl")
    status, _, seite, _ = melde_an("Änna", "anna@example.org", [POSTEN])
    pruefe(status == 200 and "Bist du schon bei uns?" in seite
           and zeilen("SELECT COUNT(*) FROM helfer WHERE lower(email) = 'anna@example.org'") == [(1,)],
           "„Änna“ mit Annas Adresse: erst die Frage, nichts angelegt")
    status, _, seite, _ = melde_an("Änna", "anna@example.org", [POSTEN], aktion="bin-ich")
    pruefe(status == 200 and len(mails("link", "anna@example.org")) == 2,
           "„Ja, das bin ich“: der Link geht an die bekannte Adresse")
    status, _, _, _ = melde_an("Bert", "bert.neu@example.org", [POSTEN_FR], nachname="Oehl",
                               telefon="+49 170 1234567")
    pruefe(status == 200 and len(mails("link", "bert@example.org")) == 0
           and zeilen("SELECT COUNT(*) FROM helfer WHERE email = 'bert.neu@example.org'") == [(0,)],
           "„Bert Oehl“ mit Berts Nummer und anderer Adresse wird auch gefragt")
    status, ort, _, _ = melde_an("Bert", "bert.neu@example.org", [POSTEN_FR], nachname="Oehl",
                                 telefon="0170 1234567", aktion="neu-anlegen")
    pruefe(status == 303, "„Nein, ich bin jemand anderes“ legt neu an")
    _, _, seite, _ = anfrage("GET", "/helfer", glas=admin)
    pruefe("Vielleicht dieselbe Person" in seite and "Bert Oehl" in seite and "Bert Öhl" in seite,
           "die Orga sieht das Paar in der Übersicht")

    print("Link anfordern")
    status, _, seite, _ = anfrage("POST", "/aa-2027/link", {"email": " ANNA@example.org "})
    pruefe(status == 200 and "unterwegs" in seite and len(mails("link", "anna@example.org")) == 3,
           "an eine bekannte Adresse geht der Link")
    status, _, seite2, _ = anfrage("POST", "/aa-2027/link", {"email": "fremd@example.org"})
    pruefe(status == 200 and seite2 == seite and not mails("link", "fremd@example.org"),
           "eine fremde Adresse bekommt dieselbe Seite – und keine Mail")
    status, _, _, _ = anfrage("POST", "/aa-2027/link", {"email": "kaputt"})
    pruefe(status == 400, "eine halbe Adresse wird gemeldet")
    _, _, seite, _ = anfrage("GET", "/aa-2027")
    pruefe('action="/aa-2027/link"' in seite, "die Startseite bietet es an")

    print("Kalender-Abo (A-10)")
    kalender = "/kalender/" + zugang.token(zugang.KALENDER, db.helfer_laden(ANNA)) + ".ics"
    status, _, ics, art = anfrage("GET", kalender)
    pruefe(status == 200 and art.startswith("text/calendar") and ics.startswith("BEGIN:VCALENDAR"),
           "ein Kalender")
    pruefe("DTSTART:20270702T050000Z" in ics and "SUMMARY:Shuttle – AA 2027" in ics
           and "LOCATION:Parkplatz Talstation" in ics, "Fr 7 Uhr in Ilmenau ist 5 Uhr UTC")
    pruefe("(Fritz)" in ics and "(Mia)" in ics, "die Mitgebrachten mit Namen")
    pruefe("/platz/" not in ics, "ohne den Link zu Mein Helferplatz – der Kalender darf nur lesen")
    status, _, _, _ = anfrage("GET", "/kalender/" + PLATZ.split("/")[-1] + ".ics")
    pruefe(status == 404, "der Link zu Mein Helferplatz ist kein Kalenderlink")

    print("Fristen (I-03)")
    status, danke_cleo, _, _ = melde_an("Cleo", "cleo@example.org", [POSTEN], weitere=["Lena"])
    CLEO = int(re.search(r"p=(\d+)", danke_cleo).group(1))
    LENA = zeilen("SELECT id FROM helfer WHERE angemeldet_von = ?", CLEO)[0][0]
    # Die Uhr steht auf dem 01.06., 10 Uhr; gerückt wird die Anmeldung.
    testdb.abfrage(db_url, "helfer", "UPDATE teilnahme SET angemeldet_am = '2027-06-01 08:00:00'"
                   " WHERE helfer_id IN (%d, %d)" % (CLEO, LENA))
    testdb.abfrage(db_url, "helfer", "UPDATE teilnahme SET angemeldet_am = '2027-05-20 08:00:00'"
                   " WHERE helfer_id = %d" % ANNA)
    pruefe(versand.fristen() == (0, 0), "vor 24 Stunden passiert nichts")
    testdb.abfrage(db_url, "helfer", "UPDATE teilnahme SET angemeldet_am = '2027-05-31 08:00:00'"
                   " WHERE helfer_id IN (%d, %d)" % (CLEO, LENA))
    pruefe(versand.fristen() == (1, 0) and len(mails("erinnerung", "cleo@example.org")) == 1,
           "nach 24 Stunden eine Erinnerung – nur an Cleo, Anna ist bestätigt")
    erinnerung = mails("erinnerung", "cleo@example.org")[0]
    pruefe("/bestaetigen/" in erinnerung and re.search(r"Code: \d{6}", erinnerung),
           "mit Link und Code")
    pruefe(versand.fristen() == (0, 0), "und nur einmal")
    testdb.abfrage(db_url, "helfer", "UPDATE teilnahme SET angemeldet_am = '2027-05-29 08:00:00'"
                   " WHERE helfer_id IN (%d, %d)" % (CLEO, LENA))
    pruefe(versand.fristen() == (0, 1), "nach 72 Stunden verfällt die Anmeldung")
    pruefe(zeilen("SELECT COUNT(*) FROM helfer WHERE id IN (?, ?)", CLEO, LENA) == [(0,)]
           and zeilen("SELECT COUNT(*) FROM einteilung WHERE helfer_id IN (?, ?)", CLEO, LENA)
           == [(0,)], "die Plätze sind frei, Cleo und Lena gelöscht")
    pruefe(zeilen("SELECT helfer_id FROM mail_out WHERE typ = 'verfallen'") == [(None,)]
           and "https://helfer.example.de/aa-2027" in mails("verfallen", "cleo@example.org")[0],
           "Cleo bekommt Bescheid, mit dem Weg zur neuen Anmeldung")
    pruefe(zeilen("SELECT COUNT(*) FROM einteilung WHERE helfer_id = ?", ANNA) == [(2,)],
           "Annas Schichten bleiben")
    testdb.abfrage(db_url, "helfer", "UPDATE mail_out SET gesendet_am = '2027-04-01 10:00:00'"
                   " WHERE typ = 'bestaetigen'")
    vorher = zeilen("SELECT COUNT(*) FROM mail_out")[0][0]
    versand.fristen()
    # Drei: Cleos ungesendete Mails sind schon mit ihr gegangen.
    pruefe(zeilen("SELECT COUNT(*) FROM mail_out")[0][0] == vorher - 3
           and zeilen("SELECT COUNT(*) FROM mail_out WHERE typ = 'bestaetigen'") == [(0,)],
           "verschickte Mails gehen nach einem Monat weg")
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
