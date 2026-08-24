"""Zeitplan-Abruf: Tabellenwahl, Zeiten, Zusammenführen (Schritt 6).

    python helfer/tests/test_zeitplan.py

Läuft ohne Netz. Die Seiten unten sind nachgebaut, nicht heruntergeladen –
aber mit demselben Aufbau wie die echten: die DHC-Seite hat zwei Zeitpläne
unter verschiedenen Überschriften, beide Seiten haben Cookie-Tabellen am Ende,
und in den Zellen steckt Markup.
"""

import os
import pathlib
import sys
import tempfile

WURZEL = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WURZEL))

os.environ["DB_PATH"] = str(pathlib.Path(
    tempfile.mkdtemp(prefix="helfer-zeitplan-")) / "helfer.db")
os.environ.setdefault("TAGE", "2026-08-28,2026-08-29,2026-08-30")

from app import config, db, zeitplan  # noqa: E402

fehler = []


def pruefe(bedingung, text):
    print(("  ok   " if bedingung else "  FEHL ") + text)
    if not bedingung:
        fehler.append(text)


def seite(*bloecke):
    return ("<!doctype html><html><head><title>Zeitplan</title></head><body>"
            "<h2>Suche</h2>" + "".join(bloecke) +
            "<h2>Cookies und Dienste</h2>"
            "<table><tr><td>Name</td><td>Google Analytics</td></tr>"
            "<tr><td>Anbieter</td><td>google.com</td></tr></table>"
            "<table><tr><td>Name</td><td>YouTube</td></tr>"
            "<tr><td>Anbieter</td><td>Google</td></tr></table>"
            "</body></html>")


def tabelle(*zeilen, kopf=("Tag", "Beschreibung", "Zeit")):
    html = "<table><thead><tr>" + "".join(
        "<th>" + z + "</th>" for z in kopf) + "</tr></thead><tbody>"
    for zeile in zeilen:
        html += "<tr>" + "".join(
            "<td><span>" + z + "</span></td>" for z in zeile) + "</tr>"
    return html + "</tbody></table>"


ALLGEMEIN = tabelle(
    ("Freitag", "Startnummerausgabe", "09.00 - 18.00 Uhr"),
    ("", "Track Walk", "10.00 - 12.00 Uhr"),
    ("", "Offizielles Training", "12.00 - 18.00 Uhr"),
    ("Samstag", "Seeding Run", "ab 13.30 Uhr"),
    ("Sonntag", "Rennlauf", "ab 11.30 Uhr"),
    ("", "Siegerehrung", "ca. 30 min nach Rennschluss"),
)
WILLINGEN = tabelle(
    ("Freitag", "Startnummerausgabe", "09.00 - 18.00 Uhr"),
    ("", "Track Walk", "11.00 - 13.00 Uhr"),
    ("", "Offizielles Training", "13.00 - 18.00 Uhr"),
)

DHC = seite("<h1>DHC Zeitplan</h1>", "<h2>allgemein</h2>", ALLGEMEIN,
            "<h2>Willingen</h2>", WILLINGEN)

KIDS = seite("<h1>Zeitplan</h1>", "<h2>Zeitplan allgemein:</h2>",
             tabelle(("Freitag", "Startnummernausgabe", "17.00 - 19.00 Uhr"),
                     ("Samstag", "Race 2", "ab circa 14.00 Uhr"),
                     ("", "Siegerehrung", "anschließend"),
                     kopf=("Tag", "Bezeichnung", "Zeit")))

db.init()

print("Tabellen erkennen")
gefunden = zeitplan.abschnitte(DHC)
pruefe(len(gefunden) == 4, "vier Tabellen insgesamt: " + str(len(gefunden)))
zeitplaene = [(k, z) for k, z in gefunden if zeitplan.ist_zeitplan(z)]
pruefe(len(zeitplaene) == 2, "davon zwei Zeitplaene")
pruefe([k for k, _ in zeitplaene] == ["allgemein", "Willingen"],
       "mit ihren Ueberschriften: " + str([k for k, _ in zeitplaene]))

print("Die richtige von zwei Tabellen")
kopf, zeilen = zeitplan.tabelle_waehlen(DHC, "allgemein")
pruefe(kopf == "allgemein", "'allgemein' wird gewaehlt")
pruefe(any("10.00 - 12.00 Uhr" in z for z in zeilen[2]),
       "und liefert deren Zeiten, nicht die von Willingen")

kopf, _ = zeitplan.tabelle_waehlen(DHC, "Willingen")
pruefe(kopf == "Willingen", "'Willingen' waere auch waehlbar")

print("Lieber abbrechen als raten")
try:
    zeitplan.tabelle_waehlen(DHC, "gibtesnicht")
    pruefe(False, "unbekannter Abschnitt muss abbrechen")
except zeitplan.Fehler as f:
    pruefe("Keine Tabelle" in str(f), "unbekannter Abschnitt bricht ab")
    pruefe("'allgemein'" in str(f) and "'Willingen'" in str(f),
           "und nennt, was es gibt")

doppelt = seite("<h2>allgemein</h2>", ALLGEMEIN, "<h2>allgemein</h2>", WILLINGEN)
try:
    zeitplan.tabelle_waehlen(doppelt, "allgemein")
    pruefe(False, "zwei gleiche Ueberschriften muessen abbrechen")
except zeitplan.Fehler as f:
    pruefe("nicht eindeutig" in str(f),
           "zwei gleiche Ueberschriften brechen ab")

try:
    zeitplan.tabelle_waehlen(seite("<h2>allgemein</h2>"), "allgemein")
    pruefe(False, "ohne Zeitplantabelle muss es abbrechen")
except zeitplan.Fehler as f:
    pruefe("keine Tabelle mit Tag- und" in str(f),
           "eine Seite ohne Zeitplan bricht ab")

print("Cookie-Tabellen")
pruefe(not zeitplan.ist_zeitplan([["Name", "YouTube"], ["Anbieter", "Google"]]),
       "werden nicht fuer einen Zeitplan gehalten")

print("Zeiten lesen")
for roh, erwartet in [
        ("09.00 - 18.00 Uhr", ("2026-08-28 09:00", "2026-08-28 18:00")),
        ("10.00 - 12.00 Uhr", ("2026-08-28 10:00", "2026-08-28 12:00")),
        ("ab 13.30 Uhr", ("2026-08-28 13:30", None)),
        ("ab circa 14.00 Uhr", ("2026-08-28 14:00", None)),
        ("anschließend", (None, None)),
        ("ca. 30 min nach Rennschluss", (None, None)),
        ("20.00 - 02.00 Uhr", ("2026-08-28 20:00", "2026-08-29 02:00")),
]:
    pruefe(zeitplan.zeiten("2026-08-28", roh) == erwartet,
           repr(roh) + " -> " + str(zeitplan.zeiten("2026-08-28", roh)))

print("Auswerten")
ergebnis = zeitplan.auswerten("dhc", *zeitplan.tabelle_waehlen(DHC, "allgemein"))
pruefe(len(ergebnis.eintraege) == 6, "sechs Eintraege")
nach_titel = {e.titel: e for e in ergebnis.eintraege}
pruefe(nach_titel["Track Walk"].tag_roh == "Freitag",
       "die leere Tagspalte erbt den Tag von oben")
pruefe(nach_titel["Track Walk"].datum == "2026-08-28",
       "Freitag wird zum 28.08.2026")
pruefe(nach_titel["Rennlauf"].datum == "2026-08-30", "Sonntag zum 30.08.2026")
pruefe(nach_titel["Seeding Run"].ende is None, "'ab 13.30' hat kein Ende")
pruefe(nach_titel["Siegerehrung"].beginn is None,
       "'ca. 30 min nach Rennschluss' hat gar keine Zeit")
pruefe(nach_titel["Siegerehrung"].zeit_roh == "ca. 30 min nach Rennschluss",
       "der Wortlaut bleibt erhalten")
pruefe(not ergebnis.probleme, "nichts wurde verworfen")
pruefe(len(ergebnis.hinweise) == 1,
       "eine Zeile ohne Uhrzeit ist ein Hinweis, kein Problem")

print("Unbekannter Wochentag")
mit_montag = seite("<h2>allgemein</h2>", tabelle(
    ("Freitag", "Aufbau", "09.00 - 18.00 Uhr"),
    ("Montag", "Abbau", "09.00 - 12.00 Uhr")))
teil = zeitplan.auswerten("dhc", *zeitplan.tabelle_waehlen(mit_montag, "allgemein"))
pruefe(len(teil.eintraege) == 1, "der Montag faellt raus")
pruefe(any("Montag" in p for p in teil.probleme), "und wird gemeldet")

print("Uebernehmen: erster Lauf")
bericht = zeitplan.uebernehmen(ergebnis, "test")
pruefe(len(bericht["neu"]) == 6, "sechs neue Eintraege")
pruefe(not bericht["geaendert"], "nichts geaendert")
pruefe(len(db.programm(serie="dhc")) == 6, "sechs stehen in der Datenbank")

print("Uebernehmen: zweiter Lauf, nichts geaendert")
bericht = zeitplan.uebernehmen(
    zeitplan.auswerten("dhc", *zeitplan.tabelle_waehlen(DHC, "allgemein")), "test")
pruefe(zeitplan.unveraendert(bericht), "wird als unveraendert gemeldet")
pruefe(len(db.programm(serie="dhc")) == 6, "und legt nichts doppelt an")

print("Uebernehmen: die Website aendert eine Zeit")
geaendert = seite("<h2>allgemein</h2>", tabelle(
    ("Freitag", "Startnummerausgabe", "09.00 - 18.00 Uhr"),
    ("", "Track Walk", "10.30 - 12.30 Uhr"),
    ("", "Offizielles Training", "12.00 - 18.00 Uhr"),
    ("Samstag", "Seeding Run", "ab 13.30 Uhr"),
    ("Sonntag", "Rennlauf", "ab 11.30 Uhr"),
    ("", "Siegerehrung", "ca. 30 min nach Rennschluss")))
bericht = zeitplan.uebernehmen(
    zeitplan.auswerten("dhc", *zeitplan.tabelle_waehlen(geaendert, "allgemein")),
    "test")
pruefe(len(bericht["geaendert"]) == 1, "genau eine Aenderung")
pruefe("10:00–12:00 wird 10.30 - 12.30 Uhr" in bericht["geaendert"][0],
       "alter und neuer Wert stehen drin: " + bericht["geaendert"][0])
walk = [z for z in db.programm(serie="dhc") if z["titel"] == "Track Walk"][0]
pruefe(walk["beginn"] == "2026-08-28 10:30", "die neue Zeit steht drin")

print("Was von Hand geaendert wurde, gewinnt")
con = db.verbinden()
with con:
    con.execute("UPDATE programm SET von_hand = 1, beginn = ?, ende = ?"
                " WHERE id = ?",
                ("2026-08-28 09:00", "2026-08-28 11:00", walk["id"]))
con.close()
bericht = zeitplan.uebernehmen(
    zeitplan.auswerten("dhc", *zeitplan.tabelle_waehlen(DHC, "allgemein")), "test")
pruefe(len(bericht["geschuetzt"]) == 1, "die Abweichung wird gemeldet")
pruefe("deine Fassung bleibt" in bericht["geschuetzt"][0], "mit klarer Ansage")
walk = [z for z in db.programm(serie="dhc") if z["titel"] == "Track Walk"][0]
pruefe(walk["beginn"] == "2026-08-28 09:00", "und nichts wird ueberschrieben")

print("Was verschwindet, bleibt sichtbar")
kuerzer = seite("<h2>allgemein</h2>", tabelle(
    ("Freitag", "Startnummerausgabe", "09.00 - 18.00 Uhr"),
    ("Sonntag", "Rennlauf", "ab 11.30 Uhr")))
bericht = zeitplan.uebernehmen(
    zeitplan.auswerten("dhc", *zeitplan.tabelle_waehlen(kuerzer, "allgemein")),
    "test")
pruefe(len(bericht["entfallen"]) == 4, "vier Eintraege sind entfallen: "
       + str(len(bericht["entfallen"])))
pruefe(len(db.programm(serie="dhc")) == 6, "geloescht wurde nichts")
pruefe(len(db.programm(serie="dhc", mit_entfallenen=False)) == 2,
       "aber nur zwei gelten noch")

print("Und taucht wieder auf")
bericht = zeitplan.uebernehmen(
    zeitplan.auswerten("dhc", *zeitplan.tabelle_waehlen(DHC, "allgemein")), "test")
pruefe(len(bericht["zurueck"]) >= 3, "die entfallenen leben wieder auf")
pruefe(len(db.programm(serie="dhc", mit_entfallenen=False)) == 6,
       "alle sechs gelten wieder")

print("Zweite Serie stoert die erste nicht")
kids = zeitplan.auswerten("kids", *zeitplan.tabelle_waehlen(KIDS, "allgemein"))
pruefe(len(kids.eintraege) == 3, "drei Eintraege beim Kids Cup")
pruefe(kids.eintraege[1].beginn == "2026-08-29 14:00",
       "'ab circa 14.00 Uhr' wird gelesen")
zeitplan.uebernehmen(kids, "test")
pruefe(len(db.programm(serie="dhc")) == 6, "der DHC bleibt bei sechs")
pruefe(len(db.programm(serie="kids")) == 3, "der Kids Cup hat drei")
pruefe(len(db.programm()) == 9, "zusammen neun")

print("Sortierung")
alle = db.programm(serie="kids")
pruefe(alle[-1]["titel"] == "Siegerehrung",
       "der Eintrag ohne Uhrzeit steht hinten, nicht vorn")

print("Abrufprotokoll")
pruefe(db.letzter_erfolg("dhc") is not None, "der letzte Erfolg ist vermerkt")
db.abruf_vermerken("dhc", False, "Server antwortet mit HTTP 500", "", "test")
pruefe(db.abrufe(1)[0]["erfolg"] == 0, "ein Fehlschlag wird vermerkt")
pruefe(db.letzter_erfolg("dhc")["erfolg"] == 1,
       "und ueberschreibt den letzten Erfolg nicht")

print("Kein Netz im Test")
try:
    zeitplan.holen("file:///etc/passwd")
    pruefe(False, "file:// muss abgewiesen werden")
except zeitplan.Fehler as f:
    pruefe("Nur http und https" in str(f), "file:// wird abgewiesen")

print()
if fehler:
    print("FEHLGESCHLAGEN (" + str(len(fehler)) + "):")
    for eintrag in fehler:
        print("  - " + eintrag)
else:
    print("alle Pruefungen bestanden")
sys.exit(1 if fehler else 0)
