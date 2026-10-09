"""Selbstbedienung, Warteliste und Absagen (Lastenheft 2.5).

    python helfer/tests/test_selbstbedienung.py

Alles aus Mein Helferplatz: absagen (S-01), tauschen (S-02), ganz abmelden
(S-03), Angaben und Adresse ändern (S-04), Daten löschen – auch mit noch
ausgeliehenem Funkgerät (S-05), für Mitangemeldete und bis zum Selbständig-
machen (S-06). Dazu die Warteliste mit Nachrücken und Fristen (R-04), die
Meldung an die Bereichsleitung und die kurzfristigen Absagen in der Übersicht
(S-07) und „Änderungen seit gestern“ (S-08). Verschickt wird nichts – die
Mails liegen in mail_out.
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


db_url = testdb.wegwerf("helfer_selbst")
os.environ.update({"DATABASE_URL": db_url, "APP_SECRET_KEY": GEHEIM,
                   "JETZT_FEST": "2027-06-01 10:00", "BASIS_URL": "https://helfer.example.de",
                   "KONTAKT_MAIL": "orga@example.org"})

from app import db, versand, zugang  # noqa: E402

db.init()
VA = db.VERANSTALTUNGEN.anlegen({"name": "Die absolute Abfahrt 2027", "kurz": "AA 2027",
                                 "beginn": "2027-07-01", "ende": "2027-07-04",
                                 "ort": "Ilmenau", "status": "offen"})
db.angebot_setzen(VA, {"goodies": 1, "shirt": 1, "schnitte": 1, "verpflegung": 1, "party": 0})
LEER = {"beschreibung": "", "treffpunkt": "", "mindestalter": None, "voraussetzungen": "",
        "intern": 0}
SHUTTLE = db.bereich_anlegen(VA, {**LEER, "name": "Shuttle",
                                  "voraussetzungen": "Führerschein Klasse B"})
STRECKE = db.bereich_anlegen(VA, {**LEER, "name": "Streckenposten"})


def schicht(bereich, tag, von, bis, soll, reserve=0, minimum=1):
    return db.schicht_anlegen(VA, bereich, {
        "datum": tag, "beginn": f"{tag} {von}", "ende": f"{tag} {bis}", "minimum": minimum,
        "soll": soll, "reserve": reserve, "mindestalter": None, "ort": "", "hinweis": "",
        "intern": 0})


FRUEH = schicht(SHUTTLE, "2027-07-02", "07:00", "12:00", 1, reserve=1)
MITTAG = schicht(SHUTTLE, "2027-07-02", "13:00", "17:00", 2, minimum=2)
POSTEN = schicht(STRECKE, "2027-07-03", "08:00", "13:00", 3)
POSTEN_SO = schicht(STRECKE, "2027-07-04", "08:00", "13:00", 3)
# Aufbau am Tag nach „jetzt“ – eine Absage dafür ist kurzfristig.
AUFBAU = schicht(STRECKE, "2027-06-02", "08:00", "12:00", 2, minimum=2)

# Kalle leitet den Shuttle; der Strecke steht niemand vor – dann geht die
# Meldung an die Orga (KONTAKT_MAIL).
KONTEN = Konten(lambda: db_url)
KONTEN.anlegen(email="ada@example.org", name="Ada Admin", kuerzel="AD", rolle="admin",
               passwort="ein-langes-passwort")
KALLE = KONTEN.anlegen(email="kalle@example.org", name="Kalle Beispiel", kuerzel="KB",
                       rolle="bereichsleitung", passwort="kalles-langes-passwort")
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
    return [b for (b,) in zeilen("SELECT body FROM mail_out WHERE typ = ? AND empfaenger = ?"
                                 " ORDER BY id", typ, empfaenger)]


def einteilung(schicht_id, helfer_id):
    return zeilen("SELECT id, art, bestaetigen_bis FROM einteilung WHERE schicht_id = ?"
                  " AND helfer_id = ?", schicht_id, helfer_id)


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

    def melde_an(vorname, schichten=(), warte=(), weitere=(), springer=()):
        email = vorname.lower() + "@example.org"
        daten = [("s", s) for s in schichten] + [("w", w) for w in warte]
        daten += [("z", z) for z in springer]
        daten += [("ich-vorname", vorname), ("ich-nachname", "Berg"), ("ich-email", email),
                  ("ich-volljaehrig", "ja"), ("ich-tshirt", "M"), ("ich-schnitt", "damen"),
                  ("ich-verpflegung", "vegetarisch"), ("weitere", len(weitere)),
                  ("aktion", "anmelden"), ("voraussetzung", "Führerschein Klasse B")]
        for i, w in enumerate(weitere):
            daten += [(f"p{i}-vorname", w), (f"p{i}-nachname", "Berg"),
                      (f"p{i}-volljaehrig", "ja"), (f"p{i}-tshirt", "S"),
                      (f"p{i}-schnitt", "herren"), (f"p{i}-verpflegung", "fleisch")]
        status, ort, seite = anfrage("POST", "/aa-2027/angaben", daten)
        nummer = int(re.search(r"p=(\d+)", ort).group(1)) if status == 303 else None
        if nummer:
            db.bestaetigen(nummer)
        return status, nummer, seite

    def platz(helfer_id):
        return "/platz/" + zugang.token(zugang.PLATZ, db.helfer_laden(helfer_id))

    print("Warteliste (R-04)")
    _, ANNA, _ = melde_an("Anna", [MITTAG], weitere=["Fritz"])
    FRITZ = zeilen("SELECT id FROM helfer WHERE angemeldet_von = ?", ANNA)[0][0]
    _, BERT, _ = melde_an("Bert", [FRUEH])
    _, CLEO, _ = melde_an("Cleo", [FRUEH])
    pruefe(einteilung(FRUEH, BERT)[0][1] == "platz" and einteilung(FRUEH, CLEO)[0][1] == "reserve",
           "Bert hat den Platz, Cleo die Reserve")
    _, _, seite = anfrage("GET", "/aa-2027/schichten")
    pruefe(f'name="w" value="{FRUEH}"' in seite and f'name="s" value="{FRUEH}"' not in seite,
           "eine volle Schicht bietet die Warteliste an")
    status, EMIL, seite = melde_an("Emil", [FRUEH])
    pruefe(status == 409 and "gerade nicht frei" in seite, "ohne Häkchen keine Warteliste")
    status, DORA, _ = melde_an("Dora", warte=[FRUEH])
    pruefe(status == 303 and zeilen("SELECT helfer_id FROM warteliste WHERE schicht_id = ?", FRUEH)
           == [(DORA,)] and not einteilung(FRUEH, DORA), "mit Häkchen steht Dora auf der Warteliste")
    _, _, seite = anfrage("GET", platz(DORA))
    pruefe("Warteliste" in seite and "Von der Warteliste nehmen" in seite,
           "Mein Helferplatz zeigt es, mit dem Weg herunter")

    print("Absagen (S-01) und Nachrücken")
    _, _, seite = anfrage("GET", platz(BERT))
    eid = einteilung(FRUEH, BERT)[0][0]
    pruefe(f"/absagen/{eid}" in seite and f"/tauschen/{eid}" in seite,
           "an jeder Schicht: tauschen und absagen")
    status, _, seite = anfrage("GET", platz(BERT) + f"/absagen/{eid}")
    pruefe(status == 200 and "Schicht absagen?" in seite and 'name="grund"' in seite
           and einteilung(FRUEH, BERT), "erst eine Rückfrage, der Grund ist freiwillig")
    status, ort, _ = anfrage("POST", platz(BERT) + f"/absagen/{eid}", {"grund": "krank"})
    pruefe(status == 303 and "hinweis=abgesagt" in ort and not einteilung(FRUEH, BERT),
           "abgesagt")
    _, _, seite = anfrage("GET", ort)
    pruefe("danke, dass du Bescheid sagst" in seite, "die Seite bedankt sich, statt zu mahnen")
    pruefe(len(mails("abgesagt", "bert@example.org")) == 1
           and zeilen("SELECT name, grund, kurzfristig FROM absage WHERE schicht_id = ?", FRUEH)
           == [("Bert Berg", "krank", 0)], "mit Mail und als Absage vermerkt")
    pruefe(einteilung(FRUEH, CLEO)[0][1] == "platz", "Cleo rückt von der Reserve auf den Platz")
    angebot = einteilung(FRUEH, DORA)
    pruefe(angebot and angebot[0][1] == "reserve" and angebot[0][2] == "2027-06-02 10:00"
           and not zeilen("SELECT 1 FROM warteliste WHERE helfer_id = ?", DORA),
           "Dora bekommt die Reserve angeboten, gehalten für 24 Stunden")
    post = mails("angebot", "dora@example.org")
    pruefe(len(post) == 1 and "/platz/" in post[0] and "Mi 02.06. 10:00 Uhr" in post[0],
           "per Mail, mit Frist und Link")
    pruefe(not mails("leitung", "kalle@example.org"),
           "die Schicht bleibt über ihrem Minimum – keine Meldung nötig")
    admin = {}
    anfrage("POST", "/helfer/login", {"email": "ada@example.org",
                                      "passwort": "ein-langes-passwort", "weiter": "/helfer"}, admin)
    _, _, seite = anfrage("GET", f"/helfer/schicht/{FRUEH}", glas=admin)
    pruefe("angeboten bis" in seite, "das Backoffice zeigt das Angebot")
    _, _, seite = anfrage("GET", platz(DORA))
    pruefe("Ein Platz ist frei geworden" in seite and 'value="ja"' in seite,
           "Dora sieht es in Mein Helferplatz")
    status, ort, _ = anfrage("POST", platz(DORA) + f"/angebot/{angebot[0][0]}", {"antwort": "ja"})
    pruefe("hinweis=angenommen" in ort and einteilung(FRUEH, DORA)[0][2] is None,
           "Ja – der Platz gehört ihr")

    _, EMIL, _ = melde_an("Emil", warte=[FRUEH])
    anfrage("POST", platz(CLEO) + f"/absagen/{einteilung(FRUEH, CLEO)[0][0]}", {})
    pruefe(einteilung(FRUEH, DORA)[0][1] == "platz" and einteilung(FRUEH, EMIL)[0][1] == "reserve",
           "Cleo sagt ab: Dora rückt auf, Emil bekommt die Reserve angeboten")
    status, ort, _ = anfrage("POST", platz(EMIL) + f"/angebot/{einteilung(FRUEH, EMIL)[0][0]}",
                             {"antwort": "nein"})
    pruefe("hinweis=abgelehnt" in ort and not einteilung(FRUEH, EMIL)
           and zeilen("SELECT COUNT(*) FROM absage WHERE helfer_id = ?", EMIL) == [(0,)],
           "Nein – der Platz geht weiter, und das ist keine Absage")

    _, FRANK, _ = melde_an("Frank", warte=[FRUEH])
    _, GERT, _ = melde_an("Gert", warte=[FRUEH])
    pruefe(einteilung(FRUEH, FRANK)[0][1] == "reserve", "Frank bekommt die freie Reserve sofort")
    pruefe(einteilung(FRUEH, FRANK)[0][2] is None,
           "wer frei bucht, muss nichts bestätigen – das Häkchen galt nur für den Fall")
    anfrage("POST", "/helfer/einteilung/%d/austragen" % einteilung(FRUEH, FRANK)[0][0],
            {"csrf": re.search(r'name="csrf" value="([^"]+)"',
                               anfrage("GET", "/helfer/schichten", glas=admin)[2]).group(1),
             "weiter": f"/helfer/schicht/{FRUEH}"}, admin)
    pruefe(einteilung(FRUEH, GERT) and einteilung(FRUEH, GERT)[0][2] is not None
           and len(mails("angebot", "gert@example.org")) == 1,
           "von Hand ausgetragen: Gert von der Warteliste bekommt das Angebot")
    testdb.abfrage(db_url, "helfer", "UPDATE einteilung SET bestaetigen_bis = '2027-06-01 09:00'"
                   " WHERE helfer_id = %d" % GERT)
    versand.fristen()
    pruefe(not einteilung(FRUEH, GERT) and any("Angebot verfallen" in w for (w,) in zeilen(
        "SELECT was FROM protokoll WHERE helfer_id = ?", GERT)),
           "ohne Antwort verfällt das Angebot")

    print("Kurzfristig und unter Minimum (S-07)")
    _, IDA, _ = melde_an("Ida", [AUFBAU])
    _, HANNA, _ = melde_an("Hanna", [AUFBAU])
    # Springer-Zeiten gibt es nur an Veranstaltungstagen; für den Aufbau
    # rückt der Test sie von Hand auf den Vortag.
    _, JONAS, _ = melde_an("Jonas", springer=["2027-07-03|frueh"])
    testdb.abfrage(db_url, "helfer", "UPDATE verfuegbarkeit SET beginn = '2027-06-02 06:00',"
                   " ende = '2027-06-02 13:00' WHERE helfer_id = %d" % JONAS)
    anfrage("POST", platz(HANNA) + f"/absagen/{einteilung(AUFBAU, HANNA)[0][0]}",
            {"grund": "Auto kaputt"})
    pruefe(zeilen("SELECT kurzfristig FROM absage WHERE helfer_id = ?", HANNA) == [(1,)],
           "weniger als 24 Stunden vorher: kurzfristig")
    post = mails("leitung", "orga@example.org")
    pruefe(len(post) == 1 and "Hanna Berg" in post[0] and "unter ihrem Minimum" in post[0]
           and "Auto kaputt" in post[0], "die Strecke hat keine Leitung – die Orga bekommt Bescheid")
    _, _, seite = anfrage("GET", "/helfer", glas=admin)
    pruefe("Kurzfristig abgesagt" in seite and "Hanna Berg" in seite and "Jonas Berg" in seite
           and "unter Minimum" in seite, "oben in der Übersicht, mit dem Springer, der kann (R-06)")
    anfrage("POST", platz(ANNA) + f"/absagen/{einteilung(MITTAG, ANNA)[0][0]}", {})
    post = mails("leitung", "kalle@example.org")
    pruefe(len(post) == 1 and "Anna Berg" in post[0] and "unter ihrem Minimum" in post[0],
           "Anna sagt ab, der Mittag ist unter Minimum: Kalle bekommt Bescheid")
    kalle = {}
    anfrage("POST", "/helfer/login", {"email": "kalle@example.org",
                                      "passwort": "kalles-langes-passwort", "weiter": "/helfer"}, kalle)
    _, _, seite = anfrage("GET", "/helfer/bereiche", glas=kalle)
    pruefe("Kurzfristig abgesagt" not in seite, "kurzfristig war nur die Strecke – nicht Kalles Bereich")

    print("Tauschen (S-02)")
    _, KURT, _ = melde_an("Kurt", [FRUEH])
    pruefe(einteilung(FRUEH, KURT)[0][1] == "reserve", "Kurt nimmt die freie Reserve – Früh ist voll")
    eid = einteilung(MITTAG, FRITZ)[0][0]
    _, _, seite = anfrage("GET", platz(ANNA) + f"/tauschen/{eid}")
    pruefe("Am selben Tag, im selben Bereich" not in seite and "Weitere Schichten" in seite
           and f'value="{POSTEN}"' in seite and f'value="{FRUEH}"' not in seite,
           "die Auswahl ohne volle Schichten")
    status, _, seite = anfrage("POST", platz(ANNA) + f"/tauschen/{eid}", {"s": FRUEH})
    pruefe(status == 409 and "bleibt" in seite and einteilung(MITTAG, FRITZ),
           "in eine volle geht es nicht – die alte bleibt")
    _, _, seite = anfrage("GET", platz(KURT) + f"/tauschen/{einteilung(FRUEH, KURT)[0][0]}")
    mittag_frei = f'value="{MITTAG}"' in seite
    status, _, seite = anfrage("POST", platz(KURT) + f"/tauschen/{einteilung(FRUEH, KURT)[0][0]}",
                               {"s": MITTAG})
    pruefe(mittag_frei and status == 400 and "Führerschein Klasse B" in seite
           and 'name="voraussetzung_ok"' in seite and einteilung(FRUEH, KURT),
           "was die neue Schicht verlangt, wird erst bestätigt")
    status, ort, _ = anfrage("POST", platz(KURT) + f"/tauschen/{einteilung(FRUEH, KURT)[0][0]}",
                             {"s": MITTAG, "voraussetzung_ok": "1"})
    pruefe(status == 303 and einteilung(MITTAG, KURT) and not einteilung(FRUEH, KURT),
           "mit Häkchen geht der Tausch")
    status, ort, _ = anfrage("POST", platz(ANNA) + f"/tauschen/{eid}", {"s": POSTEN})
    pruefe(status == 303 and "hinweis=getauscht" in ort and not einteilung(MITTAG, FRITZ)
           and einteilung(POSTEN, FRITZ), "Fritz tauscht den Mittag gegen den Posten")
    pruefe(len(mails("getauscht", "anna@example.org")) == 1 and zeilen(
        "SELECT grund FROM absage WHERE helfer_id = ? AND schicht_id = ?", FRITZ, MITTAG)
        == [("umgebucht auf Streckenposten Sa 03.07. 08:00–13:00",)],
        "Anna bekommt die Mail; der Mittag sieht eine Absage mit Grund")

    print("Ganz abmelden (S-03)")
    _, _, seite = anfrage("GET", platz(IDA) + "/aa-2027/abmelden")
    pruefe("Ganz abmelden?" in seite and 'name="grund"' in seite, "Rückfrage mit freiwilligem Grund")
    status, ort, _ = anfrage("POST", platz(IDA) + "/aa-2027/abmelden", {"grund": "Urlaub"})
    pruefe("hinweis=abgemeldet" in ort and not einteilung(AUFBAU, IDA)
           and zeilen("SELECT COUNT(*) FROM teilnahme WHERE helfer_id = ?", IDA) == [(0,)]
           and len(mails("abgemeldet", "ida@example.org")) == 1, "alles weg, mit Mail")
    fenster = zeilen("SELECT id FROM verfuegbarkeit WHERE helfer_id = ?", JONAS)[0][0]
    status, ort, _ = anfrage("POST", platz(JONAS) + f"/springer/{fenster}/weg")
    pruefe("hinweis=springer-weg" in ort and not zeilen(
        "SELECT 1 FROM verfuegbarkeit WHERE helfer_id = ?", JONAS), "Springer-Zeit abgesagt")
    status, _, _ = anfrage("POST", platz(JONAS) + f"/absagen/{einteilung(POSTEN, FRITZ)[0][0]}")
    pruefe(status == 404 and einteilung(POSTEN, FRITZ), "fremde Schichten sagt niemand ab")

    print("Angaben ändern (S-04, S-06)")
    _, _, seite = anfrage("GET", platz(ANNA) + "/angaben")
    pruefe('value="damen" selected' in seite and 'value="vegetarisch" selected' in seite
           and f'name="m{FRITZ}-tshirt"' in seite, "vorbelegt, für Anna und Fritz")
    basis = {"ich-telefon": "0151 7777777", "ich-tshirt": "L", "ich-schnitt": "herren",
             "ich-verpflegung": "fleisch", f"m{FRITZ}-tshirt": "M", f"m{FRITZ}-schnitt": "damen",
             f"m{FRITZ}-verpflegung": "vegetarisch", f"bemerkung-{VA}": "komme mit dem Rad"}
    status, _, seite = anfrage("POST", platz(ANNA) + "/angaben", {**basis, "ich-telefon": "ruf an"})
    pruefe(status == 400 and "nicht lesen" in seite, "eine kaputte Nummer wird gemeldet")
    status, ort, _ = anfrage("POST", platz(ANNA) + "/angaben", basis)
    pruefe("hinweis=angaben" in ort and zeilen(
        "SELECT telefon, tshirt_roh, veggie FROM helfer WHERE id IN (?, ?) ORDER BY id", ANNA, FRITZ)
        == [("+49 1517777777", "Herren L", 0), ("", "Damen M", 1)], "gespeichert, für beide")
    pruefe(zeilen("SELECT bemerkung FROM teilnahme WHERE helfer_id = ?", ANNA)
           == [("komme mit dem Rad",)], "die Bemerkung zur Veranstaltung auch")
    alt_platz = platz(ANNA)
    status, ort, _ = anfrage("POST", alt_platz + "/angaben",
                             {**basis, "ich-email_neu": "Anna.Neu@example.org"})
    pruefe("hinweis=adresse" in ort and zeilen("SELECT email, email_neu FROM helfer WHERE id = ?", ANNA)
           == [("anna@example.org", "anna.neu@example.org")], "die neue Adresse ist erst vorgemerkt")
    link = re.search(r"(https://\S+/email/\S+)", mails("neue_adresse", "anna.neu@example.org")[0]).group(1)
    pfad = link.replace("https://helfer.example.de", "")
    status, _, seite = anfrage("GET", pfad)
    pruefe(status == 200 and "anna.neu@example.org" in seite and "Ja, das bin ich" in seite,
           "die Mail geht an die neue Adresse, der Link zeigt einen Knopf")
    status, ort, _ = anfrage("POST", pfad)
    pruefe(status == 303 and "adresse-bestaetigt" in ort and zeilen(
        "SELECT email, email_neu FROM helfer WHERE id = ?", ANNA) == [("anna.neu@example.org", None)],
        "bestätigt: jetzt gilt sie")
    pruefe(anfrage("GET", alt_platz)[0] == 200, "der Link zu Mein Helferplatz gilt weiter")
    status, _, _ = anfrage("POST", pfad)
    pruefe(status == 404, "und der Bestätigungslink nur einmal")
    anfrage("POST", alt_platz + "/angaben", {**basis, f"m{FRITZ}-email_neu": "fritz@example.org"})
    link = re.search(r"(https://\S+/email/\S+)", mails("neue_adresse", "fritz@example.org")[0]).group(1)
    status, ort, _ = anfrage("POST", link.replace("https://helfer.example.de", ""))
    pruefe(status == 303 and zeilen("SELECT email, angemeldet_von FROM helfer WHERE id = ?", FRITZ)
           == [("fritz@example.org", None)], "Fritz mit eigener Adresse steht auf eigenen Füßen")
    _, _, seite = anfrage("GET", ort)
    pruefe("Hallo Fritz" in seite and "Streckenposten" in seite, "und hat seinen eigenen Helferplatz")

    print("Löschen (S-05)")
    status, ort, _ = anfrage("POST", alt_platz + "/aa-2027/angaben",
                             [("s", POSTEN_SO), ("aktion", "eintragen"), ("weitere", 1),
                              ("p0-vorname", "Mia"), ("p0-nachname", "Berg"),
                              ("p0-volljaehrig", "ja"), ("p0-tshirt", "S"), ("p0-schnitt", "damen"),
                              ("p0-verpflegung", "fleisch")])
    MIA = zeilen("SELECT id FROM helfer WHERE angemeldet_von = ?", ANNA)[0][0]
    _, _, seite = anfrage("GET", alt_platz + f"/loeschen?wer={MIA}")
    pruefe("Daten von Mia löschen?" in seite, "Mia einzeln: erst die Rückfrage")
    status, ort, _ = anfrage("POST", alt_platz + f"/loeschen?wer={MIA}")
    pruefe("hinweis=geloescht" in ort and zeilen("SELECT COUNT(*) FROM helfer WHERE id = ?", MIA)
           == [(0,)] and zeilen("SELECT name FROM absage WHERE schicht_id = ? AND helfer_id IS NULL",
                                POSTEN_SO) == [("",)], "Mia ist weg – auch ihr Name an der Absage")
    db.material_standard(VA)
    funk = next(m["id"] for m in db.materialien(VA) if m["name"] == "Funkgerät")
    ausleihe, _ = db.ausgeben(VA, BERT, "", [{"material_id": funk, "menge": 1}])
    status, _, seite = anfrage("POST", platz(BERT) + "/loeschen")
    pruefe(zeilen("SELECT loeschen_beantragt_am IS NOT NULL FROM helfer WHERE id = ?", BERT)
           == [(True,)] and "Funkgerät" in mails("geloescht", "bert@example.org")[0],
           "Bert hat noch ein Funkgerät: gelöscht wird nach der Rückgabe, und die Mail sagt warum")
    db.ausgabe_zurueck(ausleihe)
    pruefe(zeilen("SELECT COUNT(*) FROM helfer WHERE id = ?", BERT) == [(0,)],
           "nach der Rückgabe ist Bert weg")
    _, _, seite = anfrage("GET", alt_platz + "/loeschen")
    pruefe("Deine Daten löschen?" in seite and "nicht zurücknehmen" in seite, "Rückfrage")
    status, _, seite = anfrage("POST", alt_platz + "/loeschen")
    pruefe(status == 200 and "Deine Daten sind gelöscht" in seite
           and zeilen("SELECT COUNT(*) FROM helfer WHERE id = ?", ANNA) == [(0,)],
           "Anna löscht alles")
    pruefe(anfrage("GET", alt_platz)[0] == 404, "danach gilt ihr Link nicht mehr")
    pruefe(zeilen("SELECT helfer_id FROM mail_out WHERE typ = 'geloescht'"
                  " AND empfaenger = 'anna.neu@example.org'") == [(None,)],
           "die Abschiedsmail geht trotzdem raus")

    print("Änderungen seit gestern (S-08)")
    _, _, seite = anfrage("GET", "/helfer/aenderungen", glas=admin)
    pruefe("krank" in seite and "Auto kaputt" in seite and "Urlaub" in seite
           and "Angebot angenommen" in seite, "Absagen mit Grund und alles andere")
    pruefe('href="/helfer/aenderungen"' in seite, "steht in der Navigation")
    status, _, seite = anfrage("GET", "/helfer/aenderungen", glas=kalle)
    pruefe(status == 200 and "krank" in seite and "Auto kaputt" not in seite,
           "die Bereichsleitung sieht nur ihre Bereiche")
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
