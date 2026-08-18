"""HTTP-Test für den CSV-Export (Schritt 8).

Braucht einen laufenden Server mit `TEST_DB` und frischem Seed – siehe
tests/README.md. Legt zusätzliche Anträge an, verändert aber keine bestehenden.
"""

import csv
import http.cookiejar
import io
import os
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request

BASIS = os.environ.get("TEST_BASIS", "http://127.0.0.1:8099")
DB = os.environ.get("TEST_DB", "")
PASSWORT = os.environ.get("TEST_PASSWORT", "test-passwort-123")
TRENNER = os.environ.get("TEST_CSV_TRENNER", ";")

if not DB:
    print("TEST_DB muss auf die Datenbank des laufenden Servers zeigen.", file=sys.stderr)
    sys.exit(2)

fehler = []


def pruefe(bedingung, text):
    print(("  ok   " if bedingung else "  FEHL ") + text)
    if not bedingung:
        fehler.append(text)


class KeineWeiterleitung(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


jar = http.cookiejar.CookieJar()
o = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar), KeineWeiterleitung())


def hole(pfad, daten=None, roh=False):
    koerper = urllib.parse.urlencode(daten, encoding="utf-8", doseq=True).encode() if daten else None
    try:
        with o.open(urllib.request.Request(BASIS + pfad, data=koerper)) as antwort:
            inhalt = antwort.read()
            return antwort.status, antwort.headers, inhalt if roh else inhalt.decode("utf-8")
    except urllib.error.HTTPError as e:
        inhalt = e.read()
        return e.code, e.headers, inhalt if roh else inhalt.decode("utf-8")


def tabelle(text):
    return list(csv.reader(io.StringIO(text, newline=""), delimiter=TRENNER))


# --- Ohne Anmeldung ----------------------------------------------------------
print("Ohne Anmeldung")
status, kopf, _ = hole("/admin/export.csv")
pruefe(status == 303 and kopf.get("Location", "").startswith("/admin/login"),
       "Export ohne Anmeldung fuehrt zur Anmeldeseite")

hole("/admin/login", {"passwort": PASSWORT, "kuerzel": "KK", "weiter": "/admin"})

# Ein Antrag mit Zeichen, die CSV gern zerlegen.
hole("/", {"vorname": "Anna", "nachname": "Semikolon; Zeile",
           "funktion": 'Presse "Vor Ort"', "kategorie": "vip",
           "email": "anna@example.org", "kennzeichen": "B-AS 1",
           "bemerkung": "Zeile eins\nZeile zwei; mit Trenner"})
heikel = sqlite3.connect(DB).execute("SELECT MAX(id) FROM antrag").fetchone()[0]

# --- Grundform ---------------------------------------------------------------
print("Grundform")
status, kopf, rohdaten = hole("/admin/export.csv", roh=True)
pruefe(status == 200, "Export liefert 200")
pruefe(kopf.get("content-type", "").startswith("text/csv"),
       "Content-Type ist text/csv: " + str(kopf.get("content-type")))
verfuegung = kopf.get("content-disposition", "")
pruefe("attachment" in verfuegung and ".csv" in verfuegung,
       "als Download angeboten: " + verfuegung)
pruefe(rohdaten.startswith(b"\xef\xbb\xbf"), "beginnt mit UTF-8-BOM (Excel unter Windows)")

text = rohdaten.decode("utf-8-sig")
pruefe("\r\n" in text, "Zeilenende ist CRLF")
zeilen = tabelle(text)
kopfzeile = zeilen[0]
pruefe(kopfzeile[0] == "Nr." and "Kategorie (Klartext)" in kopfzeile,
       "Kopfzeile stimmt: " + str(kopfzeile[:4]))
pruefe(all("IP" not in feld for feld in kopfzeile), "keine IP-Spalte im Export")
pruefe(len(zeilen) - 1 == sqlite3.connect(DB).execute("SELECT COUNT(*) FROM antrag").fetchone()[0],
       "ohne Filter sind alle Antraege drin")

# --- Sonderzeichen -----------------------------------------------------------
print("Sonderzeichen")
zeile = [z for z in zeilen if z and z[0] == str(heikel)][0]
spalte = {name: wert for name, wert in zip(kopfzeile, zeile)}
pruefe(spalte["Name"] == "Semikolon; Zeile", "Semikolon im Feld bleibt heil")
pruefe(spalte["Funktion"] == 'Presse "Vor Ort"', "Anfuehrungszeichen bleiben heil")
pruefe("Zeile eins\nZeile zwei; mit Trenner" == spalte["Bemerkung"],
       "Zeilenumbruch im Feld bleibt heil: " + repr(spalte["Bemerkung"]))
pruefe(spalte["Kategorie"] == "vip", "Kategorie als Schluessel")
pruefe(spalte["Kategorie (Klartext)"] == "VIP", "Kategorie zusaetzlich als Klartext")
pruefe(spalte["Kontaktweg"] == "E-Mail", "Kontaktweg wird ausgewiesen")
pruefe("." in spalte["Eingegangen"] and ":" in spalte["Eingegangen"],
       "Zeitstempel ist lesbar formatiert: " + spalte["Eingegangen"])

# --- Umlaute -----------------------------------------------------------------
print("Umlaute")
namen = [z[4] for z in zeilen[1:]]
pruefe("Weiß" in namen, "Umlaute kommen im Export an: " + str(namen))

# --- Filter greifen ----------------------------------------------------------
print("Filter")
_, _, text = hole("/admin/export.csv?status=&kategorie=vip")
zeilen = tabelle(text.lstrip("﻿"))
kategorien = {z[6] for z in zeilen[1:]}
pruefe(kategorien == {"vip"}, "Kategoriefilter greift: " + str(kategorien))

_, _, text = hole("/admin/export.csv?status=&suche=" + urllib.parse.quote("mustermann"))
zeilen = tabelle(text.lstrip("﻿"))
pruefe(len(zeilen) == 2 and zeilen[1][4] == "Mustermann", "Suche greift")

_, _, text = hole("/admin/export.csv?status=neu")
zeilen = tabelle(text.lstrip("﻿"))
pruefe(all(z[2] == "neu" for z in zeilen[1:]), "Statusfilter greift")

_, _, text = hole("/admin/export.csv?status=&suche=gibtesnicht")
zeilen = tabelle(text.lstrip("﻿"))
pruefe(len(zeilen) == 1, "leere Auswahl liefert nur die Kopfzeile")

_, _, text = hole("/admin/export.csv?sortierung=" + urllib.parse.quote("id; DROP TABLE antrag--"))
pruefe(sqlite3.connect(DB).execute("SELECT COUNT(*) FROM antrag").fetchone()[0] > 0,
       "unbekannte Sortierung richtet keinen Schaden an")

# --- Verweis in der Liste ----------------------------------------------------
print("Verweis in der Liste")
_, _, liste = hole("/admin?status=&kategorie=vip")
pruefe("/admin/export.csv?status=&amp;kategorie=vip" in liste,
       "die Liste verlinkt den Export mit den aktuellen Filtern")

print()
if fehler:
    print("FEHLGESCHLAGEN (" + str(len(fehler)) + "):")
    for eintrag in fehler:
        print("  - " + eintrag)
else:
    print("alle Pruefungen bestanden")
sys.exit(1 if fehler else 0)
