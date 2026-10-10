"""Check-in zentral bei der Orga (Lastenheft 4.1: T-01 bis T-03).

    python helfer/tests/test_checkin.py

Alle melden sich 15 Minuten vor Beginn an einem Tisch bei der Orga – mit
dem QR-Code aus der Erinnerung oder ihrem Namen. Ein Klick checkt alle
Schichten des Tages ein, für die ganze Familie auf einmal; im selben Zug
Shirt, Goodies und Material. Wer fehlt, steht als „noch nicht da“ in der
Übersicht. Ob es den Check-in gibt, stellt die Veranstaltung ein.
"""

import http.client
import os
import re
import socket
import subprocess
import sys
import time
import urllib.parse
from datetime import datetime
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


db_url = testdb.wegwerf("helfer_checkin")
os.environ.update({"DATABASE_URL": db_url, "APP_SECRET_KEY": "test-schluessel",
                   "JETZT_FEST": "2027-07-01 10:00", "BASIS_URL": "https://helfer.example.org"})

from app import config, db, mail, versand, zugang  # noqa: E402
from kern import mail as kern_mail  # noqa: E402

db.init()
VA = db.VERANSTALTUNGEN.anlegen({"name": "Die absolute Abfahrt 2027", "kurz": "AA 2027",
                                 "beginn": "2027-07-01", "ende": "2027-07-04",
                                 "ort": "Ilmenau", "status": "offen"})
ANGEBOT = {"goodies": 1, "shirt": 1, "schnitte": 0, "verpflegung": 0, "party": 0, "checkin": 1}
db.angebot_setzen(VA, ANGEBOT)
db.goodie_anlegen(VA, {"name": "Bier am Bierwagen", "ab_schichten": 2, "ab_stunden": None,
                       "mindestalter": 16, "alternative": "Eistüte"})
db.material_standard(VA)
LEER = {"beschreibung": "", "treffpunkt": "Zelt", "mindestalter": None, "voraussetzungen": "",
        "intern": 0}
STRECKE = db.bereich_anlegen(VA, {**LEER, "name": "Strecke"})
SHUTTLE = db.bereich_anlegen(VA, {**LEER, "name": "Shuttle"})


def schicht(b, tag, von, bis):
    return db.schicht_anlegen(VA, b, {
        "datum": tag, "beginn": f"{tag} {von}", "ende": f"{tag} {bis}", "minimum": 1,
        "soll": 8, "reserve": 0, "mindestalter": None, "ort": "", "hinweis": "", "intern": 0})


FRUEH = schicht(STRECKE, "2027-07-02", "09:00", "12:00")
SPAET = schicht(STRECKE, "2027-07-02", "13:00", "17:00")
LAUF = schicht(SHUTTLE, "2027-07-02", "08:00", "12:00")
BALD = schicht(SHUTTLE, "2027-07-02", "10:30", "12:00")
MORGEN = schicht(SHUTTLE, "2027-07-03", "08:00", "12:00")


def sql(text, *parameter):
    return testdb.abfrage(db_url, "helfer", text, parameter)


def person(name, **mehr):
    nummer, _ = db.helfer_von_hand({"name": name, "email": mehr.pop("email", name.split()[0].lower()
                                                                     + "@example.org")})
    werte = {"vorname": name.split()[0], **mehr}
    sql("UPDATE helfer SET " + ", ".join(k + " = ?" for k in werte) + " WHERE id = ?",
        *werte.values(), nummer)
    return nummer


ANNA = person("Anna Berg", volljaehrig=1, tshirt="M")
KAI = person("Kai Berg", email="", geburtsdatum="2012-05-01", volljaehrig=0, angemeldet_von=ANNA)
BEN = person("Ben Lauf", volljaehrig=1, telefon="+491511111111")
CARL = person("Carl Bald", volljaehrig=1)
DORA = person("Dora Morgen", volljaehrig=1)
# Lena ist von Hand angelegt, ihr Alter kennen wir nicht.
LENA = person("Lena Ohne", volljaehrig=None)
for helfer_id, schicht_id in ((ANNA, FRUEH), (ANNA, SPAET), (KAI, FRUEH), (KAI, SPAET),
                              (LENA, FRUEH), (LENA, SPAET),
                              (BEN, LAUF), (CARL, BALD), (DORA, MORGEN)):
    db.einteilen(schicht_id, helfer_id)
KONTO = testdb.abfrage(db_url, "kern", "INSERT INTO konto (email, name, kuerzel, rolle)"
                       " VALUES ('rita@example.org', 'Rita Leitung', 'RL', 'orga') RETURNING id")[0][0]
sql("INSERT INTO bereich_leitung (bereich_id, konto_id) VALUES (?, ?)", SHUTTLE, KONTO)

print("Erinnerung mit Code (C-02, T-01)")
pruefe(versand.erinnern() == 5, "fünf Erinnerungen: Anna (mit Kai), Lena, Ben, Carl, Dora")
anna_mail = sql("SELECT * FROM mail_out WHERE helfer_id = ? AND typ = 'vorher'", ANNA)[0]
CODE = zugang.token(zugang.CHECKIN, db.helfer_laden(ANNA))
pruefe(anna_mail["qr"] == CODE and "Code im Anhang" in anna_mail["body"]
       and "Check-in bei der Orga" in anna_mail["body"],
       "Annas Erinnerung bittet zum Check-in und trägt ihren Code")
pruefe(versand._qr_anhang(CODE)[0][1] == "image/png"
       and versand._qr_anhang(CODE)[0][2].startswith(b"\x89PNG") and versand._qr_anhang("") == [],
       "der Code wird beim Verschicken zum PNG")

gesendet = []


class Postfach:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def starttls(self, **_):
        pass

    def login(self, *_):
        pass

    def send_message(self, nachricht):
        gesendet.append(nachricht)


kern_mail._verbindung = lambda _: Postfach()
config.SMTP_HOST, config.MAIL_FROM = "smtp.example.org", "orga@example.org"
pruefe(versand.verschicken() == (5, 0), "verschickt")
an_anna = next(n for n in gesendet if n["To"] == "anna@example.org")
anhaenge = list(an_anna.iter_attachments())
pruefe(len(anhaenge) == 1 and anhaenge[0].get_filename() == "check-in-code.png"
       and anhaenge[0].get_content_type() == "image/png"
       and "Check-in bei der Orga" in an_anna.get_body(("plain",)).get_content(),
       "die Mail ist Text, der Code hängt als Bild daran")
ohne = mail.vorher(db.helfer_laden(BEN), "AA", "Morgen", [], [], [], "https://x", checkin=False)
pruefe("am Treffpunkt und melde dich bei der" in ohne[3] and "Check-in" not in ohne[3],
       "ohne Check-in schickt die Erinnerung gleich zum Treffpunkt")

hafen = freier_hafen()
prozess = subprocess.Popen(
    [str(PYTHON), "-m", "app"], cwd=str(WURZEL),
    env={**os.environ, "BIND": f"127.0.0.1:{hafen}", "ADMIN_PASSWORD_HASH": HASH,
         "JETZT_FEST": "2027-07-02 08:50", "SMTP_HOST": "", "MAIL_FROM": "",
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

    def anfrage(methode, pfad, daten=None, mit_glas=True):
        verbindung = http.client.HTTPConnection("127.0.0.1", hafen, timeout=10)
        koerper = urllib.parse.urlencode(daten, doseq=True).encode() if daten else None
        kopf = {"Content-Type": "application/x-www-form-urlencoded"} if koerper else {}
        if glas and mit_glas:
            kopf["Cookie"] = "; ".join(k + "=" + w for k, w in glas.items())
        verbindung.request(methode, pfad, body=koerper, headers=kopf)
        antwort = verbindung.getresponse()
        if mit_glas:
            for gesetzt in antwort.headers.get_all("Set-Cookie") or []:
                name, _, wert = gesetzt.split(";")[0].partition("=")
                glas[name] = wert
        ergebnis = (antwort.status, antwort.getheader("Location", ""),
                    unescape(antwort.read().decode("utf-8")))
        verbindung.close()
        return ergebnis

    def da(helfer_id):
        return [z[0] for z in sql("SELECT e.schicht_id FROM einteilung e WHERE e.helfer_id = ?"
                                  " AND e.eingecheckt_am IS NOT NULL ORDER BY e.schicht_id", helfer_id)]

    anfrage("POST", "/helfer/login", {"passwort": "test-passwort-123", "kuerzel": "KK",
                                      "weiter": "/helfer"})

    print("Der Tisch (T-01)")
    status, _, seite = anfrage("GET", "/helfer/checkin")
    csrf = re.search(r'name="csrf" value="([^"]+)"', seite).group(1)
    pruefe(status == 200 and 'href="/helfer/checkin"' in seite,
           "Check-in steht unter Vor Ort")
    pruefe(seite.index('href="/helfer/checkin"') < seite.index('href="/helfer/monitor"'),
           "vorn, vor dem Monitor")
    zahlen = re.findall(r'zaehler-zahl">(\d+)<', seite)
    pruefe(zahlen[:2] == ["0", "4"], "heute niemand da; noch nicht da: Anna, Kai, Lena, Ben – " + str(zahlen))
    liste = seite.split("Noch nicht da (")[1].split("Gleich dran")[0]
    pruefe("Anna Berg" in liste and "Kai Berg" in liste and "Ben Lauf" in liste
           and "Carl Bald" not in liste,
           "noch nicht da: wer in 15 Minuten anfängt oder schon läuft – Carl erst um halb elf")
    pruefe("Carl Bald" in seite.split("Gleich dran")[1] and "Dora" not in seite,
           "Carl steht unter „gleich dran“, Dora ist erst morgen dran")

    status, ort, _ = anfrage("GET", "/helfer/checkin?" + urllib.parse.urlencode({"q": CODE}))
    pruefe(status == 303 and ort == f"/helfer/checkin?p={ANNA}", "der gescannte Code führt zu Anna")
    status, ort, _ = anfrage("GET", "/helfer/checkin?q=" + urllib.parse.quote(
        "https://irgendwo/" + str(ANNA) + "." + "0" * 32))
    pruefe("hinweis=code-unbekannt" in ort, "ein falscher Code findet niemanden")
    _, _, seite = anfrage("GET", "/helfer/checkin?q=carl")
    pruefe(f'href="/helfer/checkin?p={CARL}"' in seite, "ohne Code nach dem Namen")

    _, _, seite = anfrage("GET", f"/helfer/checkin?p={ANNA}")
    pruefe(f'id="person-{ANNA}"' in seite and f'id="person-{KAI}"' in seite
           and "Alle einchecken" in seite, "Anna kommt mit Kai – beide stehen da, ein Knopf für alle")
    pruefe("Das Shirt gibt es nach dem Einchecken." in seite, "das Shirt erst nach dem Einchecken")
    pruefe("Goodies: noch 2 Schichten bis Bier am Bierwagen." in seite
           and "Bier am Bierwagen ausgeben" not in seite,
           "Goodies erst nach angetretenen Schichten – noch 2 bis zum Bier")

    print("Einchecken")
    status, ort, _ = anfrage("POST", f"/helfer/checkin/{ANNA}", {"csrf": csrf, "alle": "1"})
    pruefe("hinweis=eingecheckt" in ort and f"p={ANNA}" in ort, "eingecheckt, zurück zu Anna")
    pruefe(da(ANNA) == [FRUEH, SPAET] and da(KAI) == [FRUEH, SPAET],
           "beide, für alle Schichten des Tages")
    pruefe(sql("SELECT eingecheckt_von FROM einteilung WHERE helfer_id = ? AND schicht_id = ?",
               ANNA, FRUEH)[0][0] == "KK", "mit Kürzel")
    pruefe(sql("SELECT was FROM protokoll WHERE helfer_id = ? ORDER BY id DESC", ANNA)[0][0]
           == "Eingecheckt", "und im Verlauf")
    status, ort, _ = anfrage("POST", f"/helfer/checkin/{DORA}", {"csrf": csrf})
    pruefe("hinweis=nichts-heute" in ort and da(DORA) == [], "Dora hat heute nichts – kein Haken")

    print("Am selben Tisch (T-03)")
    _, _, seite = anfrage("GET", f"/helfer/checkin?p={ANNA}")
    pruefe("Shirt ausgeben" in seite and re.search(r'<option value="M" selected>', seite),
           "jetzt das Shirt, ihre Größe vorgewählt")
    status, ort, _ = anfrage("POST", f"/helfer/checkin/{ANNA}/tshirt",
                             {"csrf": csrf, "groesse": "L", "p": str(ANNA)})
    pruefe("hinweis=tshirt" in ort and f"p={ANNA}" in ort
           and sql("SELECT tshirt_ausgegeben FROM helfer WHERE id = ?", ANNA)[0][0] == "L",
           "ausgegeben, zurück am Tisch")
    pruefe(f'href="/helfer/ausgabe?helfer={ANNA}"' in seite, "Material mit einem Klick")
    _, _, seite = anfrage("GET", f"/helfer/ausgabe?helfer={ANNA}")
    pruefe(re.search(r'<option value="%d" selected>' % ANNA, seite),
           "in der Ausgabe ist Anna schon gewählt")

    print("Goodies abhaken (4.2, G-02)")
    _, _, seite = anfrage("GET", f"/helfer/checkin?p={ANNA}")
    anna = seite.split(f'id="person-{ANNA}"')[1].split(f'id="person-{KAI}"')[0]
    kai = seite.split(f'id="person-{KAI}"')[1]
    pruefe(">Bier am Bierwagen ausgeben</button>" in anna,
           "Anna hat zwei Schichten angetreten – das Bier steht zu")
    pruefe(">Eistüte ausgeben</button>" in kai and "statt Bier am Bierwagen, unter 16" in kai,
           "Kai ist 15 – für ihn die Eistüte")
    goodie = sql("SELECT id FROM goodie WHERE veranstaltung_id = ?", VA)[0][0]
    status, ort, _ = anfrage("POST", f"/helfer/checkin/{ANNA}/goodie/{goodie}",
                             {"csrf": csrf, "p": str(ANNA)})
    anfrage("POST", f"/helfer/checkin/{ANNA}/goodie/{goodie}", {"csrf": csrf, "p": str(ANNA)})
    pruefe("hinweis=goodie" in ort and [tuple(z.values()) for z in sql(
        "SELECT was, ausgegeben_von FROM goodie_ausgabe WHERE helfer_id = ?", ANNA)]
           == [("Bier am Bierwagen", "KK")], "abgehakt, einmal, mit Kürzel")
    anfrage("POST", f"/helfer/checkin/{KAI}/goodie/{goodie}", {"csrf": csrf, "p": str(ANNA),
                                                               "voll": "1"})
    pruefe(sql("SELECT was FROM goodie_ausgabe WHERE helfer_id = ?", KAI)[0][0] == "Eistüte",
           "Kai bekommt die Eistüte – auch wenn jemand auf „Ausweis“ drückt, sein Alter ist bekannt")
    _, _, seite = anfrage("GET", f"/helfer/checkin?p={ANNA}")
    pruefe("✓</span> Bier am Bierwagen" in seite and "✓</span> Eistüte" in seite,
           "am Tisch steht, was schon raus ist")
    anfrage("POST", f"/helfer/checkin/{LENA}", {"csrf": csrf})
    _, _, seite = anfrage("GET", f"/helfer/checkin?p={LENA}")
    pruefe("Bier am Bierwagen – Ausweis ab 16 gezeigt" in seite and ">Eistüte ausgeben</button>" in seite,
           "bei Lena, Alter unbekannt: Bier nach Ausweis oder die Eistüte")
    anfrage("POST", f"/helfer/checkin/{LENA}/goodie/{goodie}", {"csrf": csrf, "p": str(LENA),
                                                                "voll": "1"})
    pruefe(sql("SELECT was FROM goodie_ausgabe WHERE helfer_id = ?", LENA)[0][0] == "Bier am Bierwagen",
           "Ausweis gezeigt – das Bier")
    status, ort, _ = anfrage("POST", f"/helfer/checkin/{CARL}/goodie/{goodie}", {"csrf": csrf})
    pruefe("hinweis=goodie-nicht" in ort and not sql("SELECT 1 FROM goodie_ausgabe WHERE helfer_id = ?", CARL),
           "Carl hat noch keine Schicht angetreten – nichts")
    anfrage("POST", f"/helfer/checkin/{ANNA}/goodie/{goodie}/zurueck", {"csrf": csrf, "p": str(ANNA)})
    pruefe(not sql("SELECT 1 FROM goodie_ausgabe WHERE helfer_id = ?", ANNA), "zurücknehmen geht")

    print("Noch nicht da (T-02)")
    _, _, seite = anfrage("GET", "/helfer")
    box = seite.split("Noch nicht da (")[1][:600] if "Noch nicht da (" in seite else ""
    pruefe(box.startswith("1)") and "Ben Lauf" in box and "+491511111111" in box,
           "die Übersicht zeigt Ben – mit Nummer, zum Anrufen")
    pruefe(f'href="/helfer/schicht/{LAUF}"' in box, "und seiner Schicht, um einen Springer einzusetzen")
    uhr = datetime(2027, 7, 2, 8, 50)
    pruefe([z["id"] for z in db.noch_nicht_da(VA, KONTO, uhr)] == [BEN]
           and db.noch_nicht_da(VA, KONTO + 1000, uhr) == [],
           "die Bereichsleitung sieht ihre Bereiche")
    status, ort, _ = anfrage("POST", f"/helfer/checkin/{BEN}", {"csrf": csrf, "liste": "1"})
    pruefe(ort == "/helfer/checkin?hinweis=eingecheckt" and da(BEN) == [LAUF],
           "aus der Liste heraus: Ben ist da, die Liste bleibt stehen")
    anfrage("POST", f"/helfer/checkin/{BEN}/zurueck", {"csrf": csrf, "liste": "1"})
    pruefe(da(BEN) == [], "zurückgenommen – falls es der Falsche war")

    print("Mein Helferplatz zeigt den Code")
    tok = zugang.token(zugang.PLATZ, db.helfer_laden(ANNA))
    _, _, seite = anfrage("GET", f"/platz/{tok}", mit_glas=False)
    pruefe("Dein Check-in" in seite and "<svg" in seite and "Gilt auch für alle" in seite,
           "mit dem QR-Code, der auch für Kai gilt")

    print("Ohne Check-in")
    db.angebot_setzen(VA, {**ANGEBOT, "checkin": 0})
    _, _, seite = anfrage("GET", "/helfer/checkin")
    pruefe("Kein Check-in" in seite and 'href="/helfer/checkin"' not in seite,
           "die Seite sagt es, und unter Vor Ort steht er nicht")
    _, _, seite = anfrage("GET", "/helfer")
    pruefe("Noch nicht da (" not in seite, "niemand ist „noch nicht da“")
    _, _, seite = anfrage("GET", f"/platz/{tok}", mit_glas=False)
    pruefe("Dein Check-in" not in seite, "Mein Helferplatz zeigt keinen Code")
    _, _, seite = anfrage("GET", "/helfer/goodies")
    pruefe('name="checkin" value="1"' in seite and "Check-in bei der Orga" in seite,
           "einschalten lässt er sich beim Angebot")
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
