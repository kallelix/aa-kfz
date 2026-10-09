"""Die Veranstaltungen in kern/veranstaltungen.py – ohne Server.

    python tests/test_kern_veranstaltungen.py

Braucht den PostgreSQL aus compose.yaml und legt sich darauf eine
Wegwerf-Datenbank an.
"""

import sys
from datetime import date
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WURZEL))

from kern import testdb  # noqa: E402
from kern import veranstaltungen as va  # noqa: E402

fehler = []


def pruefe(bedingung, text):
    print(("  ok   " if bedingung else "  FEHL ") + text)
    if not bedingung:
        fehler.append(text)


def wirft(aufruf, enthaelt=""):
    try:
        aufruf()
    except va.Fehler as f:
        return enthaelt in str(f)
    return False


url = testdb.wegwerf("test_va")
v = va.Veranstaltungen(lambda: url)
v.init()

print("Anlegen und prüfen")
pruefe(v.vorgabe() is None, "ohne Veranstaltung keine Vorgabe")
GRUND = {"name": "Die absolute Abfahrt 2027", "kurz": "AA 2027", "beginn": "2027-07-01",
         "ende": "2027-07-04", "ort": "Ilmenau", "status": "planung"}
aa = v.anlegen(GRUND)
zeile = v.laden(aa)
pruefe(zeile["beginn"] == date(2027, 7, 1) and zeile["status"] == "planung",
       "Tage als Datum, Status in Planung")
pruefe(va.tage(zeile) == [date(2027, 7, d) for d in (1, 2, 3, 4)], "vier Tage")
pruefe(wirft(lambda: v.anlegen(GRUND), "Kurznamen"), "derselbe Kurzname geht nicht zweimal")
pruefe(wirft(lambda: v.anlegen({**GRUND, "kurz": "X", "ende": "2027-06-30"}), "vor dem ersten"),
       "das Ende vor dem Beginn geht nicht")
pruefe(wirft(lambda: v.anlegen({**GRUND, "kurz": "X", "beginn": "1.7.2027"}), "kein Datum"),
       "ein Datum in falscher Schreibweise wird erkannt")
pruefe(wirft(lambda: v.anlegen({**GRUND, "kurz": "X", "anmeldung_ab": "2026-12-15",
                                "anmeldung_bis": "2026-12-01"}), "endet, bevor"),
       "die Anmeldung kann nicht vor ihrem Beginn enden")
pruefe(wirft(lambda: v.anlegen({**GRUND, "kurz": "X", "status": "irgendwas"}), "Status"),
       "unbekannter Status wird abgewiesen")

print("Welche gilt ohne Wahl")
xco = v.anlegen({**GRUND, "name": "XCO 2027", "kurz": "XCO 2027",
                 "beginn": "2027-05-15", "ende": "2027-05-15"})
alt = v.anlegen({**GRUND, "name": "AA 2026", "kurz": "AA 2026", "beginn": "2026-08-28",
                 "ende": "2026-08-30", "status": "archiviert"})
pruefe(v.vorgabe(date(2026, 10, 9))["id"] == xco, "im Oktober 2026: die nächste ist der XCO")
pruefe(v.vorgabe(date(2027, 5, 15))["id"] == xco, "am Tag des XCO: der XCO")
pruefe(v.vorgabe(date(2027, 5, 16))["id"] == aa, "danach: die AA")
pruefe(v.vorgabe(date(2027, 9, 1))["id"] == aa, "ist alles vorbei: die zuletzt gewesene")
pruefe(v.gewaehlt(str(alt), date(2026, 10, 9))["id"] == alt, "eine gewählte gilt, auch archiviert")
pruefe(v.gewaehlt("quatsch", date(2026, 10, 9))["id"] == xco, "eine unsinnige Wahl fällt auf die Vorgabe")
pruefe(v.gewaehlt("999", date(2026, 10, 9))["id"] == xco, "eine gelöschte auch")
pruefe([z["kurz"] for z in v.liste()] == ["AA 2027", "XCO 2027", "AA 2026"],
       "Liste: neueste zuerst, archivierte am Ende")

print("Ändern und löschen")
v.aendern(aa, {**GRUND, "status": "offen", "anmeldung_ab": "2026-12-15"})
pruefe(v.laden(aa)["status"] == "offen" and v.laden(aa)["anmeldung_ab"] == date(2026, 12, 15),
       "Status und Anmeldestart geändert")
v.loeschen(xco)
pruefe(v.laden(xco) is None, "eine Veranstaltung ohne Daten lässt sich löschen")

print()
if fehler:
    print("FEHLGESCHLAGEN (" + str(len(fehler)) + "):")
    for eintrag in fehler:
        print("  - " + eintrag)
    sys.exit(1)
print("alle Pruefungen bestanden")
