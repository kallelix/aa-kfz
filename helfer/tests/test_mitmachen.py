"""Helfer werden ohne Veranstaltung (Lastenheft C-10).

    python helfer/tests/test_mitmachen.py

Unter /mitmachen meldet sich, wer helfen will, auch wenn gerade keine
Veranstaltung Helfer sucht – Vorname, Nachname, Mail, mehr nicht. Erst der
Klick in der Mail macht die Person zum Teil des Helferstamms; wer nie
bestätigt, ist nach der Frist wieder weg. Ist eine Veranstaltung offen, lädt
„Helferstamm einladen“ sie ein, und bei der Schichtwahl stehen Shirt und
Essen da, wie wir sie kennen – was fehlt, wird gefragt, das Alter nur, wenn
wir es nicht kennen.
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


db_url = testdb.wegwerf("helfer_mitmachen")
os.environ.update({"DATABASE_URL": db_url, "APP_SECRET_KEY": "test-schluessel",
                   "JETZT_FEST": "2027-03-01 10:00", "BASIS_URL": "https://helfer.example.org"})

from app import config, db, versand, zugang  # noqa: E402

db.init()


def sql(text, *parameter):
    return testdb.abfrage(db_url, "helfer", text, parameter)


def mails(typ):
    return {z["helfer_id"]: z for z in sql("SELECT * FROM mail_out WHERE typ = ? ORDER BY id", typ)}


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

    def anfrage(methode, pfad, daten=None, mit_glas=False):
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
                    unescape(antwort.read().decode("utf-8")), antwort.getheader("Content-Type", ""))
        verbindung.close()
        return ergebnis

    def melden(vorname, nachname, email, einverstanden=True, **mehr):
        daten = {"vorname": vorname, "nachname": nachname, "email": email, **mehr}
        if einverstanden:
            daten["einverstanden"] = "1"
        return anfrage("POST", "/mitmachen", daten)

    def helfer(email):
        zeilen = sql("SELECT * FROM helfer WHERE email = ? ORDER BY id", email)
        return zeilen[0] if zeilen else None

    print("Ohne Veranstaltung")
    status, _, seite, _ = anfrage("GET", "/")
    pruefe(status == 200 and "Gerade suchen wir keine Helfer" in seite
           and 'href="/mitmachen"' in seite, "die Startseite führt zu „Mitmachen“")
    status, _, seite, _ = anfrage("GET", "/mitmachen")
    pruefe(status == 200 and 'name="einverstanden"' in seite and 'name="tshirt"' not in seite,
           "nur Name, Mail, Handy und die Einwilligung – kein Shirt")
    status, _, seite, _ = melden("", "", "kaputt", einverstanden=False)
    pruefe(status == 400 and "Bitte den Vornamen." in seite and "Bitte den Nachnamen." in seite
           and "Diese Mailadresse sieht nicht vollständig aus." in seite
           and "Bitte das Häkchen setzen" in seite, "Pflicht sind Vorname, Nachname, Mail, Häkchen")
    status, ort, _, _ = melden("Robo", "Ter", "robo@example.org", webseite="http://spam")
    pruefe(status == 303 and helfer("robo@example.org") is None, "das Honigtopf-Feld fängt Roboter")

    status, ort, _, _ = melden("Lena", "Neu", "Lena@Example.org", telefon="0171 1234567")
    lena = helfer("lena@example.org")
    pruefe(status == 303 and ort == "/mitmachen?gesendet=1" and lena is not None
           and lena["mitmachen_am"] and lena["telefon"] and lena["volljaehrig"] is None
           and lena["stamm_einwilligung_am"] is None and lena["email_bestaetigt_am"] is None,
           "angelegt – noch nicht bestätigt, noch nicht im Helferstamm, ohne Alter")
    LENA = lena["id"] if lena else 0
    _, _, seite, _ = anfrage("GET", "/mitmachen?gesendet=1")
    pruefe("Fast geschafft!" in seite, "danach: in die Mail schauen")
    text = mails("mitmachen").get(LENA, {"body": ""})["body"]
    link = re.search(r"https://helfer\.example\.org(/mitmachen/\S+)", text)
    pruefe(link is not None, "die Mail hat den Link zum Bestätigen")
    link = link.group(1) if link else "/mitmachen/x"
    pruefe(db.stamm_zaehlen()["stamm"] == 0, "unbestätigt erreicht sie keine Einladung")

    status, _, seite, _ = anfrage("GET", link)
    pruefe(status == 200 and "bist du in unserem Helferstamm, und wir schreiben dir" in seite
           and helfer("lena@example.org")["stamm_einwilligung_am"] is None,
           "der Link zeigt nur den Knopf – Mailscanner lösen nichts aus")
    status, ort, _, _ = anfrage("POST", link)
    lena = helfer("lena@example.org")
    pruefe(status == 303 and "hinweis=dabei" in ort and lena["stamm_einwilligung_am"]
           and lena["email_bestaetigt_am"], "bestätigt: im Helferstamm")
    _, _, seite, _ = anfrage("GET", ort)
    pruefe("Danke – du bist in unserem Helferstamm." in seite
           and "Du bist in unserem Helferstamm. Sobald eine Veranstaltung geplant ist" in seite
           and "15 Minuten vor Beginn" not in seite, "Mein Helferplatz ohne Veranstaltung")
    status, _, _, _ = anfrage("GET", link.replace(f"/mitmachen/{LENA}.", f"/mitmachen/{LENA}.0"))
    pruefe(status == 404, "ein falscher Link führt ins Leere")

    melden("Lena", "Neu", "lena@example.org")
    pruefe(len(sql("SELECT id FROM helfer WHERE email = 'lena@example.org'")) == 1
           and LENA in mails("link"), "noch einmal gemeldet: kein zweiter Eintrag, ihr Link kommt")

    # Jörg war schon da, ohne Helferstamm, und hat einmal alles abbestellt.
    JOERG = db.helfer_von_hand({"name": "Jörg Müller", "email": "joerg@example.org"})[0]
    sql("UPDATE helfer SET aufrufe_abbestellt_am = '2026-01-01 10:00:00' WHERE id = ?", JOERG)
    melden("Joerg", "Mueller", "joerg@example.org")
    pruefe(helfer("joerg@example.org")["id"] == JOERG
           and len(sql("SELECT id FROM helfer WHERE email = 'joerg@example.org'")) == 1
           and JOERG in mails("mitmachen"), "andere Schreibweise, dieselbe Person – die Mail geht an sie")
    jlink = re.search(r"https://helfer\.example\.org(/mitmachen/\S+)",
                      mails("mitmachen")[JOERG]["body"]).group(1)
    anfrage("POST", jlink)
    joerg = db.helfer_laden(JOERG)
    pruefe(joerg["stamm_einwilligung_am"] and joerg["aufrufe_abbestellt_am"] is None,
           "mit der neuen Einwilligung bekommt er Einladungen wieder")

    melden("Tim", "Spaet", "tim@example.org")
    TIM = helfer("tim@example.org")["id"]

    print("Einladen")
    VA = db.VERANSTALTUNGEN.anlegen({"name": "Die absolute Abfahrt 2027", "kurz": "AA 2027",
                                     "beginn": "2027-07-01", "ende": "2027-07-04",
                                     "ort": "Ilmenau", "status": "offen"})
    db.angebot_setzen(VA, {"goodies": 1, "shirt": 1, "schnitte": 0, "verpflegung": 1, "party": 0})
    LEER = {"beschreibung": "", "treffpunkt": "Zelt", "voraussetzungen": "", "intern": 0}
    B = db.bereich_anlegen(VA, {**LEER, "name": "Strecke", "mindestalter": None})
    B16 = db.bereich_anlegen(VA, {**LEER, "name": "Shuttle", "mindestalter": 16})

    def schicht(bereich, tag, von, bis):
        return db.schicht_anlegen(VA, bereich, {
            "datum": tag, "beginn": f"{tag} {von}", "ende": f"{tag} {bis}", "minimum": 1,
            "soll": 9, "reserve": 0, "mindestalter": None, "ort": "", "hinweis": "", "intern": 0})

    S1 = schicht(B, "2027-07-02", "08:00", "12:00")
    S2 = schicht(B, "2027-07-03", "08:00", "12:00")
    S16 = schicht(B16, "2027-07-02", "14:00", "18:00")

    # Olaf war 2026 dabei: Größe, Essen und Alter kennen wir.
    ALT = db.VERANSTALTUNGEN.anlegen({"name": "Die absolute Abfahrt 2026", "kurz": "AA 2026",
                                      "beginn": "2026-07-01", "ende": "2026-07-04",
                                      "ort": "Ilmenau", "status": "archiviert"})
    OLAF = db.helfer_von_hand({"name": "Olaf Alt", "email": "olaf@example.org"})[0]
    sql("UPDATE helfer SET vorname = 'Olaf', stamm_einwilligung_am = '2026-07-01 10:00:00',"
        " tshirt = 'L', tshirt_roh = 'L', veggie = 0, volljaehrig = 1 WHERE id = ?", OLAF)
    db.einteilen(db.schicht_anlegen(ALT, db.bereich_anlegen(ALT, {**LEER, "name": "Strecke",
                                                                   "mindestalter": None}),
                                    {"datum": "2026-07-02", "beginn": "2026-07-02 08:00",
                                     "ende": "2026-07-02 12:00", "minimum": 1, "soll": 9,
                                     "reserve": 0, "mindestalter": None, "ort": "", "hinweis": "",
                                     "intern": 0}), OLAF)

    anfrage("POST", "/helfer/login", {"passwort": "test-passwort-123", "kuerzel": "KK",
                                      "weiter": "/helfer"}, mit_glas=True)
    _, _, seite, _ = anfrage("GET", "/helfer/einladen", mit_glas=True)
    csrf = re.search(r'name="csrf" value="([^"]+)"', seite).group(1)
    pruefe("Noch nicht eingeladen (3)" in seite and "Neue Helfer gewinnen" in seite
           and "https://helfer.example.org/mitmachen" in seite and "<svg" in seite,
           "Lena, Jörg und Olaf – dazu der Link und der Code für Flyer")
    pruefe(seite.count("marke-neu") == 2 and "Im Helferstamm: 3, davon 2 noch bei" in seite,
           "Lena und Jörg sind neu, Olaf war schon dabei")
    status, _, svg, art = anfrage("GET", "/helfer/einladen/mitmachen.svg", mit_glas=True)
    pruefe(status == 200 and art.startswith("image/svg+xml") and "<svg" in svg,
           "der Code zum Herunterladen")
    _, _, seite, _ = anfrage("GET", "/helfer/helfer", mit_glas=True)
    pruefe(seite.count("marke-neu") == 2, "auch in der Liste der Helfer markiert")
    _, _, seite, _ = anfrage("GET", f"/helfer/helfer/{LENA}", mit_glas=True)
    pruefe("<dt>Helferstamm</dt>" in seite and "über „Mitmachen“" in seite,
           "bei Lena steht, wie sie kam")

    anfrage("POST", "/helfer/einladen", {"csrf": csrf}, mit_glas=True)
    m = mails("einladung")
    pruefe(sorted(m) == sorted([LENA, JOERG, OLAF]), "alle drei eingeladen")
    lena_mail, olaf_mail = m.get(LENA, {"body": "", "betreff": ""}), m.get(OLAF, {"body": ""})
    pruefe("Du hast dich\nbei uns als Helfer gemeldet – jetzt geht es los." in lena_mail["body"]
           and lena_mail["betreff"].endswith("bist du dabei?")
           and "wieder dabei" in olaf_mail["body"], "Lena nicht „wieder“, Olaf schon")

    print("Schichtwahl: Lena")
    lena_link = re.search(r"https://helfer\.example\.org(/platz/\S+)/schichten",
                          lena_mail["body"]).group(1)
    status, _, seite, _ = anfrage("GET", lena_link + "/schichten")
    pruefe(status == 200 and f'value="{S1}"' in seite, "der Link führt zu den Schichten")
    status, _, seite, _ = anfrage("GET", f"{lena_link}/angaben?s={S1}")
    pruefe(status == 200 and f'name="m{LENA}-volljaehrig"' in seite
           and f'name="m{LENA}-tshirt"' in seite and f'name="m{LENA}-verpflegung"' in seite,
           "gefragt: Alter, Shirt, Essen")
    grund = {"s": str(S1), "wer": str(LENA), "weitere": "0", "aktion": "eintragen"}
    status, _, seite, _ = anfrage("POST", f"{lena_link}/angaben", grund)
    pruefe(status == 400 and "Bitte angeben." in seite and "Bitte eine Größe wählen" in seite
           and not sql("SELECT 1 FROM einteilung WHERE helfer_id = ?", LENA),
           "ohne Alter und Größe geht es nicht")
    status, ort, _, _ = anfrage("POST", f"{lena_link}/angaben", {
        **grund, f"m{LENA}-volljaehrig": "ja", f"m{LENA}-tshirt": "M",
        f"m{LENA}-verpflegung": "vegetarisch"})
    lena = db.helfer_laden(LENA)
    pruefe(status == 303 and "hinweis=dazu" in ort and lena["volljaehrig"] == 1
           and lena["tshirt"] == "M" and lena["veggie"] == 1
           and sql("SELECT 1 FROM einteilung WHERE helfer_id = ? AND schicht_id = ?", LENA, S1),
           "eingetragen – mit Alter, Größe und Essen")
    _, _, seite, _ = anfrage("GET", f"{lena_link}/angaben?s={S2}")
    pruefe(f'name="m{LENA}-volljaehrig"' not in seite
           and re.search(r'<option value="M"\s+selected>', seite),
           "beim nächsten Mal: kein Alter mehr, die Größe steht da")

    print("Schichtwahl: Olaf")
    olaf_link = re.search(r"https://helfer\.example\.org(/platz/\S+)/schichten",
                          olaf_mail["body"]).group(1)
    _, _, seite, _ = anfrage("GET", f"{olaf_link}/angaben?s={S1}")
    pruefe(f'name="m{OLAF}-volljaehrig"' not in seite
           and re.search(r'<option value="L"\s+selected>', seite)
           and re.search(r'<option value="fleisch"\s+selected>', seite),
           "Olaf sieht Größe und Essen, wie wir sie kennen – nach dem Alter fragt niemand")
    status, _, _, _ = anfrage("POST", f"{olaf_link}/angaben",
                              {"s": str(S1), "wer": str(OLAF), "aktion": "eintragen"})
    pruefe(status == 303 and db.helfer_laden(OLAF)["tshirt"] == "L",
           "ohne die Felder bleibt, was gespeichert ist")
    anfrage("POST", f"{olaf_link}/angaben", {"s": str(S2), "wer": str(OLAF), "aktion": "eintragen",
                                             f"m{OLAF}-tshirt": "XL"})
    pruefe(db.helfer_laden(OLAF)["tshirt"] == "XL", "eine neue Größe gilt ab jetzt")

    print("Schichtwahl: Mia ist 15")
    _, mia = db.mitmachen({"vorname": "Mia", "nachname": "Jung", "name": "Mia Jung",
                           "email": "mia@example.org", "telefon": ""})
    db.stamm_beitreten(mia["id"])
    MIA = mia["id"]
    mia_link = f"/platz/{zugang.token(zugang.PLATZ, db.helfer_laden(MIA))}/aa-2027"
    jung = {"wer": str(MIA), "aktion": "eintragen", f"m{MIA}-volljaehrig": "nein",
            f"m{MIA}-geburtsdatum": "2012-05-01", f"m{MIA}-eltern_name": "Maria Jung",
            f"m{MIA}-eltern_email": "maria@example.org", f"m{MIA}-tshirt": "S",
            f"m{MIA}-verpflegung": "fleisch"}
    status, _, seite, _ = anfrage("POST", f"{mia_link}/angaben", {**jung, "s": str(S16)})
    pruefe(status == 409 and "erst ab 16" in seite, "der Shuttle ist erst ab 16")
    mia = db.helfer_laden(MIA)
    pruefe(mia["geburtsdatum"] == "2012-05-01" and mia["eltern_email"] == "maria@example.org"
           and f'name="m{MIA}-volljaehrig"' not in seite,
           "das Alter ist trotzdem gespeichert – und wird nicht noch einmal gefragt")
    status, _, _, _ = anfrage("POST", f"{mia_link}/angaben",
                              {"s": str(S1), "wer": str(MIA), "aktion": "eintragen"})
    pruefe(status == 303 and MIA in mails("eltern"),
           "an der Strecke geht es – und die Eltern bekommen ihre Mail")

    print("Mit Veranstaltung")
    _, ort, _, _ = anfrage("GET", "/")
    _, _, seite, _ = anfrage("GET", ort)
    pruefe(ort == "/aa-2027" and 'href="/mitmachen"' in seite,
           "auch die Seite der Veranstaltung zeigt den Weg in den Helferstamm")
    _, _, seite, _ = anfrage("GET", "/datenschutz")
    pruefe("Mitmachen" in seite and re.search(r"drei\s+Jahre nach deiner Einwilligung", seite),
           "der Datenschutzhinweis nennt es")
finally:
    prozess.terminate()
    try:
        prozess.wait(timeout=10)
    except subprocess.TimeoutExpired:
        prozess.kill()

print("Nicht bestätigt")
config.JETZT_FEST = "2027-03-03 10:00"
versand.fristen()
pruefe(db.helfer_laden(TIM) is not None, "vor Ablauf der Frist bleibt Tim")
config.JETZT_FEST = "2027-03-05 10:00"
versand.fristen()
pruefe(db.helfer_laden(TIM) is None and db.helfer_laden(LENA) is not None
       and db.helfer_laden(JOERG) is not None,
       "danach ist er weg – wer bestätigt hat oder schon da war, bleibt")

print()
if fehler:
    print("FEHLGESCHLAGEN (" + str(len(fehler)) + "):")
    for eintrag in fehler:
        print("  - " + eintrag)
else:
    print("alle Pruefungen bestanden")
sys.exit(1 if fehler else 0)
