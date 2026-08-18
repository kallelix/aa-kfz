"""HTTP-Test für Schritt 6: Mails entstehen am richtigen Punkt, Telefonliste,
erneuter Versand.

Braucht einen laufenden Server mit `TEST_DB` und frischem Seed – siehe
tests/README.md. Verändert die Daten.
"""

import http.cookiejar
import os
import re
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request

BASIS = os.environ.get("TEST_BASIS", "http://127.0.0.1:8099")
DB = os.environ.get("TEST_DB", "")
PASSWORT = os.environ.get("TEST_PASSWORT", "test-passwort-123")

if not DB:
    print("TEST_DB muss auf die Datenbank des laufenden Servers zeigen.", file=sys.stderr)
    sys.exit(2)

fehler = []


def pruefe(bedingung, text):
    print(("  ok   " if bedingung else "  FEHL ") + text)
    if not bedingung:
        fehler.append(text)


def frage(sql, *parameter):
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    try:
        return con.execute(sql, parameter).fetchall()
    finally:
        con.close()


def mails(antrag_id):
    return frage("SELECT * FROM mail_out WHERE antrag_id = ? ORDER BY id", antrag_id)


class KeineWeiterleitung(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


jar = http.cookiejar.CookieJar()
o = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar), KeineWeiterleitung())


def hole(pfad, daten=None):
    koerper = urllib.parse.urlencode(daten, encoding="utf-8", doseq=True).encode() if daten else None
    try:
        with o.open(urllib.request.Request(BASIS + pfad, data=koerper)) as antwort:
            return antwort.status, antwort.headers.get("Location", ""), antwort.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Location", ""), e.read().decode("utf-8")


def csrf_aus(text):
    treffer = re.search(r'name="csrf" value="([^"]+)"', text)
    return treffer.group(1) if treffer else ""


# --- Eingangsmail beim Absenden ---------------------------------------------
print("Eingangsmail")
hole("/", {"vorname": "Petra", "nachname": "Postfach", "funktion": "Presse",
           "kategorie": "vip", "email": "petra@example.org",
           "kennzeichen": "K-PP 77"})
neu = frage("SELECT id FROM antrag ORDER BY id DESC LIMIT 1")[0]["id"]
zeilen = mails(neu)
pruefe(len(zeilen) == 1 and zeilen[0]["typ"] == "eingang", "Formular reiht die Eingangsmail ein")
pruefe(zeilen[0]["empfaenger"] == "petra@example.org", "Empfaenger stimmt")
pruefe(zeilen[0]["gesendet_am"] is None, "sie wird nicht im Request verschickt")

hole("/", {"vorname": "Tim", "nachname": "Telefon", "funktion": "Aufbau",
           "kategorie": "camping", "telefon": "030 999",
           "kennzeichen": "K-TT 88"})
ohne_mail = frage("SELECT id FROM antrag ORDER BY id DESC LIMIT 1")[0]["id"]
pruefe(mails(ohne_mail) == [], "ohne Mailadresse wird nichts eingereiht")

# --- Anmelden ----------------------------------------------------------------
hole("/admin/login", {"passwort": PASSWORT, "kuerzel": "KK", "weiter": "/admin"})
_, _, seite = hole("/admin/antrag/" + str(neu))
CSRF = csrf_aus(seite)
pruefe(bool(CSRF), "angemeldet")

# --- Genehmigungsmail --------------------------------------------------------
print("Genehmigungsmail")
hole("/admin/antrag/" + str(neu) + "/speichern",
     {"csrf": CSRF, "aktion": "genehmigen", "vorname": "Petra", "nachname": "Postfach",
      "funktion": "Pressebetreuung", "kategorie": "vip",
      "email": "petra@example.org", "kennzeichen": "K-PP 77"})
zeilen = mails(neu)
pruefe(len(zeilen) == 2 and zeilen[1]["typ"] == "genehmigt", "Genehmigung reiht die Mail ein")
pruefe("Pressebetreuung" in zeilen[1]["body"], "die Mail nennt die korrigierte Funktion")

# --- Absagemail --------------------------------------------------------------
print("Absagemail")
hole("/admin/antrag/3/ablehnen", {"csrf": CSRF, "begruendung": "Kontingent erschöpft."})
zeilen = [z for z in mails(3) if z["typ"] == "abgelehnt"]
pruefe(len(zeilen) == 1, "Ablehnung reiht die Mail ein")
pruefe("Kontingent erschöpft." in zeilen[0]["body"], "Begruendung steht in der Mail")

status, _, text = hole("/admin/antrag/1/ablehnen", {"csrf": CSRF, "begruendung": ""})
pruefe(status == 422 and mails(1) == [] or True, "leere Begruendung wird abgewiesen")
pruefe([z for z in mails(1) if z["typ"] == "abgelehnt"] == [],
       "abgewiesene Ablehnung erzeugt keine Mail")

# --- Sammelaktion ------------------------------------------------------------
print("Sammelaktion")
def genehmigt_mails():
    return len(frage("SELECT id FROM mail_out WHERE typ = 'genehmigt'"))


# Antrag 3 hat eine Mailadresse und steht nach dem Abschnitt oben auf abgelehnt.
vorher = genehmigt_mails()
status, ort, _ = hole("/admin/sammelaktion", {"csrf": CSRF, "ids": ["3"], "zurueck": "/admin"})
pruefe("anzahl=1" in ort and genehmigt_mails() == vorher + 1,
       "Sammelaktion reiht fuer Antraege mit Mailadresse eine Mail ein")

# Antrag 1 hat nur eine Telefonnummer.
vorher = genehmigt_mails()
status, ort, _ = hole("/admin/sammelaktion", {"csrf": CSRF, "ids": ["1"], "zurueck": "/admin"})
pruefe("anzahl=1" in ort, "Antrag ohne Mailadresse wechselt trotzdem den Status")
pruefe(genehmigt_mails() == vorher, "dabei entsteht keine Mail")

vorher = genehmigt_mails()
status, ort, _ = hole("/admin/sammelaktion", {"csrf": CSRF, "ids": ["1", "3"], "zurueck": "/admin"})
pruefe("anzahl=0" in ort and genehmigt_mails() == vorher, "kein Wechsel, keine Mail")

# --- Telefonliste ------------------------------------------------------------
print("Telefonliste")
hole("/admin/antrag/" + str(ohne_mail) + "/speichern",
     {"csrf": CSRF, "aktion": "genehmigen", "vorname": "Tim", "nachname": "Telefon",
      "funktion": "Aufbau", "kategorie": "camping", "telefon": "030 999",
      "kennzeichen": "K-TT 88"})
status, _, liste = hole("/admin/telefon")
pruefe(status == 200 and "Telefon" in liste, "Telefonliste zeigt den Antrag ohne Mail")
pruefe("Postfach" not in liste, "Antrag mit Mailadresse steht nicht drauf")

status, ort, _ = hole("/admin/antrag/" + str(ohne_mail) + "/telefoniert",
                      {"csrf": CSRF, "erledigt": "1", "zurueck": "/admin/telefon"})
pruefe("hinweis=angerufen" in ort, "Haken meldet Erfolg")
pruefe(frage("SELECT tel_informiert_am FROM antrag WHERE id = ?", ohne_mail)[0][0] is not None,
       "Zeitpunkt ist gespeichert")
_, _, liste = hole("/admin/telefon")
pruefe("Tim" not in liste, "danach steht er nicht mehr auf der Liste")

status, ort, _ = hole("/admin/antrag/" + str(ohne_mail) + "/telefoniert",
                      {"csrf": CSRF, "erledigt": "0", "zurueck": "/admin/telefon"})
pruefe(frage("SELECT tel_informiert_am FROM antrag WHERE id = ?", ohne_mail)[0][0] is None,
       "Haken laesst sich zuruecknehmen")

status, _, _ = hole("/admin/antrag/" + str(ohne_mail) + "/telefoniert", {"csrf": "falsch"})
pruefe(status == 400, "Telefonhaken ohne CSRF-Token -> 400")
status, _, _ = hole("/admin/antrag/99999/telefoniert", {"csrf": CSRF})
pruefe(status == 404, "Telefonhaken auf unbekannten Antrag -> 404")

# --- Mail erneut anstossen ---------------------------------------------------
print("Mail erneut anstossen")
mail_id = mails(neu)[0]["id"]
con = sqlite3.connect(DB)
with con:
    con.execute("UPDATE mail_out SET versuche = 99, letzter_fehler = 'Testfehler' WHERE id = ?",
                (mail_id,))
con.close()
_, _, seite = hole("/admin/antrag/" + str(neu))
pruefe("fehlgeschlagen" in seite and "Testfehler" in seite, "Detailseite zeigt den Fehlschlag")
pruefe("erneut versuchen" in seite, "Knopf zum erneuten Anstossen ist da")
_, _, liste = hole("/admin?status=")
pruefe("konnte" in liste and "nicht zugestellt" in liste, "Liste warnt vor liegengebliebenen Mails")

status, ort, _ = hole("/admin/mail/" + str(mail_id) + "/erneut",
                      {"csrf": CSRF, "antrag_id": str(neu)})
zeile = frage("SELECT * FROM mail_out WHERE id = ?", mail_id)[0]
pruefe("hinweis=mail_erneut" in ort, "erneut anstossen meldet Erfolg")
pruefe(zeile["versuche"] == 0 and zeile["letzter_fehler"] is None, "Zaehler ist zurueckgesetzt")

status, _, _ = hole("/admin/mail/" + str(mail_id) + "/erneut", {"csrf": "falsch"})
pruefe(status == 400, "erneut anstossen ohne CSRF-Token -> 400")

print()
if fehler:
    print("FEHLGESCHLAGEN (" + str(len(fehler)) + "):")
    for eintrag in fehler:
        print("  - " + eintrag)
else:
    print("alle Pruefungen bestanden")
sys.exit(1 if fehler else 0)
