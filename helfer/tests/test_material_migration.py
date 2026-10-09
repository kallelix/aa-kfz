"""Die Übernahme von Funk und Schlüssel in die Materialausgabe (Migration 0014).

    python helfer/tests/test_material_migration.py

Eine Datenbank im Stand vor 3.8 – Ausleihen mit drei festen Spalten,
Schlüsselvorgänge, Unterschriften zu beiden, die Vorbelegung in den
Einstellungen –, dann die Migration darüber. Danach steht dasselbe als
Material, Vorgänge und Posten da, und die Unterschriften zeigen auf die neuen
Vorgänge.
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WURZEL))
sys.path.insert(0, str(WURZEL.parent))
from kern import testdb  # noqa: E402

fehler = []


def pruefe(bedingung, text):
    print(("  ok   " if bedingung else "  FEHL ") + text)
    if not bedingung:
        fehler.append(text)


db_url = testdb.wegwerf("helfer_material_alt")
os.environ["DATABASE_URL"] = db_url

from kern.db import migrieren  # noqa: E402
from app import db, unterschriften  # noqa: E402

ORDNER = WURZEL / "app" / "migrationen"
alt = Path(tempfile.mkdtemp())
for datei in sorted(ORDNER.glob("*.sql")):
    if datei.name < "0014":
        shutil.copy(datei, alt / datei.name)
db.VERANSTALTUNGEN.init()
migrieren(db_url, "helfer", alt)
shutil.rmtree(alt)


def sql(text, *parameter):
    return testdb.abfrage(db_url, "helfer", text, parameter)


VA = db.VERANSTALTUNGEN.anlegen({"name": "Die absolute Abfahrt 2026", "kurz": "AA 2026",
                                 "beginn": "2026-08-28", "ende": "2026-08-30", "ort": "Ilmenau"})
NUR_HELFER = db.VERANSTALTUNGEN.anlegen({"name": "XCO 2026", "kurz": "XCO 2026",
                                         "beginn": "2026-09-12", "ende": "2026-09-13",
                                         "ort": "Ilmenau", "nutzt": ["helfer"]})
ANNA = sql("INSERT INTO helfer (name, email, schluessel, angelegt_am) VALUES"
           " ('Anna Berg', 'anna@example.org', 'anna berg|anna@example.org', '2026-08-01 10:00')"
           " RETURNING id")[0][0]
sql("INSERT INTO einstellung (schluessel, wert, geaendert_am) VALUES"
    " ('vorgabe_headset', '1', '2026-08-01 10:00')")
TEILWEISE = sql("INSERT INTO ausleihe (veranstaltung_id, helfer_id, datum, funke, headset,"
                " ersatzakku, funke_zurueck, headset_zurueck, ersatzakku_zurueck,"
                " ausgegeben_am, ausgegeben_von) VALUES (?, ?, '2026-08-29', 1, 1, 2, 1, 0, 1,"
                " '2026-08-29 07:00', 'KK') RETURNING id", VA, ANNA)[0][0]
ZURUECK = sql("INSERT INTO ausleihe (veranstaltung_id, helfer_id, funke, funke_zurueck,"
              " ausgegeben_am, zurueck_am, zurueck_von) VALUES (?, ?, 1, 1,"
              " '2026-08-28 07:00', '2026-08-28 19:00', 'MS') RETURNING id", VA, ANNA)[0][0]
WAGEN = sql("INSERT INTO fahrzeug (kennzeichen, kennzeichen_norm, name, angelegt_am)"
            " VALUES ('IL-A 1', 'ILA1', 'Halter Hans', '2026-08-01 10:00') RETURNING id")[0][0]
SCHLUESSEL = sql("INSERT INTO schluessel (veranstaltung_id, fahrzeug_id, name, bemerkung,"
                 " ausgegeben_am, ausgegeben_von) VALUES (?, ?, 'Max Fahrer', 'Shuttle 1',"
                 " '2026-08-29 06:30', 'KK') RETURNING id", VA, WAGEN)[0][0]
for art, vorgang in (("material", TEILWEISE), ("schluessel", SCHLUESSEL)):
    sql("INSERT INTO unterschrift (art, vorgang_id, richtung, titel, wortlaut, person,"
        " angefordert_am, laeuft_ab_am, unterschrieben_am, bild) VALUES (?, ?, 'ausgabe',"
        " 'damals', 'wie damals', 'Anna Berg', '2026-08-29 07:00', '2026-08-29 07:05',"
        " '2026-08-29 07:01', 'M1,1L2,2') ", art, vorgang)

print("Migration 0014")
neu = db.init()
pruefe(any("0014" in n for n in neu), "läuft: " + str(neu))

print("Materialien")
mat = {z["name"]: z for z in sql("SELECT * FROM material WHERE veranstaltung_id = ?", VA)}
pruefe(sorted(mat) == ["Ersatzakku", "Fahrzeugschlüssel", "Funkgerät", "Headset"],
       "die vier bisherigen für die Abfahrt")
pruefe(mat["Funkgerät"]["vorgabe"] == 1 and mat["Headset"]["vorgabe"] == 1
       and mat["Ersatzakku"]["vorgabe"] == 0,
       "die Vorbelegung kommt aus den Einstellungen, sonst die alte Vorgabe")
pruefe(mat["Fahrzeugschlüssel"]["erfassen"] == "kennzeichen"
       and all(m["rueckgabe"] == 1 and m["unterschrift"] == 1 for m in mat.values()),
       "der Schlüssel mit Kennzeichen, alle mit Rückgabe und Unterschrift")
pruefe(not sql("SELECT 1 FROM material WHERE veranstaltung_id = ?", NUR_HELFER),
       "eine Veranstaltung ohne Ausgabe bekommt keine")

print("Vorgänge und Posten")
vorgaenge = sql("SELECT * FROM ausgabe ORDER BY ausgegeben_am")
pruefe(len(vorgaenge) == 3, "drei Vorgänge: zwei Ausleihen, ein Schlüssel")


def posten(ausgabe_id):
    return {z["material"]: (z["menge"], z["zurueck"], z["nummer"]) for z in sql(
        "SELECT m.name AS material, p.* FROM ausgabe_posten p JOIN material m"
        " ON m.id = p.material_id WHERE p.ausgabe_id = ?", ausgabe_id)}


teilweise = next(v for v in vorgaenge if v["datum"] == "2026-08-29")
pruefe(teilweise["helfer_id"] == ANNA and teilweise["name"] == "Anna Berg"
       and teilweise["zurueck_am"] is None and teilweise["ausgegeben_von"] == "KK",
       "die offene Ausleihe: Anna, noch draußen, mit Kürzel")
pruefe(posten(teilweise["id"]) == {"Funkgerät": (1, 1, ""), "Headset": (1, 0, ""),
                                   "Ersatzakku": (2, 1, "")},
       "mit Mengen und dem, was schon zurück ist: " + str(posten(teilweise["id"])))
zurueck = next(v for v in vorgaenge if v["zurueck_von"] == "MS")
pruefe(zurueck["zurueck_am"] == "2026-08-28 19:00" and posten(zurueck["id"]) == {"Funkgerät": (1, 1, "")},
       "die zurückgegebene bleibt zurückgegeben")
schluessel = next(v for v in vorgaenge if v["helfer_id"] is None)
pruefe(schluessel["name"] == "Max Fahrer" and schluessel["bemerkung"] == "Shuttle 1"
       and posten(schluessel["id"]) == {"Fahrzeugschlüssel": (1, 0, "IL-A 1")},
       "der Schlüssel: Max, mit Kennzeichen, noch draußen")
pruefe(sql("SELECT fahrzeug_id FROM ausgabe_posten WHERE ausgabe_id = ?", schluessel["id"])[0][0] == WAGEN,
       "und am Fahrzeugstamm")

print("Unterschriften")
belege = sql("SELECT art, vorgang_id FROM unterschrift ORDER BY id")
pruefe([(z["art"], z["vorgang_id"]) for z in belege] == [("material", teilweise["id"]),
                                                          ("material", schluessel["id"])],
       "beide zeigen auf die neuen Vorgänge, der Schlüssel ist jetzt Material")
titel, text, person = unterschriften.wortlaut("material", schluessel["id"], "ausgabe")
pruefe("Fahrzeugschlüssel IL-A 1" in text and person == "Max Fahrer",
       "der Wortlaut lässt sich neu bilden: " + text)

print("Aufgeräumt")
tabellen = {z["table_name"] for z in testdb.abfrage(
    db_url, "helfer", "SELECT table_name FROM information_schema.tables WHERE table_schema = 'helfer'")}
pruefe("ausleihe" not in tabellen and "schluessel" not in tabellen, "die alten Tabellen sind weg")
pruefe(not sql("SELECT 1 FROM einstellung WHERE schluessel LIKE 'vorgabe_%'"),
       "die alte Vorbelegung auch")

print()
if fehler:
    print("FEHLGESCHLAGEN (" + str(len(fehler)) + "):")
    for eintrag in fehler:
        print("  - " + eintrag)
else:
    print("alle Pruefungen bestanden")
sys.exit(1 if fehler else 0)
