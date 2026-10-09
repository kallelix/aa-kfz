"""Die Konten in kern/konten.py – ohne Server.

    python tests/test_kern_konten.py

Braucht den PostgreSQL aus compose.yaml und legt sich darauf eine
Wegwerf-Datenbank an.
"""

import sys
from datetime import timedelta
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WURZEL))

from kern import testdb  # noqa: E402
from kern.konten import Fehler, Konten  # noqa: E402

fehler = []


def pruefe(bedingung, text):
    print(("  ok   " if bedingung else "  FEHL ") + text)
    if not bedingung:
        fehler.append(text)


def wirft(aufruf, enthaelt=""):
    try:
        aufruf()
    except Fehler as f:
        return enthaelt in str(f)
    return False


url = testdb.wegwerf("test_konten")
konten = Konten(lambda: url)
pruefe("0001_konten.sql" in konten.init(), "Schema kern wird angelegt")
pruefe(konten.init() == [], "und beim zweiten Start nicht noch einmal")

print("Anlegen")
pruefe(not konten.gibt_es_admin(), "anfangs kein Admin")
eva = konten.anlegen(email=" Eva@Example.org ", name="Eva  Admin", kuerzel="ea",
                     rolle="admin", von="Test")
k = konten.laden(eva)
pruefe(k["email"] == "eva@example.org" and k["kuerzel"] == "EA" and k["name"] == "Eva Admin",
       "Mail klein, Kürzel groß, Name ohne doppelte Leerzeichen")
pruefe(not konten.gibt_es_admin(), "ein Admin ohne Passwort zählt noch nicht")
pruefe(wirft(lambda: konten.anlegen(email="eva@example.org", name="X", kuerzel="XX",
                                    rolle="orga", bereiche=["presse"]), "Mailadresse"),
       "dieselbe Adresse geht nicht zweimal")
pruefe(wirft(lambda: konten.anlegen(email="x@example.org", name="X", kuerzel="Ea",
                                    rolle="orga", bereiche=["presse"]), "Kürzel"),
       "dasselbe Kürzel auch nicht, egal wie geschrieben")
pruefe(wirft(lambda: konten.anlegen(email="x@example.org", name="X", kuerzel="XX",
                                    rolle="orga"), "Bereich"),
       "Orga ohne Bereich geht nicht")
pruefe(wirft(lambda: konten.anlegen(email="kein-at", name="X", kuerzel="XX",
                                    rolle="orga", bereiche=["presse"]), "Mailadresse"),
       "kaputte Adresse wird abgewiesen")
pruefe(wirft(lambda: konten.anlegen(email="x@example.org", name="X", kuerzel="X Y",
                                    rolle="orga", bereiche=["presse"]), "Kürzel"),
       "Kürzel mit Leerzeichen wird abgewiesen")
pia = konten.anlegen(email="pia@example.org", name="Pia Presse", kuerzel="PP",
                     rolle="orga", bereiche=["presse", "unbekannt"], von="EA")
pruefe(konten.laden(pia)["bereiche"] == ["presse"], "unbekannte Bereiche fallen weg")
bea = konten.anlegen(email="bea@example.org", name="Bea Bereich", kuerzel="BB",
                     rolle="bereichsleitung", bereiche=["presse"], telefon="  0151   123 ")
pruefe(konten.laden(bea)["bereiche"] == ["helfer"],
       "eine Bereichsleitung sieht nur den Helferbereich, was auch angekreuzt war")
pruefe(konten.laden(bea)["telefon"] == "0151 123", "die Nummer wird geglättet")
konten.telefon_setzen(bea, "0160 9")
pruefe(konten.laden(bea)["telefon"] == "0160 9", "die eigene Nummer lässt sich setzen")

print("Einladung")
link = konten.link_anlegen(eva, "einladung")
pruefe(konten.link_lesen(link)["id"] == eva, "der Link führt zum Konto")
pruefe(konten.link_lesen(link + "x") is None, "ein veränderter Link nicht")
pruefe(wirft(lambda: konten.link_einloesen(link, "kurz"), "mindestens"),
       "zu kurzes Passwort wird abgewiesen")
pruefe(konten.link_lesen(link) is not None, "und der Link gilt danach weiter")
pruefe(konten.link_einloesen(link, "ein-langes-passwort")["id"] == eva, "Einladung eingelöst")
pruefe(konten.link_einloesen(link, "noch-ein-passwort") is None, "ein zweites Mal nicht")
pruefe(konten.gibt_es_admin(), "jetzt gibt es einen Admin")
erster = konten.link_anlegen(pia, "einladung")
zweiter = konten.link_anlegen(pia, "einladung")
pruefe(konten.link_lesen(erster) is None and konten.link_lesen(zweiter) is not None,
       "ein neuer Link macht den alten ungültig")

print("Anmelden")
pruefe(konten.anmelden("EVA@example.org", "ein-langes-passwort")["id"] == eva,
       "mit Adresse in anderer Schreibung")
pruefe(konten.anmelden("eva@example.org", "falsch-falsch") is None, "falsches Passwort nicht")
pruefe(konten.anmelden("gibt-es@nicht.org", "ein-langes-passwort") is None,
       "unbekannte Adresse nicht")
pruefe(konten.anmelden("pia@example.org", "") is None, "Konto ohne Passwort nicht")
pruefe(konten.laden(eva)["zuletzt_angemeldet_am"] is not None, "letzte Anmeldung vermerkt")

print("Sitzungen")
s1 = konten.sitzung_anlegen(eva, timedelta(hours=1))
s2 = konten.sitzung_anlegen(eva, timedelta(hours=1))
pruefe(konten.sitzung_lesen(s1)["kuerzel"] == "EA", "die Sitzung führt zum Konto")
pruefe(konten.sitzung_lesen("") is None and konten.sitzung_lesen("quatsch") is None,
       "leere und erfundene Sitzungen nicht")
alt = konten.sitzung_anlegen(eva, timedelta(seconds=-1))
pruefe(konten.sitzung_lesen(alt) is None, "abgelaufene Sitzung gilt nicht")
konten.passwort_setzen(eva, "das-neue-passwort", ausser_sitzung=s1)
pruefe(konten.sitzung_lesen(s1) is not None and konten.sitzung_lesen(s2) is None,
       "neues Passwort beendet die anderen Sitzungen, die eigene bleibt")
konten.sitzung_beenden(s1)
pruefe(konten.sitzung_lesen(s1) is None, "Abmelden beendet die Sitzung")

print("Ändern und der letzte Admin")
pruefe(wirft(lambda: konten.aendern(eva, email="eva@example.org", name="Eva Admin",
                                    kuerzel="EA", rolle="orga", bereiche=["helfer"]),
             "letzte Admin"),
       "der letzte Admin kann nicht herabgestuft werden")
pruefe(wirft(lambda: konten.aendern(eva, email="eva@example.org", name="Eva Admin",
                                    kuerzel="EA", rolle="admin", aktiv=False),
             "letzte Admin"),
       "und nicht gesperrt")
konten.link_einloesen(konten.link_anlegen(pia, "einladung"), "pias-passwort-123")
sp = konten.sitzung_anlegen(pia, timedelta(hours=1))
konten.aendern(pia, email="pia@example.org", name="Pia Presse", kuerzel="PP",
               rolle="orga", bereiche=["presse"], aktiv=False)
pruefe(konten.sitzung_lesen(sp) is None, "gesperrt heißt: sofort abgemeldet")
pruefe(konten.anmelden("pia@example.org", "pias-passwort-123") is None,
       "und keine neue Anmeldung")
pruefe(konten.link_lesen(konten.link_anlegen(pia, "zuruecksetzen")) is None,
       "auch kein Link zum Zurücksetzen")
konten.aendern(pia, email="pia@example.org", name="Pia Presse", kuerzel="PP",
               rolle="admin", bereiche=[], aktiv=True)
konten.aendern(eva, email="eva@example.org", name="Eva Admin", kuerzel="EA",
               rolle="lesend", bereiche=["kennzeichen"])
pruefe(konten.laden(eva)["rolle"] == "lesend",
       "mit einem zweiten Admin lässt sich der erste herabstufen")

print()
if fehler:
    print("FEHLGESCHLAGEN (" + str(len(fehler)) + "):")
    for eintrag in fehler:
        print("  - " + eintrag)
    sys.exit(1)
print("alle Pruefungen bestanden")
