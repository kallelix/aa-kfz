"""HTTP-Ablauftest für Anmeldung und Backoffice.

Braucht einen laufenden Server mit frisch eingespielten Testdaten – siehe
tests/README.md. Der Test löscht Antrag 2 und sperrt am Ende die Anmeldung
für die eigene IP; danach gehört die Test-Datenbank weggeworfen.
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


def zaehle(sql, *parameter):
    con = sqlite3.connect(DB)
    try:
        return con.execute(sql, parameter).fetchone()[0]
    finally:
        con.close()


class KeineWeiterleitung(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def oeffner(folgen=True):
    jar = http.cookiejar.CookieJar()
    handler = [urllib.request.HTTPCookieProcessor(jar)]
    if not folgen:
        handler.append(KeineWeiterleitung())
    o = urllib.request.build_opener(*handler)
    o.jar = jar
    return o


def hole(o, pfad, daten=None):
    """Liefert (status, ort, text) – auch bei 3xx/4xx, ohne Ausnahme."""
    koerper = urllib.parse.urlencode(daten, encoding="utf-8").encode() if daten else None
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


anmeldung = {"passwort": PASSWORT, "weiter": "/admin"}

# --- 1. Ohne Anmeldung -------------------------------------------------------
print("Ohne Anmeldung")
o = oeffner(folgen=False)
for pfad in ("/admin", "/admin/antrag/1", "/admin?status="):
    status, ort, _ = hole(o, pfad)
    pruefe(
        status == 303 and ort.startswith("/admin/login?weiter="),
        pfad + " leitet zur Anmeldung (" + str(status) + " -> " + ort + ")",
    )

status, _, _ = hole(o, "/admin/antrag/1/loeschen", {"csrf": "x"})
pruefe(status == 303, "Loeschen ohne Anmeldung wird abgewiesen")

anzahl_vorher = zaehle("SELECT COUNT(*) FROM antrag")

# --- Kennzeichen ist Pflicht -------------------------------------------------
print("Kennzeichen ist Pflicht")
pflicht = {"vorname": "Kurt", "nachname": "Kennzeichen", "funktion": "Aufbau",
           "kategorie": "camping", "telefon": "030 4711"}

status, _, text = hole(o, "/", dict(pflicht))
pruefe(status == 422 and "Bitte das amtliche Kennzeichen angeben" in text,
       "ohne Kennzeichen wird abgewiesen")

status, _, text = hole(o, "/", dict(pflicht, kennzeichen="x"))
pruefe(status == 422 and "sieht nicht nach einem Kennzeichen aus" in text,
       "ein einzelnes Zeichen genuegt nicht")

status, _, _ = hole(o, "/", dict(pflicht, kennzeichen="ka-kk 4711"))
pruefe(status == 303, "mit Kennzeichen geht es durch")

_, _, formular = hole(o, "/")
kennzeichen_stelle = formular.find('name="kennzeichen"')
funktion_stelle = formular.find('name="funktion"')
kategorie_stelle = formular.find('name="kategorie"')
pruefe(funktion_stelle < kennzeichen_stelle < kategorie_stelle,
       "das Feld steht zwischen Funktion und Kategorie")
pruefe("Straßensperre" in formular, "das Formular erklaert, wofuer es gebraucht wird")

# Der Abschnitt oben hat einen Antrag angelegt – der Ausgangsstand fuer die
# spaetere Zaehlprobe muss danach genommen werden.
anzahl_vorher = zaehle("SELECT COUNT(*) FROM antrag")

status, _, _ = hole(o, "/admin/login")
pruefe(status == 200, "Anmeldeseite ist erreichbar")
status, _, text = hole(o, "/admin/login?weiter=" + urllib.parse.quote("//boese.example/"))
pruefe('value="/admin"' in text, "fremdes Weiterleitungsziel wird auf /admin zurechtgebogen")

# --- 2. Anmeldung ------------------------------------------------------------
print("Anmeldung")
o = oeffner(folgen=False)
status, _, text = hole(o, "/admin/login", {"passwort": "falsch", "weiter": "/admin"})
pruefe(status == 401 and "Passwort stimmt nicht" in text, "falsches Passwort -> 401")

status, ort, _ = hole(o, "/admin/login", dict(anmeldung, kuerzel="KK"))
pruefe(status == 303 and ort == "/admin", "richtiges Passwort -> 303 auf /admin")
kekse = [c for c in o.jar if c.name == "abfahrt_sitzung"]
pruefe(len(kekse) == 1, "Session-Cookie wurde gesetzt")
if kekse:
    pruefe(kekse[0].path == "/admin", "Cookie-Pfad ist /admin (nicht /)")
    pruefe(kekse[0].has_nonstandard_attr("HttpOnly"), "Cookie ist HttpOnly")

status, _, _ = hole(o, "/admin/login")
pruefe(status == 303, "angemeldet fuehrt die Anmeldeseite direkt weiter")

# --- 3. Liste und Filter -----------------------------------------------------
print("Liste und Filter")
o = oeffner()
hole(o, "/admin/login", dict(anmeldung, kuerzel="KK"))
status, _, liste = hole(o, "/admin")
pruefe(status == 200, "Liste laedt")
pruefe("KK" in liste, "Kuerzel steht in der Kopfzeile")
pruefe("Status „neu“" in liste, "Vorgabefilter ist neu")

status, _, alle = hole(o, "/admin?status=")
pruefe(
    alle.count('href="/admin/antrag/') >= liste.count('<a href="/admin/antrag/'),
    "ohne Statusfilter sind es mindestens so viele",
)

status, _, gefiltert = hole(o, "/admin?status=&kategorie=vip")
pruefe("Beispiel" in gefiltert and "Mustermann" not in gefiltert, "Kategoriefilter greift")

status, _, gesucht = hole(o, "/admin?status=&suche=" + urllib.parse.quote("mustermann"))
pruefe("Mustermann" in gesucht and "Beispiel" not in gesucht, "Suche greift")

status, _, umlaut = hole(o, "/admin?status=&suche=" + urllib.parse.quote("weiß"))
pruefe("Weiß" in umlaut, "Suche findet Umlaute unabhaengig von Gross/Klein")

status, _, _ = hole(
    o, "/admin?status=&sortierung=" + urllib.parse.quote("id; DROP TABLE antrag--")
)
pruefe(status == 200, "unbekannte Sortierung faellt auf die Vorgabe zurueck")
pruefe(
    zaehle("SELECT COUNT(*) FROM antrag") == anzahl_vorher,
    "Tabelle existiert noch (kein SQL aus der URL)",
)

status, _, _ = hole(o, "/admin?status=&sortierung=name")
pruefe(status == 200, "Sortierung nach Name laedt")

# --- 4. Detailansicht --------------------------------------------------------
print("Detailansicht")
status, _, detail = hole(o, "/admin/antrag/1")
pruefe(status == 200 and "Mustermann" in detail, "Detailansicht zeigt den Antrag")
pruefe("0171 1234567" in detail, "Telefonnummer ist sichtbar")
pruefe("nur Telefon" in detail, "Antrag ohne Mail ist als 'nur Telefon' markiert")
status, _, _ = hole(o, "/admin/antrag/99999")
pruefe(status == 404, "unbekannte Nummer -> 404")

# --- 5. Loeschen -------------------------------------------------------------
print("Loeschen")
status, _, _ = hole(o, "/admin/antrag/2/loeschen", {"csrf": "falsch"})
pruefe(status == 400, "Loeschen ohne gueltigen CSRF-Token -> 400")
pruefe(zaehle("SELECT COUNT(*) FROM antrag WHERE id=2") == 1, "Antrag 2 ist noch da")

fremder_token = csrf_aus(detail)
pruefe(bool(fremder_token), "CSRF-Token steht im Loeschformular")
o_fremd = oeffner(folgen=False)
hole(o_fremd, "/admin/login", anmeldung)
status, _, _ = hole(o_fremd, "/admin/antrag/2/loeschen", {"csrf": fremder_token})
pruefe(status == 400, "CSRF-Token einer fremden Sitzung wird abgelehnt")

status, _, detail2 = hole(o, "/admin/antrag/2")
hole(o, "/admin/antrag/2/loeschen", {"csrf": csrf_aus(detail2)})
pruefe(zaehle("SELECT COUNT(*) FROM antrag WHERE id=2") == 0, "mit gueltigem Token wird geloescht")

# --- 6. Abmelden -------------------------------------------------------------
print("Abmelden")
o = oeffner(folgen=False)
hole(o, "/admin/login", anmeldung)
status, _, seite = hole(o, "/admin")
status, ort, _ = hole(o, "/admin/logout", {"csrf": "falsch"})
pruefe(ort.startswith("/admin/login?weiter="), "Abmelden ohne CSRF-Token wird abgewiesen")
status, _, seite = hole(o, "/admin")
pruefe(status == 200, "Sitzung besteht nach abgewiesenem Abmelden weiter")
status, ort, _ = hole(o, "/admin/logout", {"csrf": csrf_aus(seite)})
pruefe(ort == "/admin/login", "Abmelden leitet zur Anmeldeseite")
status, ort, _ = hole(o, "/admin")
pruefe(status == 303 and ort.startswith("/admin/login"), "nach dem Abmelden ist Schluss")

# --- 7. Manipuliertes Cookie -------------------------------------------------
print("Manipuliertes Cookie")
o = oeffner(folgen=False)
hole(o, "/admin/login", dict(anmeldung, kuerzel="KK"))
for keks in o.jar:
    if keks.name == "abfahrt_sitzung":
        keks.value = keks.value[:-2] + "xy"
status, ort, _ = hole(o, "/admin")
pruefe(status == 303 and ort.startswith("/admin/login"), "verbogenes Cookie zaehlt nicht")

# --- 8. Rate Limit -----------------------------------------------------------
print("Rate Limit am Login (erwartet LOGIN_VERSUCHE=3)")
o = oeffner(folgen=False)
codes = [hole(o, "/admin/login", {"passwort": "falsch", "weiter": "/admin"})[0] for _ in range(4)]
pruefe(codes[:3] == [401, 401, 401] and codes[3] == 429, "3x 401, dann 429: " + str(codes))
status, _, _ = hole(o, "/admin/login", anmeldung)
pruefe(status == 429, "auch das richtige Passwort prallt waehrend der Sperre ab")

# --- 9. Oeffentlicher Teil unberuehrt ---------------------------------------
print("Oeffentlicher Teil")
o = oeffner()
status, _, formular = hole(o, "/")
pruefe(status == 200 and "Durchfahrtsberechtigung" in formular, "Formular laeuft weiter")
pruefe("abfahrt_sitzung" not in str(o.jar), "kein Session-Cookie auf der oeffentlichen Seite")

print()
if fehler:
    print("FEHLGESCHLAGEN (" + str(len(fehler)) + "):")
    for eintrag in fehler:
        print("  - " + eintrag)
else:
    print("alle Pruefungen bestanden")
sys.exit(1 if fehler else 0)
