"""Das Programm-Band: Achse, Packung, offene Enden (Schritt 7).

    python helfer/tests/test_band.py

Reine Rechnerei, kein Server und keine Datenbank – band.py bekommt Listen und
gibt Prozentwerte zurück.
"""

import sys
from datetime import datetime
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WURZEL))

from app import band  # noqa: E402

fehler = []


def pruefe(bedingung, text):
    print(("  ok   " if bedingung else "  FEHL ") + text)
    if not bedingung:
        fehler.append(text)


TAG = "2026-08-29"


def programmpunkt(titel, beginn, ende, serie="dhc", roh=""):
    return {"titel": titel, "serie": serie,
            "beginn": TAG + " " + beginn if beginn else None,
            "ende": TAG + " " + ende if ende else None,
            "zeit_roh": roh}


def schicht(nummer, liste, beginn, ende, besetzt, bedarf, tag=TAG):
    return {"id": nummer, "liste": liste, "beginn": TAG + " " + beginn,
            "ende": tag + " " + ende, "besetzt": besetzt, "bedarf": bedarf,
            "fehlt": max(0, bedarf - besetzt)}


print("Minuten seit Mitternacht")
pruefe(band.minuten("2026-08-29 00:00", TAG) == 0, "Mitternacht ist 0")
pruefe(band.minuten("2026-08-29 08:30", TAG) == 510, "08:30 ist 510")
pruefe(band.minuten("2026-08-30 08:00", TAG) == 1920,
       "der Folgetag zaehlt weiter: 08:00 am 30. ist 1920")
pruefe(band.minuten(None, TAG) is None, "ohne Zeitstempel nichts")
pruefe(band.minuten("kaputt", TAG) is None, "unlesbar ergibt nichts")

print("Spuren packen")
eintraege = [
    {"von": 0, "bis": 60}, {"von": 60, "bis": 120}, {"von": 30, "bis": 90},
]
spuren = band.packen(eintraege)
pruefe(len(spuren) == 2, "drei Balken, zwei ueberschneiden sich -> zwei Spuren")
pruefe([e["von"] for e in spuren[0]] == [0, 60],
       "die anschliessenden teilen sich eine Spur")
pruefe([e["von"] for e in spuren[1]] == [30], "der ueberlappende kommt darunter")

pruefe(len(band.packen([])) == 0, "nichts ergibt keine Spur")
pruefe(len(band.packen([{"von": 0, "bis": 10}] * 3)) == 3,
       "drei gleichzeitige brauchen drei Spuren")

print("Achse")
b = band.bauen(TAG, [programmpunkt("Training", "10:15", "12:15")],
               [schicht(1, "Shuttle", "07:00", "12:45", 2, 3)])
pruefe(b["von"] == 7 * 60, "Beginn auf die volle Stunde abgerundet: "
       + b["von_uhr"])
pruefe(b["bis"] == 13 * 60, "Ende auf die volle Stunde aufgerundet: "
       + b["bis_uhr"])
pruefe(len(b["stunden"]) == 7, "sieben Stundenmarken (07 bis 13)")
pruefe(b["stunden"][0]["prozent"] == 0.0
       and b["stunden"][-1]["prozent"] == 100.0,
       "die erste sitzt links, die letzte rechts")
pruefe([s["text"] for s in b["stunden"]] ==
       ["07", "08", "09", "10", "11", "12", "13"], "mit den richtigen Zahlen")

print("Ein sehr kurzer Tag wird nicht zusammengequetscht")
kurz = band.bauen(TAG, [], [schicht(1, "Kurz", "09:00", "09:30", 1, 1)])
pruefe(kurz["bis"] - kurz["von"] >= band.MINDESTSPANNE,
       "mindestens vier Stunden Achse, sonst waere ein 30-Minuten-Balken "
       "die ganze Breite")

print("Ueber Mitternacht")
nacht = band.bauen(TAG, [], [schicht(1, "Nachtwache", "20:00", "08:00", 1, 2,
                                     tag="2026-08-30")])
pruefe(nacht["bis"] == 32 * 60, "die Achse waechst bis 32:00, also 08:00 am "
       "Folgetag")
wechsel = [s for s in nacht["stunden"] if s["tageswechsel"]]
pruefe(len(wechsel) == 1, "genau ein Tageswechsel-Strich")
pruefe(wechsel[0]["text"] == "00", "er sitzt auf Mitternacht")
pruefe([s["text"] for s in nacht["stunden"]][-1] == "08",
       "die letzte Marke heisst 08, nicht 32")
pruefe(nacht["schicht_spuren"][0][0]["breite"] > 30,
       "der Balken laeuft ueber den halben Tag")

print("Offenes Ende")
offen = band.bauen(TAG, [programmpunkt("Rennlauf", "11:30", None,
                                       roh="ab 11.30 Uhr"),
                         programmpunkt("Vorher", "08:00", "09:00")], [])
rennlauf = [x for spur in offen["programm_spuren"] for x in spur
            if x["titel"] == "Rennlauf"][0]
pruefe(rennlauf["offen"], "wird als offen gefuehrt")
pruefe(round(rennlauf["links"] + rennlauf["breite"]) == 100,
       "und laeuft bis zum rechten Rand statt ein Ende zu behaupten")
pruefe(rennlauf["bis_uhr"] == "", "es wird keine Endzeit angezeigt")

print("Ganz ohne Uhrzeit")
b = band.bauen(TAG, [programmpunkt("Siegerehrung", None, None,
                                   roh="anschließend"),
                     programmpunkt("Rennlauf", "11:30", "12:00")], [])
pruefe(len(b["ohne_zeit"]) == 1 and b["ohne_zeit"][0]["titel"] == "Siegerehrung",
       "steht getrennt daneben, nicht auf der Achse")
pruefe(all(x["titel"] != "Siegerehrung"
           for spur in b["programm_spuren"] for x in spur),
       "und taucht in keiner Spur auf")

print("Nach Serie gruppiert")
b = band.bauen(TAG, [
    programmpunkt("DHC A", "08:00", "09:00", "dhc"),
    programmpunkt("DHC B", "09:00", "10:00", "dhc"),
    programmpunkt("Kids A", "08:00", "09:00", "kids"),
], [], farben={"dhc": "#95bf0b", "kids": "#4e690f"})
pruefe(len(b["programm_spuren"]) == 2, "zwei Serien, zwei Spuren")
serien_je_spur = [{x["serie"] for x in spur} for spur in b["programm_spuren"]]
pruefe(all(len(s) == 1 for s in serien_je_spur),
       "in einer Spur steht nie mehr als eine Serie")
pruefe(b["serien"] == ["dhc", "kids"], "beide werden gemeldet")
alle = [x for spur in b["programm_spuren"] for x in spur]
pruefe(all(x["farbe"] for x in alle), "jeder Balken kennt seine Farbe")

print("Jetzt-Linie")
b = band.bauen(TAG, [], [schicht(1, "Dienst", "08:00", "18:00", 1, 1)],
               jetzt=datetime(2026, 8, 29, 13, 0))
pruefe(b["jetzt_prozent"] == 50.0, "13:00 liegt mittig zwischen 08 und 18: "
       + str(b["jetzt_prozent"]))
b = band.bauen(TAG, [], [schicht(1, "Dienst", "08:00", "18:00", 1, 1)],
               jetzt=datetime(2026, 8, 31, 13, 0))
pruefe(b["jetzt_prozent"] is None,
       "an einem anderen Tag gibt es keine Jetzt-Linie")
b = band.bauen(TAG, [], [schicht(1, "Dienst", "08:00", "18:00", 1, 1)])
pruefe(b["jetzt_prozent"] is None, "und ohne Angabe auch nicht")

print("Beschriftung nur, wenn Platz ist")
b = band.bauen(TAG, [], [
    schicht(1, "Langer Dienst", "08:00", "18:00", 1, 1),
    schicht(2, "Kurz", "08:00", "08:10", 1, 1),
])
alle = {x["titel"]: x for spur in b["schicht_spuren"] for x in spur}
pruefe(alle["Langer Dienst"]["beschriftung"] == "Langer Dienst",
       "der breite Balken traegt seinen Namen")
pruefe(alle["Kurz"]["beschriftung"] == "",
       "der schmale bleibt leer, statt zu 'Ku…' zu verstuemmeln")

print("Lueckenkennzeichnung")
b = band.bauen(TAG, [], [
    schicht(1, "Voll", "08:00", "12:00", 3, 3),
    schicht(2, "Luecke", "12:00", "16:00", 1, 4),
])
alle = {x["titel"]: x for spur in b["schicht_spuren"] for x in spur}
pruefe(alle["Voll"]["fehlt"] == 0 and alle["Luecke"]["fehlt"] == 3,
       "die Fehlzahl wird durchgereicht")

print("Nichts zu zeigen")
pruefe(band.bauen(TAG, [], []) is None, "ohne Inhalt kein Band")
pruefe(band.bauen(TAG, [programmpunkt("Nur Text", None, None)], []) is None,
       "ein Punkt ohne Uhrzeit allein ergibt auch keine Achse")

print("Balken bleiben innerhalb der Achse")
b = band.bauen(TAG, [programmpunkt("A", "08:00", "09:00"),
                     programmpunkt("B", "17:00", "18:30")],
               [schicht(1, "S", "07:30", "19:00", 1, 2)])
alle = [x for spur in b["programm_spuren"] + b["schicht_spuren"] for x in spur]
pruefe(all(x["links"] >= 0 for x in alle), "keiner beginnt links vom Rand")
pruefe(all(x["links"] + x["breite"] <= 100.01 for x in alle),
       "und keiner ragt rechts hinaus")
pruefe(all(x["breite"] > 0 for x in alle), "jeder ist sichtbar breit")

print()
if fehler:
    print("FEHLGESCHLAGEN (" + str(len(fehler)) + "):")
    for eintrag in fehler:
        print("  - " + eintrag)
else:
    print("alle Pruefungen bestanden")
sys.exit(1 if fehler else 0)
