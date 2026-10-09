"""Einsatzgrenzen (Lastenheft 2.3, K-05 bis K-09).

    python helfer/tests/test_grenzen.py

Setzen und aufheben im Backoffice, still wirken in der öffentlichen
Anmeldung – mit denselben Worten wie bei einer vollen Schicht –, der Hinweis
„nur zu zweit“ für Orga und Bereichsleitung, nicht auf dem Monitor; wer
Grenzen sieht und wer nicht; Einteilen trotz Grenze nur mit Vermerk; die
Vorlage aus dem Vorjahr nimmt die Grenzen auf ganze Bereiche mit.
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


db_url = testdb.wegwerf("helfer_grenzen")
os.environ["DATABASE_URL"] = db_url

from app import db  # noqa: E402

db.init()
VA = db.VERANSTALTUNGEN.anlegen({"name": "Die absolute Abfahrt 2027", "kurz": "AA 2027",
                                 "beginn": "2027-07-01", "ende": "2027-07-04",
                                 "ort": "Ilmenau", "status": "offen"})
db.angebot_setzen(VA, {"goodies": 0, "shirt": 0, "schnitte": 0, "verpflegung": 0, "party": 0})
LEER = {"beschreibung": "", "treffpunkt": "", "mindestalter": None, "voraussetzungen": "",
        "intern": 0}
SHUTTLE = db.bereich_anlegen(VA, {**LEER, "name": "Shuttle"})
STRECKE = db.bereich_anlegen(VA, {**LEER, "name": "Streckenposten"})


def schicht(bereich, tag, von, bis, soll):
    return db.schicht_anlegen(VA, bereich, {
        "datum": tag, "beginn": f"{tag} {von}", "ende": f"{tag} {bis}", "minimum": 1,
        "soll": soll, "reserve": 0, "mindestalter": None, "ort": "", "hinweis": "",
        "intern": 0})


FRUEH = schicht(SHUTTLE, "2027-07-02", "07:00", "12:00", 2)
MITTAG = schicht(SHUTTLE, "2027-07-02", "13:00", "17:00", 2)
POSTEN = schicht(STRECKE, "2027-07-03", "08:00", "13:00", 3)
VOLL = schicht(STRECKE, "2027-07-03", "14:00", "18:00", 1)
POSTEN_SO = schicht(STRECKE, "2027-07-04", "08:00", "13:00", 2)

# Ada ist Orga mit allen Rechten, Kalle leitet die Strecke, Lea liest nur.
KONTEN = Konten(lambda: db_url)
KONTEN.anlegen(email="ada@example.org", name="Ada Admin", kuerzel="AD", rolle="admin",
               passwort="ein-langes-passwort")
KALLE = KONTEN.anlegen(email="kalle@example.org", name="Kalle Beispiel", kuerzel="KB",
                       rolle="bereichsleitung", passwort="kalles-langes-passwort")
KONTEN.anlegen(email="lea@example.org", name="Lea Lesend", kuerzel="LL", rolle="lesend",
               bereiche=["helfer"], passwort="leas-langes-passwort")
db.leitung_setzen(STRECKE, [KALLE])
TOKEN = db.monitor_token(anlegen=True)

hafen = freier_hafen()
prozess = subprocess.Popen(
    [str(PYTHON), "-m", "app"], cwd=str(WURZEL),
    env={**os.environ, "DATABASE_URL": db_url, "BIND": f"127.0.0.1:{hafen}",
         "ADMIN_PASSWORD_HASH": HASH, "APP_SECRET_KEY": "test-schluessel",
         "COOKIE_SECURE": "0", "ZEITPLAN_SERIEN": "", "JETZT_FEST": "2027-06-01 10:00",
         "PYTHONIOENCODING": "utf-8"},
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

    def melde_an(vorname, email, schichten, weitere=()):
        daten = [("s", s) for s in schichten]
        daten += [("ich-vorname", vorname), ("ich-nachname", "Berg"), ("ich-email", email),
                  ("ich-volljaehrig", "ja"), ("weitere", len(weitere)), ("aktion", "anmelden")]
        for i, w in enumerate(weitere):
            daten += [(f"p{i}-vorname", w), (f"p{i}-nachname", "Berg"),
                      (f"p{i}-volljaehrig", "ja")]
        return anfrage("POST", "/aa-2027/angaben", daten)

    def gruende(seite):
        return re.findall(r"<li>(.*?)</li>", seite)

    def anmelden_als(email, passwort):
        glas = {}
        anfrage("POST", "/helfer/login", {"email": email, "passwort": passwort,
                                          "weiter": "/helfer"}, glas)
        anfrage("GET", "/helfer/veranstaltung?id=%d" % VA, glas=glas)
        return glas

    def csrf(glas, pfad="/helfer/schichten"):
        return re.search(r'name="csrf" value="([^"]+)"', anfrage("GET", pfad, glas=glas)[2]).group(1)

    print("Vorher: Anna und Bert melden sich an")
    status, ort, _ = melde_an("Anna", "anna@example.org", [POSTEN])
    pruefe(status == 303, "Anna steht am Posten")
    ANNA = int(re.search(r"p=(\d+)", ort).group(1))
    status, _, _ = melde_an("Bert", "bert@example.org", [VOLL])
    pruefe(status == 303, "Bert nimmt den letzten Platz am Nachmittag")

    print("Setzen (K-05)")
    ada = anmelden_als("ada@example.org", "ein-langes-passwort")
    ACSRF = csrf(ada)
    status, _, seite = anfrage("GET", "/helfer/helfer/%d" % ANNA, glas=ada)
    pruefe(status == 200 and "Einsatzgrenzen" in seite and "Keine." in seite,
           "die Helferseite hat einen Abschnitt, noch leer")
    pruefe('<optgroup label="Shuttle">' in seite and 'value="b%d"' % SHUTTLE in seite
           and 'value="s%d"' % FRUEH in seite, "zur Wahl: ganze Bereiche und einzelne Schichten")
    pruefe("Grund" in seite and "Diagnose" in seite and "bemerkung" not in seite.split("Einsatzgrenzen")[1],
           "das Formular sagt, dass kein Grund hineingehört, und hat kein Feld dafür (K-08)")

    def setzen(ziel, art, glas=ada, token=None):
        return anfrage("POST", "/helfer/helfer/%d/grenze" % ANNA,
                       {"csrf": token or ACSRF, "ziel": ziel, "art": art}, glas)

    status, ort, _ = setzen("b%d" % SHUTTLE, "nicht_anbieten")
    pruefe(status == 303 and "hinweis=grenze-gesetzt" in ort, "Shuttle nicht anbieten")
    pruefe(zeilen("SELECT bereich_id, schicht_id, art, angelegt_von FROM einsatzgrenze")
           == [(SHUTTLE, None, "nicht_anbieten", "AD")], "gespeichert, mit Kürzel")
    pruefe(zeilen("SELECT wer, was FROM protokoll WHERE helfer_id = ?", ANNA)
           == [("AD", "Einsatzgrenze gesetzt: Shuttle – nicht anbieten")],
           "und im Protokoll (K-08)")
    _, ort, _ = setzen("s%d" % FRUEH, "nur_zu_zweit")
    pruefe("hinweis=zweit-nur-bereich" in ort, "„nur zu zweit“ nicht für eine einzelne Schicht")
    _, ort, _ = setzen("b99999", "nicht_anbieten")
    pruefe("hinweis=grenze-ziel" in ort, "ein Bereich, den es nicht gibt, geht nicht")
    _, ort, _ = setzen("b%d" % SHUTTLE, "quatsch")
    pruefe("hinweis=grenze-ziel" in ort, "eine Art, die es nicht gibt, auch nicht")
    status, _, _ = anfrage("POST", "/helfer/helfer/%d/grenze" % ANNA,
                           {"ziel": "b%d" % SHUTTLE, "art": "nicht_anbieten"}, ada)
    pruefe(status == 400, "ohne CSRF-Token nichts")
    setzen("s%d" % POSTEN_SO, "nicht_anbieten")
    setzen("b%d" % STRECKE, "nur_zu_zweit")
    setzen("b%d" % SHUTTLE, "nicht_anbieten")
    pruefe(zeilen("SELECT COUNT(*) FROM einsatzgrenze WHERE helfer_id = ?", ANNA) == [(3,)],
           "dasselbe Ziel zweimal ersetzt, statt zu verdoppeln")
    pruefe(zeilen("SELECT COUNT(*) FROM protokoll WHERE was LIKE '%Shuttle – nicht anbieten'")
           == [(1,)], "dieselbe Grenze noch einmal steht nicht doppelt im Protokoll")
    setzen("b%d" % STRECKE, "nicht_anbieten")
    setzen("b%d" % STRECKE, "nur_zu_zweit")
    pruefe(zeilen("SELECT art FROM einsatzgrenze WHERE bereich_id = ?", STRECKE)
           == [("nur_zu_zweit",)] and zeilen(
               "SELECT COUNT(*) FROM protokoll WHERE was LIKE '%Streckenposten – %'") == [(3,)],
           "eine andere Art auf demselben Ziel ersetzt die alte, mit Protokoll")
    _, _, seite = anfrage("GET", "/helfer/helfer/%d" % ANNA, glas=ada)
    pruefe("Shuttle – nicht anbieten" in seite and "Streckenposten – nur zu zweit einplanen" in seite
           and "Streckenposten So 04.07. 08:00–13:00 – nicht anbieten" in seite,
           "die Seite zeigt die Grenzen so, dass die Person sie lesen könnte")
    pruefe("Verlauf" in seite and "aufheben" in seite, "mit Verlauf und zum Aufheben")

    print("Still in der Anmeldung (K-06)")
    status, _, seite = melde_an("Anna", "anna@example.org", [FRUEH])
    anna_text = gruende(seite)
    status_voll, _, seite_voll = melde_an("Cleo", "cleo@example.org", [VOLL])
    voll_text = gruende(seite_voll)
    pruefe(status == 409 and status_voll == 409, "weder Anna beim Shuttle noch Cleo in der vollen Schicht")
    pruefe(len(anna_text) == 1 and len(voll_text) == 1
           and anna_text[0].replace("Shuttle Fr 02.07. 07:00–12:00", "X")
           == voll_text[0].replace("Streckenposten Sa 03.07. 14:00–18:00", "X"),
           "Anna bekommt wortgleich dieselbe Antwort wie bei einer vollen Schicht: "
           + (anna_text[0] if anna_text else "–"))
    pruefe("Grenze" not in seite and "Einsatz" not in seite, "kein Wort von einer Grenze")
    status, _, seite = melde_an("Anna", "anna@example.org", [POSTEN_SO])
    pruefe(status == 409 and "gerade nicht frei" in seite, "auch nicht die eine gesperrte Schicht")
    status, _, seite = melde_an("Anna", "anna@example.org", [MITTAG], weitere=["Fritz"])
    pruefe(status == 409 and "gerade nicht für alle 2 Platz" in seite,
           "mit einer Mitanmeldung klingt es wie eine knappe Schicht")
    status, _, _ = melde_an("Bert", "bert@example.org", [FRUEH])
    pruefe(status == 303, "Bert kommt in dieselbe Schicht – die Grenze gilt nur Anna")
    _, _, seite = anfrage("GET", "/aa-2027/schichten")
    pruefe('name="s" value="%d"' % MITTAG in seite, "die öffentliche Liste bleibt für alle gleich")

    print("Nur zu zweit (K-07)")
    _, _, seite = anfrage("GET", "/helfer", glas=ada)
    pruefe("Bitte eine zweite Person dazu planen" in seite
           and 'href="/helfer/schicht/%d"' % POSTEN in seite and "Anna Berg" in seite,
           "die Übersicht nennt Anna allein am Posten")
    pruefe("nur zu zweit" not in seite, "ohne Begründung, ohne die Grenze zu nennen")
    _, _, seite = anfrage("GET", "/helfer/schicht/%d" % POSTEN, glas=ada)
    pruefe("Bitte eine zweite Person dazu planen" in seite, "auch auf der Schicht selbst")
    kalle = anmelden_als("kalle@example.org", "kalles-langes-passwort")
    _, _, seite = anfrage("GET", "/helfer/bereiche", glas=kalle)
    pruefe("Bitte eine zweite Person dazu planen" in seite
           and 'href="/helfer/schicht/%d"' % POSTEN in seite,
           "die Bereichsleitung sieht es in ihren Bereichen")
    lea = anmelden_als("lea@example.org", "leas-langes-passwort")
    _, _, seite = anfrage("GET", "/helfer", glas=lea)
    pruefe("zweite Person" not in seite, "wer nur liest, sieht den Hinweis nicht")
    for pfad in ("/monitor/" + TOKEN, "/monitor/" + TOKEN + "/inhalt",
                 "/monitor/" + TOKEN + "/inhalt?tag=2027-07-03"):
        status, _, seite = anfrage("GET", pfad)
        pruefe(status == 200 and "zweite Person" not in seite and "Grenze" not in seite,
               "nichts auf dem Monitor: " + pfad.replace(TOKEN, "…"))
    status, _, _ = melde_an("Dora", "dora@example.org", [POSTEN])
    _, _, seite = anfrage("GET", "/helfer", glas=ada)
    pruefe(status == 303 and "zweite Person" not in seite, "steht Dora dabei, ist der Hinweis weg")

    print("Wer Grenzen sieht (K-08)")
    _, _, seite = anfrage("GET", "/helfer/helfer/%d" % ANNA, glas=kalle)
    pruefe("Streckenposten – nur zu zweit einplanen" in seite
           and "Streckenposten So 04.07." in seite and "Shuttle" not in seite,
           "die Bereichsleitung sieht nur die Grenzen in ihren Bereichen")
    pruefe('/grenze"' not in seite and "aufheben" not in seite and "Verlauf" not in seite,
           "und pflegt sie nicht, ohne Verlauf")
    KCSRF = csrf(kalle)
    status, _, seite = setzen("b%d" % STRECKE, "nicht_anbieten", glas=kalle, token=KCSRF)
    pruefe(status == 403, "Setzen bleibt ihr verschlossen")
    grenze_strecke = zeilen("SELECT id FROM einsatzgrenze WHERE bereich_id = ?", STRECKE)[0][0]
    status, _, _ = anfrage("POST", "/helfer/grenze/%d/aufheben" % grenze_strecke,
                           {"csrf": KCSRF}, kalle)
    pruefe(status == 403, "Aufheben auch")
    status, _, seite = anfrage("GET", "/helfer/helfer/%d" % ANNA, glas=lea)
    pruefe(status == 200 and "Einsatzgrenzen" not in seite and "nicht anbieten" not in seite,
           "wer nur liest, sieht keine Grenzen")
    status, _, _ = setzen("b%d" % SHUTTLE, "nur_zu_zweit", glas=lea, token=csrf(lea))
    pruefe(status == 403, "und setzt keine")
    status, _, csv = anfrage("GET", "/helfer/helfer/export.csv", glas=ada)
    pruefe(status == 200 and "Anna" in csv and "anbieten" not in csv and "zweit" not in csv,
           "nicht in der CSV-Ausfuhr")

    print("Trotzdem einteilen (K-09)")
    status, ort, _ = anfrage("POST", "/helfer/schicht/%d/einteilen" % MITTAG,
                             {"csrf": ACSRF, "helfer_id": ANNA}, ada)
    pruefe(status == 303 and "hinweis=grenze" in ort and "bestaetigen=%d" % ANNA in ort,
           "erst eine Rückfrage")
    pruefe(zeilen("SELECT COUNT(*) FROM einteilung WHERE schicht_id = ? AND helfer_id = ?",
                  MITTAG, ANNA) == [(0,)], "noch nicht eingeteilt")
    _, _, seite = anfrage("GET", ort, glas=ada)
    pruefe("Trotzdem einteilen" in seite and 'name="vermerk"' in seite,
           "die Schicht fragt nach einem Vermerk")
    _, ort, _ = anfrage("POST", "/helfer/schicht/%d/einteilen" % MITTAG,
                        {"csrf": ACSRF, "helfer_id": ANNA, "trotzdem": "1", "vermerk": "  "}, ada)
    pruefe("hinweis=vermerk-fehlt" in ort, "ohne Vermerk nicht")
    _, ort, _ = anfrage("POST", "/helfer/schicht/%d/einteilen" % MITTAG,
                        {"csrf": ACSRF, "helfer_id": ANNA, "trotzdem": "1",
                         "vermerk": "abgesprochen, diesmal zu zweit"}, ada)
    pruefe("hinweis=eingeteilt" in ort and zeilen(
        "SELECT vermerk FROM einteilung WHERE schicht_id = ? AND helfer_id = ?", MITTAG, ANNA)
        == [("abgesprochen, diesmal zu zweit",)], "mit Vermerk geht es")
    pruefe(zeilen("SELECT was FROM protokoll WHERE helfer_id = ? ORDER BY id DESC LIMIT 1", ANNA)
           == [("Trotz Einsatzgrenze eingeteilt: Shuttle Fr 02.07. 13:00–17:00 – "
                "abgesprochen, diesmal zu zweit",)], "und es steht im Protokoll")
    _, _, seite = anfrage("GET", "/helfer/schicht/%d" % MITTAG, glas=ada)
    pruefe("mit Vermerk" in seite, "die Schicht zeigt den Vermerk")
    _, _, seite = anfrage("GET", "/helfer/schicht/%d?bestaetigen=%d" % (MITTAG, ANNA), glas=lea)
    pruefe("mit Vermerk" not in seite and "Trotzdem einteilen" not in seite,
           "wer nur liest, sieht weder Vermerk noch Rückfrage")
    status, ort, _ = anfrage("POST", "/helfer/schicht/%d/einteilen" % POSTEN_SO,
                             {"csrf": KCSRF, "helfer_id": ANNA, "trotzdem": "1",
                              "vermerk": "geht schon"}, kalle)
    pruefe("hinweis=grenze-orga" in ort and zeilen(
        "SELECT COUNT(*) FROM einteilung WHERE schicht_id = ? AND helfer_id = ?",
        POSTEN_SO, ANNA) == [(0,)], "die Bereichsleitung übersteuert nicht")
    status, ort, _ = anfrage("POST", "/helfer/schicht/%d/einteilen" % VOLL,
                             {"csrf": KCSRF, "helfer_id": ANNA}, kalle)
    pruefe("hinweis=eingeteilt" in ort, "ohne Grenze teilt sie ganz normal ein")

    print("Aufheben")
    grenze_shuttle = zeilen("SELECT id FROM einsatzgrenze WHERE bereich_id = ?", SHUTTLE)[0][0]
    status, ort, _ = anfrage("POST", "/helfer/grenze/%d/aufheben" % grenze_shuttle,
                             {"csrf": ACSRF}, ada)
    pruefe(status == 303 and "hinweis=grenze-aufgehoben" in ort
           and zeilen("SELECT COUNT(*) FROM einsatzgrenze WHERE bereich_id = ?", SHUTTLE) == [(0,)],
           "die Grenze ist weg")
    pruefe(("AD", "Einsatzgrenze aufgehoben: Shuttle – nicht anbieten") in zeilen(
        "SELECT wer, was FROM protokoll WHERE helfer_id = ?", ANNA), "das steht im Protokoll")
    status, _, _ = melde_an("Anna", "anna@example.org", [FRUEH])
    pruefe(status == 303, "danach kommt Anna in den Shuttle")
    status, ort, _ = anfrage("POST", "/helfer/grenze/99999/aufheben", {"csrf": ACSRF}, ada)
    pruefe("hinweis=unbekannt" in ort, "eine Grenze, die es nicht gibt, meldet sich")

    print("Vorlage fürs nächste Jahr")
    NEU = db.VERANSTALTUNGEN.anlegen({"name": "Die absolute Abfahrt 2028", "kurz": "AA 2028",
                                      "beginn": "2028-07-06", "ende": "2028-07-09",
                                      "ort": "Ilmenau"})
    ergebnis = db.vorlage_uebernehmen(NEU, VA, "AD")
    neue_strecke = zeilen("SELECT id FROM bereich WHERE veranstaltung_id = ? AND name = ?",
                          NEU, "Streckenposten")[0][0]
    pruefe(ergebnis is not None and zeilen(
        "SELECT g.helfer_id, g.art FROM einsatzgrenze g JOIN bereich b ON b.id = g.bereich_id"
        " WHERE b.veranstaltung_id = ?", NEU) == [(ANNA, "nur_zu_zweit")],
        "die Grenze auf den ganzen Bereich kommt mit, die auf die Schicht nicht")
    pruefe(db.grenzen(NEU, ANNA)[0]["bereich_id"] == neue_strecke
           and len(db.grenzen(VA, ANNA)) == 2, "am neuen Bereich, der alte behält seine")
    pruefe(any(w == "AD" and "aus AA 2027 übernommen: Streckenposten" in was for w, was in zeilen(
        "SELECT wer, was FROM protokoll WHERE helfer_id = ?", ANNA)), "auch das im Protokoll")

    print("Geht die Person, gehen ihre Grenzen")
    testdb.abfrage(db_url, "helfer", "DELETE FROM einteilung WHERE helfer_id = %s" % ANNA)
    testdb.abfrage(db_url, "helfer", "DELETE FROM helfer WHERE id = %s" % ANNA)
    pruefe(zeilen("SELECT COUNT(*) FROM einsatzgrenze") == [(0,)]
           and zeilen("SELECT COUNT(*) FROM protokoll WHERE helfer_id = ?", ANNA) == [(0,)],
           "Grenzen und Protokoll sind mit gelöscht")
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
