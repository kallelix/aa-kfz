"""Ablauftest für die redaktionelle Freigabe (Schritt 5).

Braucht einen laufenden Server mit frischen Testdaten und `TEST_DB` – siehe
tests/README.md. Verändert die Daten, also nur gegen eine Wegwerf-Datenbank.
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


def zeile(antrag_id):
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    try:
        return con.execute("SELECT * FROM antrag WHERE id = ?", (antrag_id,)).fetchone()
    finally:
        con.close()


class KeineWeiterleitung(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


jar = http.cookiejar.CookieJar()
o = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(jar), KeineWeiterleitung()
)


def hole(pfad, daten=None):
    koerper = urllib.parse.urlencode(daten, encoding="utf-8", doseq=True).encode() if daten else None
    req = urllib.request.Request(BASIS + pfad, data=koerper)
    try:
        with o.open(req) as antwort:
            return (
                antwort.status,
                antwort.headers.get("Location", ""),
                antwort.read().decode("utf-8"),
            )
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Location", ""), e.read().decode("utf-8")


def csrf_aus(text):
    treffer = re.search(r'name="csrf" value="([^"]+)"', text)
    return treffer.group(1) if treffer else ""


hole("/admin/login", {"passwort": PASSWORT, "kuerzel": "KK", "weiter": "/admin"})
_, _, seite = hole("/admin/antrag/1")
CSRF = csrf_aus(seite)
pruefe(bool(CSRF), "angemeldet, CSRF-Token vorhanden")

daten_1 = {
    "csrf": CSRF, "vorname": "Max", "nachname": "Mustermann", "funktion": "Sanität",
    "kategorie": "camping", "telefon": "0171 1234567", "kennzeichen": "KA-XY 123",
    "bemerkung": "Kommt Freitag",
}

# --- Werte korrigieren -------------------------------------------------------
print("Werte korrigieren")
status, ort, _ = hole("/admin/antrag/1/speichern",
                      dict(daten_1, aktion="speichern", funktion="Sanitätsdienst"))
a = zeile(1)
pruefe(status == 303 and "hinweis=gespeichert" in ort, "Speichern leitet mit Hinweis zurueck")
pruefe(a["funktion"] == "Sanitätsdienst", "korrigierte Funktion ist gespeichert")
pruefe(a["status"] == "neu", "Speichern allein aendert den Status nicht")

status, _, text = hole("/admin/antrag/1/speichern",
                       dict(daten_1, aktion="speichern", nachname="", telefon="", email=""))
pruefe(status == 422 and "Name bitte ausfüllen" in text, "leerer Name wird abgelehnt")
pruefe("Bitte mindestens E-Mail oder Telefon" in text, "Kontaktregel gilt auch beim Bearbeiten")
pruefe(zeile(1)["nachname"] == "Mustermann", "nach Fehler ist nichts gespeichert")

# --- Genehmigen mit Korrektur ------------------------------------------------
print("Genehmigen")
status, ort, _ = hole("/admin/antrag/1/speichern",
                      dict(daten_1, aktion="genehmigen", funktion="Sanität"))
a = zeile(1)
pruefe(status == 303 and "hinweis=genehmigt" in ort, "Genehmigen leitet mit Hinweis zurueck")
pruefe(a["status"] == "genehmigt", "Status ist genehmigt")
pruefe(a["funktion"] == "Sanität", "Korrektur wurde beim Genehmigen mitgespeichert")
pruefe(bool(a["entscheidung_am"]), "Zeitpunkt der Entscheidung ist festgehalten")
pruefe(a["entscheidung_durch"] == "KK", "Kuerzel aus der Sitzung ist eingetragen")

_, _, seite = hole("/admin/antrag/1")
pruefe("Speichern und genehmigen" not in seite, "kein zweiter Genehmigen-Knopf bei genehmigt")
pruefe("Karte ausgegeben" in seite, "Knopf fuer die Kartenuebergabe erscheint")

# --- Ausgegeben --------------------------------------------------------------
print("Ausgegeben")
vorher = zeile(1)["entscheidung_am"]
status, ort, _ = hole("/admin/antrag/1/status", {"csrf": CSRF, "ziel": "ausgegeben"})
a = zeile(1)
pruefe(status == 303 and "hinweis=ausgegeben" in ort, "Ausgeben leitet mit Hinweis zurueck")
pruefe(a["status"] == "ausgegeben", "Status ist ausgegeben")
pruefe(a["entscheidung_am"] == vorher, "Zeitpunkt der Genehmigung bleibt erhalten")

# --- Zuruecksetzen -----------------------------------------------------------
print("Zuruecksetzen")
status, ort, _ = hole("/admin/antrag/1/status", {"csrf": CSRF, "ziel": "neu"})
a = zeile(1)
pruefe(status == 303 and "hinweis=zurueckgesetzt" in ort, "Zuruecksetzen leitet mit Hinweis zurueck")
pruefe(a["status"] == "neu", "Status ist wieder neu")
pruefe(a["entscheidung_am"] is None and a["entscheidung_durch"] is None,
       "Entscheidungsdaten sind geraeumt")

# --- Unerlaubte Uebergaenge --------------------------------------------------
print("Unerlaubte Uebergaenge")
status, ort, _ = hole("/admin/antrag/1/status", {"csrf": CSRF, "ziel": "ausgegeben"})
pruefe("hinweis=nichts" in ort, "neu -> ausgegeben wird abgewiesen")
pruefe(zeile(1)["status"] == "neu", "Status blieb neu")

status, ort, _ = hole("/admin/antrag/1/status", {"csrf": CSRF, "ziel": "geloescht"})
pruefe("hinweis=nichts" in ort, "erfundener Zielstatus wird abgewiesen")
pruefe(zeile(1)["status"] == "neu", "Status blieb neu")

# --- Ablehnen ----------------------------------------------------------------
print("Ablehnen")
status, _, text = hole("/admin/antrag/3/ablehnen", {"csrf": CSRF, "begruendung": "   "})
pruefe(status == 422 and "Bitte eine Begründung angeben" in text,
       "Ablehnen ohne Begruendung wird abgewiesen")
pruefe(zeile(3)["status"] == "neu", "Status blieb neu")

status, ort, _ = hole("/admin/antrag/3/ablehnen",
                      {"csrf": CSRF, "begruendung": "Kontingent erschöpft, sorry."})
a = zeile(3)
pruefe(status == 303 and "hinweis=abgelehnt" in ort, "Ablehnen leitet mit Hinweis zurueck")
pruefe(a["status"] == "abgelehnt", "Status ist abgelehnt")
pruefe(a["begruendung"] == "Kontingent erschöpft, sorry.", "Begruendung ist gespeichert")
pruefe(a["entscheidung_durch"] == "KK", "Kuerzel ist eingetragen")

_, _, seite = hole("/admin/antrag/3")
pruefe("Doch genehmigen" in seite, "abgelehnter Antrag laesst sich noch genehmigen")

# --- Sammelaktion ------------------------------------------------------------
print("Sammelaktion")
con = sqlite3.connect(DB)
with con:
    con.execute("UPDATE antrag SET status='neu', entscheidung_am=NULL,"
                " entscheidung_durch=NULL, begruendung=NULL")
con.close()

status, ort, _ = hole("/admin/sammelaktion", {"csrf": CSRF, "zurueck": "/admin"})
pruefe("hinweis=nichts_markiert" in ort, "ohne Markierung passiert nichts")

status, ort, _ = hole("/admin/sammelaktion", {"csrf": CSRF, "ids": ["1", "3"], "zurueck": "/admin"})
pruefe(status == 303 and "hinweis=sammel&anzahl=2" in ort, "zwei Antraege genehmigt: " + ort)
pruefe(zeile(1)["status"] == "genehmigt" and zeile(3)["status"] == "genehmigt",
       "beide stehen auf genehmigt")
pruefe(zeile(1)["entscheidung_durch"] == "KK", "Kuerzel auch bei der Sammelaktion")

status, ort, _ = hole("/admin/sammelaktion", {"csrf": CSRF, "ids": ["1"], "zurueck": "/admin"})
pruefe("anzahl=0" in ort, "bereits genehmigte werden nicht doppelt gezaehlt")

status, ort, _ = hole("/admin/sammelaktion",
                      {"csrf": CSRF, "ids": ["nichtszahl", "99999"], "zurueck": "/admin"})
pruefe("anzahl=0" in ort, "Unfug in ids fuehrt zu keiner Aenderung")

status, ort, _ = hole("/admin/sammelaktion",
                      {"csrf": CSRF, "ids": ["1"], "zurueck": "https://boese.example/"})
pruefe(ort.startswith("/admin"), "fremdes Rueckkehrziel wird abgewiesen: " + ort)

status, _, _ = hole("/admin/sammelaktion", {"csrf": "falsch", "ids": ["1"]})
pruefe(status == 400, "Sammelaktion ohne CSRF-Token -> 400")

# --- CSRF auf allen Schreibwegen --------------------------------------------
print("CSRF auf allen Schreibwegen")
for pfad, daten in (
    ("/admin/antrag/1/speichern", dict(daten_1, csrf="falsch", aktion="genehmigen")),
    ("/admin/antrag/1/ablehnen", {"csrf": "falsch", "begruendung": "weil"}),
    ("/admin/antrag/1/status", {"csrf": "falsch", "ziel": "neu"}),
):
    status, _, _ = hole(pfad, daten)
    pruefe(status == 400, pfad + " ohne CSRF-Token -> 400")

# --- Unbekannter Antrag ------------------------------------------------------
print("Unbekannter Antrag")
for pfad, daten in (
    ("/admin/antrag/99999/speichern", dict(daten_1, aktion="speichern")),
    ("/admin/antrag/99999/ablehnen", {"csrf": CSRF, "begruendung": "weil"}),
    ("/admin/antrag/99999/status", {"csrf": CSRF, "ziel": "neu"}),
):
    status, _, _ = hole(pfad, daten)
    pruefe(status == 404, pfad + " -> 404")

# --- Kontingent --------------------------------------------------------------
print("Kontingentwarnung (erwartet KONTINGENTE=camping:1)")
con = sqlite3.connect(DB)
with con:
    con.execute("UPDATE antrag SET status='neu' WHERE id=3")
    con.execute("UPDATE antrag SET status='genehmigt' WHERE id=1")
con.close()
_, _, seite = hole("/admin/antrag/3")
pruefe("Kontingent für" in seite and "ausgeschöpft" in seite,
       "volles Kontingent wird auf der Detailseite gewarnt")
pruefe("keine Sperre" in seite, "die Warnung sagt, dass sie keine Sperre ist")
status, ort, _ = hole("/admin/antrag/3/speichern",
                      {"csrf": CSRF, "aktion": "genehmigen", "vorname": "Jörg",
                       "nachname": "Weiß", "funktion": "Aufbau",
                       "kategorie": "camping", "email": "joerg@example.org",
                       "kennzeichen": "HD-JW 30"})
pruefe(zeile(3)["status"] == "genehmigt", "trotz vollem Kontingent genehmigbar")

_, _, liste = hole("/admin?status=")
pruefe("zaehler-voll" in liste, "volle Kategorie ist in der Liste markiert")

print()
if fehler:
    print("FEHLGESCHLAGEN (" + str(len(fehler)) + "):")
    for eintrag in fehler:
        print("  - " + eintrag)
else:
    print("alle Pruefungen bestanden")
sys.exit(1 if fehler else 0)
