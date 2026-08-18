"""HTTP-Test für die Druckansicht der Karten (Schritt 11).

Braucht einen laufenden Server mit `TEST_DB` und frischem Seed – siehe
tests/README.md. Der Server sollte mit
`KARTEN_URL_BASIS=https://kennzeichen.example.de` laufen.
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


class KeineWeiterleitung(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


jar = http.cookiejar.CookieJar()
o = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar), KeineWeiterleitung())


def hole(pfad, daten=None):
    koerper = urllib.parse.urlencode(daten, encoding="utf-8", doseq=True).encode() if daten else None
    try:
        with o.open(urllib.request.Request(BASIS + pfad, data=koerper)) as antwort:
            return antwort.status, antwort.headers, antwort.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read().decode("utf-8")


def csrf_aus(text):
    treffer = re.search(r'name="csrf" value="([^"]+)"', text)
    return treffer.group(1) if treffer else ""


# --- Ohne Anmeldung ----------------------------------------------------------
print("Ohne Anmeldung")
status, kopf, _ = hole("/admin/karten")
pruefe(status == 303 and kopf.get("Location", "").startswith("/admin/login"),
       "Druckansicht ohne Anmeldung fuehrt zur Anmeldeseite")

hole("/admin/login", {"passwort": PASSWORT, "kuerzel": "KK", "weiter": "/admin"})

# --- Ohne genehmigte Antraege ------------------------------------------------
print("Ohne genehmigte Antraege")
status, _, seite = hole("/admin/karten")
pruefe(status == 200, "Seite laedt auch ohne Treffer")
pruefe("nichts zu drucken" in seite, "sagt, dass es nichts zu drucken gibt")
_, _, liste = hole("/admin?status=")
pruefe("Karten drucken" not in liste, "die Liste bietet den Druck noch nicht an")

# --- Genehmigen und drucken --------------------------------------------------
print("Mit genehmigten Antraegen")
_, _, seite = hole("/admin/antrag/1")
CSRF = csrf_aus(seite)
hole("/admin/sammelaktion", {"csrf": CSRF, "ids": ["1", "3"], "zurueck": "/admin"})

status, _, seite = hole("/admin/karten")
pruefe(status == 200, "Druckansicht laedt")
pruefe(seite.count('class="karte"') == 2, "zwei Karten: " + str(seite.count('class="karte"')))
pruefe(seite.count('class="bogen"') == 1, "beide auf einem Bogen")
pruefe("Mustermann" in seite and "Weiß" in seite, "Namen stehen drauf")
pruefe("Sanität" in seite, "Funktion steht drauf")
pruefe("Camping" in seite, "Kategorie im Klartext")
pruefe("KA-XY 123" in seite, "Kennzeichen steht drauf, wenn vorhanden")
pruefe("Nr. 1" in seite, "Antragsnummer steht drauf")
pruefe("/static/karten.css" in seite, "eigenes Druck-Stylesheet ist eingebunden")

# --- QR-Codes ----------------------------------------------------------------
print("QR-Codes")
pruefe(seite.count("<svg") == 2, "je Karte ein SVG: " + str(seite.count("<svg")))
pruefe("data:image" not in seite, "kein data:-URI, sonst wuerde die CSP es blocken")
pruefe("<img" not in seite or "/static/" in seite, "keine externen Bilder")

# Der QR-Code muss auch wirklich das Richtige enthalten.
try:
    import segno  # noqa: F401
    from urllib.parse import urlparse
    basis = os.environ.get("TEST_KARTEN_BASIS", "https://kennzeichen.example.de")
    erwartet = segno.make(basis + "/admin/antrag/1", error="m").svg_inline(
        scale=3, dark="#000000", border=0
    )
    pruefe(erwartet in seite, "QR-Code von Antrag 1 zeigt auf " + basis + "/admin/antrag/1")
except ImportError:
    pruefe(False, "segno fehlt")

# --- Nur genehmigte, wenn so gefiltert ---------------------------------------
print("Filter")
status, _, nur_neu = hole("/admin/karten?status=neu")
pruefe("Beispiel" in nur_neu, "mit status=neu kommen die neuen")
pruefe("Mustermann" not in nur_neu, "und die genehmigten nicht")

status, _, gefiltert = hole("/admin/karten?status=genehmigt&kategorie=camping")
pruefe("Mustermann" in gefiltert and "Weiß" in gefiltert, "Kategoriefilter greift")

status, _, gesucht = hole("/admin/karten?status=genehmigt&suche=" + urllib.parse.quote("mustermann"))
pruefe(gesucht.count('class="karte"') == 1, "Suche grenzt ein")

status, _, unfug = hole("/admin/karten?sortierung=" + urllib.parse.quote("id; DROP TABLE antrag--"))
pruefe(status == 200, "unbekannte Sortierung faellt auf die Vorgabe zurueck")
pruefe(sqlite3.connect(DB).execute("SELECT COUNT(*) FROM antrag").fetchone()[0] > 0,
       "und richtet keinen Schaden an")

# --- Umbruch auf mehrere Boegen ----------------------------------------------
print("Bogenumbruch")
for nummer in range(5):
    hole("/", {"vorname": "Bogen" + str(nummer), "nachname": "Test",
               "funktion": "Aufbau", "kategorie": "camping",
               "kennzeichen": "B-BT " + str(nummer + 1),
               "telefon": "030 " + str(nummer)})
neue = [str(z[0]) for z in sqlite3.connect(DB).execute(
    "SELECT id FROM antrag WHERE nachname = 'Test'")]
hole("/admin/sammelaktion", {"csrf": CSRF, "ids": neue, "zurueck": "/admin"})

status, _, viele = hole("/admin/karten")
karten = viele.count('class="karte"')
boegen = viele.count('class="bogen"')
pruefe(karten == 7, "sieben Karten: " + str(karten))
pruefe(boegen == 2, "auf zwei Boegen: " + str(boegen))

# --- Verweis in der Liste ----------------------------------------------------
print("Verweis in der Liste")
_, _, liste = hole("/admin?status=neu")
pruefe("Karten drucken" in liste, "die Liste bietet den Druck jetzt an")
pruefe("/admin/karten?status=genehmigt" in liste,
       "der Verweis zeigt auf genehmigt, nicht auf den gerade sichtbaren Filter")

# --- Kein Logo hinterlegt ----------------------------------------------------
print("Logo")
pruefe("Kein Logo hinterlegt" in viele or "kein Logo hinterlegt" in viele,
       "ohne LOGO_DATEI wird darauf hingewiesen")
pruefe('class="karte-logo"' not in viele, "und es wird kein leeres Bild eingebaut")

print()
if fehler:
    print("FEHLGESCHLAGEN (" + str(len(fehler)) + "):")
    for eintrag in fehler:
        print("  - " + eintrag)
else:
    print("alle Pruefungen bestanden")
sys.exit(1 if fehler else 0)
