"""Tests für Mailvorlagen, Queue-Logik und Worker-Backoff – ohne SMTP-Server.

    python tests/test_mail.py

Legt eine eigene Wegwerf-Datenbank an und fasst nichts anderes an.
"""

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

TEMP = Path(tempfile.mkdtemp(prefix="abfahrt-mailtest-"))
os.environ["DB_PATH"] = str(TEMP / "test.db")
os.environ["APP_SECRET_KEY"] = "test"
os.environ["MAIL_MAX_VERSUCHE"] = "3"
os.environ["KONTAKT_NAME"] = "Orga Absolute Abfahrt"
os.environ["KONTAKT_MAIL"] = "orga@example.org"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, db, mail, worker  # noqa: E402

fehler = []


def pruefe(bedingung, text):
    print(("  ok   " if bedingung else "  FEHL ") + text)
    if not bedingung:
        fehler.append(text)


db.init()


def antrag_anlegen(**abweichend):
    werte = {
        "vorname": "Max", "nachname": "Mustermann", "funktion": "Sanität",
        "kategorie": "camping", "email": "max@example.org", "telefon": "",
        "kennzeichen": "KA-XY 123", "bemerkung": "",
    }
    werte.update(abweichend)
    return db.antrag_anlegen(werte, None)


# --- Vorlagen ----------------------------------------------------------------
print("Vorlagen")
mit_mail = db.antrag_laden(antrag_anlegen())
ohne_mail = db.antrag_laden(antrag_anlegen(email="", telefon="0171 1234567"))

typ, empfaenger, betreff, body = mail.vorlage_eingang(mit_mail)
pruefe(typ == "eingang" and empfaenger == "max@example.org", "Eingangsmail geht an den Antragsteller")
pruefe(str(mit_mail["id"]) in betreff, "Antragsnummer steht im Betreff")
pruefe("Camping" in body, "Kategorie steht als Klartext in der Mail")
pruefe("KA-XY 123" in body, "Kennzeichen steht in der Mail")
pruefe("Orga Absolute Abfahrt" in body and "orga@example.org" in body, "Ansprechpartner steht drunter")
pruefe("<" not in body.replace("<", "", 0) or "<html" not in body.lower(), "reiner Text, kein HTML")

_, _, _, body = mail.vorlage_genehmigt(mit_mail)
pruefe("genehmigt" in body, "Genehmigungsmail sagt, dass genehmigt wurde")
pruefe("rechtzeitig vorher" in body, "ohne ABHOLUNG wird kein Ort erfunden")
config.ABHOLUNG = "Karte am Freitag ab 16 Uhr am Orgazelt."
_, _, _, body = mail.vorlage_genehmigt(mit_mail)
pruefe("Orgazelt" in body, "gesetzte ABHOLUNG steht in der Mail")
config.ABHOLUNG = ""

_, _, _, body = mail.vorlage_abgelehnt(mit_mail, "Kontingent erschöpft.")
pruefe("Kontingent erschöpft." in body, "Begründung steht in der Absagemail")

pruefe(mail.fuer(ohne_mail, "eingang") is None, "ohne Mailadresse keine Vorlage")
pruefe(mail.fuer(mit_mail, "quatsch") is None, "unbekannter Typ liefert nichts")

# --- Einreihen ist an die Entscheidung gekoppelt ------------------------------
print("Einreihen")
a = antrag_anlegen()
db.mail_einreihen(a, mail.fuer(db.antrag_laden(a), "eingang"))
pruefe(len(db.mails_zu_antrag(a)) == 1, "Eingangsmail eingereiht")

erledigt = db.antrag_status_setzen(
    a, "genehmigt", "KK", mail=mail.fuer(db.antrag_laden(a), "genehmigt")
)
pruefe(erledigt and len(db.mails_zu_antrag(a)) == 2, "Genehmigung reiht die Mail mit ein")

# Unerlaubter Wechsel: weder Status noch Mail
vorher = len(db.mails_zu_antrag(a))
erledigt = db.antrag_status_setzen(
    a, "genehmigt", "KK", mail=mail.fuer(db.antrag_laden(a), "genehmigt")
)
pruefe(not erledigt and len(db.mails_zu_antrag(a)) == vorher,
       "abgewiesener Wechsel erzeugt keine Mail")

b = antrag_anlegen(email="", telefon="030 111")
db.antrag_status_setzen(b, "genehmigt", "KK", mail=mail.fuer(db.antrag_laden(b), "genehmigt"))
pruefe(db.antrag_laden(b)["status"] == "genehmigt", "Antrag ohne Mail wird trotzdem genehmigt")
pruefe(db.mails_zu_antrag(b) == [], "ohne Mailadresse wird nichts eingereiht")

# Sammelaktion
c, d = antrag_anlegen(), antrag_anlegen()
db.antrag_status_setzen(d, "ausgegeben", "KK")  # unerlaubt, bleibt neu
mails = {nr: mail.fuer(db.antrag_laden(nr), "genehmigt") for nr in (c, d)}
betroffen = db.sammel_genehmigen([c, d], "KK", mails)
pruefe(sorted(betroffen) == sorted([c, d]), "Sammelaktion meldet beide Nummern")
pruefe(len(db.mails_zu_antrag(c)) == 1 and len(db.mails_zu_antrag(d)) == 1,
       "Sammelaktion reiht je eine Mail ein")
pruefe(db.sammel_genehmigen([c], "KK", mails) == [], "schon genehmigt -> keine zweite Mail")
pruefe(len(db.mails_zu_antrag(c)) == 1, "wirklich keine zweite Mail")

# --- Faelligkeit und Backoff --------------------------------------------------
print("Faelligkeit und Backoff")
offen_vorher = len(db.mails_faellig())
pruefe(offen_vorher > 0, "es liegen faellige Mails an")

erste = db.mails_faellig()[0]
db.mail_fehlgeschlagen(erste["id"], "SMTPServerDisconnected: weg", worker._backoff(1))
danach = [z["id"] for z in db.mails_faellig()]
pruefe(erste["id"] not in danach, "Mail mit Backoff ist nicht mehr faellig")

db.mail_fehlgeschlagen(erste["id"], "wieder weg", None)
db.mail_fehlgeschlagen(erste["id"], "und nochmal", None)
zeile = [z for z in db.mails_zu_antrag(erste["antrag_id"]) if z["id"] == erste["id"]][0]
pruefe(zeile["versuche"] == 3, "Versuche werden hochgezaehlt: " + str(zeile["versuche"]))
pruefe(erste["id"] not in [z["id"] for z in db.mails_faellig()],
       "nach MAX_VERSUCHE nicht mehr faellig")
pruefe(db.mails_aufgegeben() >= 1, "aufgegebene Mail wird gezaehlt")

pruefe(db.mail_erneut(erste["id"]), "erneut anstossen meldet Erfolg")
pruefe(erste["id"] in [z["id"] for z in db.mails_faellig()], "danach wieder faellig")
zeile = [z for z in db.mails_zu_antrag(erste["antrag_id"]) if z["id"] == erste["id"]][0]
pruefe(zeile["versuche"] == 0 and zeile["letzter_fehler"] is None, "Zaehler und Fehler geraeumt")

db.mail_gesendet(erste["id"])
pruefe(erste["id"] not in [z["id"] for z in db.mails_faellig()], "gesendete Mail ist erledigt")
pruefe(not db.mail_erneut(erste["id"]), "gesendete Mail laesst sich nicht neu anstossen")

abstaende = [worker._backoff(n) for n in (1, 2, 3, 9)]
pruefe(abstaende == sorted(abstaende), "Backoff waechst monoton")

# --- Worker ohne SMTP ---------------------------------------------------------
print("Worker ohne SMTP")
config.MAIL_AKTIV = False
gesendet, misslungen = worker.runde()
pruefe(gesendet == 0 and misslungen > 0, "ohne SMTP schlaegt jeder Versuch fehl")
con = sqlite3.connect(config.DB_PATH)
uebrig = con.execute("SELECT COUNT(*) FROM mail_out WHERE gesendet_am IS NULL").fetchone()[0]
con.close()
pruefe(uebrig > 0, "die Mails bleiben liegen, nichts geht verloren")

# --- Worker mit vorgetaeuschtem Versand ---------------------------------------
print("Worker mit Versand")
config.MAIL_AKTIV = True
verschickt = []


def _merken(empfaenger, betreff, body):
    verschickt.append((empfaenger, betreff))


echt = mail.senden
mail.senden = _merken
# Alle liegengebliebenen zuruecksetzen – mails_faellig() liefert die
# aufgegebenen ja gerade nicht mehr.
con = sqlite3.connect(config.DB_PATH)
with con:
    con.execute(
        "UPDATE mail_out SET versuche = 0, naechster_versuch = NULL,"
        " letzter_fehler = NULL WHERE gesendet_am IS NULL"
    )
offen = con.execute("SELECT COUNT(*) FROM mail_out WHERE gesendet_am IS NULL").fetchone()[0]
con.close()
pruefe(offen > 0, "es liegen " + str(offen) + " Mails zum Verschicken bereit")
gesendet, misslungen = worker.runde()
mail.senden = echt
pruefe(gesendet == offen and misslungen == 0,
       "mit funktionierendem Versand gehen alle " + str(offen) + " raus: " + str(gesendet))
pruefe(len(verschickt) == gesendet, "jede Mail genau einmal verschickt")
pruefe(all("@" in e for e, _ in verschickt), "Empfaenger sehen nach Adressen aus")
pruefe(worker.runde() == (0, 0), "zweiter Durchgang schickt nichts doppelt")

# --- Telefonliste -------------------------------------------------------------
print("Telefonliste – nur Absagen")


def nummern_auf_liste():
    return [z["id"] for z in db.antraege_telefonisch()]


# Genehmigt und ohne Mailadresse: wird NICHT angerufen. Diese Leute stehen an
# der Strassensperre auf der Liste und bekommen den Aufkleber dort.
pruefe(b not in nummern_auf_liste(),
       "genehmigter Antrag ohne Mail steht nicht auf der Telefonliste")

# Abgelehnt und ohne Mailadresse: muss angerufen werden, sonst faehrt jemand
# umsonst hin.
abgelehnt_ohne_mail = antrag_anlegen(email="", telefon="030 222")
db.antrag_status_setzen(abgelehnt_ohne_mail, "abgelehnt", "KK", "Kein Platz mehr.")
pruefe(abgelehnt_ohne_mail in nummern_auf_liste(),
       "abgelehnter Antrag ohne Mail steht drauf")

neu_ohne_mail = antrag_anlegen(email="", telefon="030 333")
pruefe(neu_ohne_mail not in nummern_auf_liste(),
       "unentschiedener Antrag steht noch nicht drauf")

abgelehnt_mit_mail = antrag_anlegen()
db.antrag_status_setzen(abgelehnt_mit_mail, "abgelehnt", "KK", "Kein Platz mehr.")
pruefe(abgelehnt_mit_mail not in nummern_auf_liste(),
       "abgelehnter Antrag MIT Mailadresse steht nicht drauf – der bekommt eine Mail")

vorher = db.telefonisch_offen()
db.tel_informiert_setzen(abgelehnt_ohne_mail, True)
pruefe(db.telefonisch_offen() == vorher - 1, "Haken nimmt ihn von der Liste")
pruefe(db.antrag_laden(abgelehnt_ohne_mail)["tel_informiert_am"] is not None,
       "Zeitpunkt ist festgehalten")
db.tel_informiert_setzen(abgelehnt_ohne_mail, False)
pruefe(db.telefonisch_offen() == vorher, "Haken laesst sich zuruecknehmen")

# --- Migration ----------------------------------------------------------------
print("Migration einer alten Datenbank")
alt = TEMP / "alt.db"
con = sqlite3.connect(alt)
con.executescript(
    "CREATE TABLE antrag (id INTEGER PRIMARY KEY, vorname TEXT, nachname TEXT,"
    " funktion TEXT, kategorie TEXT, email TEXT, telefon TEXT, kennzeichen TEXT,"
    " bemerkung TEXT, status TEXT, entscheidung_am TEXT, entscheidung_durch TEXT,"
    " begruendung TEXT, tel_informiert_am TEXT, created_at TEXT, remote_ip TEXT);"
    "CREATE TABLE mail_out (id INTEGER PRIMARY KEY, antrag_id INTEGER, typ TEXT,"
    " empfaenger TEXT, betreff TEXT, body TEXT, versuche INTEGER DEFAULT 0,"
    " gesendet_am TEXT, letzter_fehler TEXT, created_at TEXT);"
)
con.commit()
con.close()
config.DB_PATH = alt
ergaenzt = db.init()
pruefe("mail_out.naechster_versuch" in ergaenzt, "fehlende Spalte wird nachgetragen: " + str(ergaenzt))
pruefe(db.init() == [], "zweiter Lauf traegt nichts mehr nach")
con = sqlite3.connect(alt)
spalten = {z[1] for z in con.execute("PRAGMA table_info(mail_out)")}
con.close()
pruefe("naechster_versuch" in spalten, "Spalte ist wirklich da")

print()
if fehler:
    print("FEHLGESCHLAGEN (" + str(len(fehler)) + "):")
    for eintrag in fehler:
        print("  - " + eintrag)
else:
    print("alle Pruefungen bestanden")
print("Wegwerf-Datenbanken lagen in " + str(TEMP))
sys.exit(1 if fehler else 0)
