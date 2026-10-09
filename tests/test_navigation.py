"""Die Navigation des Backoffice in kern/navigation.py – ohne Server.

    python tests/test_navigation.py

Reiter, Gruppen und Punkte (Lastenheft 2.1b): welche Seite unter welchem
Reiter steht, was markiert ist und welche Reiter ein Konto bei welcher
Veranstaltung sieht.
"""

import sys
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WURZEL))

from kern import navigation as nav  # noqa: E402
from kern.auth import Sitzung  # noqa: E402

fehler = []


def pruefe(bedingung, text):
    print(("  ok   " if bedingung else "  FEHL ") + text)
    if not bedingung:
        fehler.append(text)


def sitzung(rolle="admin", bereiche=(), verwaltung=True):
    return Sitzung(kuerzel="KK", laeuft_ab=0, token="t", konto_id=1, name="Test",
                   rolle=rolle, bereiche=tuple(bereiche), verwaltung=verwaltung)


ADMIN = sitzung()
ORGA_HELFER = sitzung("orga", ["helfer"])
ORGA_PRESSE = sitzung("orga", ["presse"])
LEITUNG = sitzung("bereichsleitung", ["helfer"])
AA = {"id": 7, "kurz": "AA 2027", "nutzt": ["kennzeichen", "presse", "helfer", "ausgabe"]}
XCO = {"id": 8, "kurz": "XCO 2027", "nutzt": ["helfer"]}

print("Unter welchem Reiter eine Seite steht")
for pfad, reiter in (("/helfer", "helfer"), ("/helfer/bereich/3", "helfer"),
                     ("/helfer/ausgabe", "ausgabe"), ("/helfer/fahrzeug/2/loeschen", "ausgabe"),
                     ("/helfer/funk", "ausgabe"), ("/helfer/material/3", "verwaltung"),
                     ("/helfer/goodies", "verwaltung"), ("/helfer/goodie/4", "verwaltung"),
                     ("/helfer/unterschriften", "verwaltung"), ("/veranstaltungen/7", "verwaltung"),
                     ("/konten", "verwaltung"), ("/kennzeichen/durchfahrt", "kennzeichen"),
                     ("/konto", ""), ("/", "")):
    pruefe(nav.reiter_von(pfad) == reiter, pfad + " → " + (reiter or "keiner"))
pruefe(nav.reiter_von("/helfer/goodiesammlung") == "helfer",
       "ein Pfad, der nur so anfängt, gehört nicht dazu")

print("Gruppen und Punkte")
GRUPPEN = [("Planen", [("/a", "Erstens", ()), ("/a/x", "Zweitens", ("/a/y",))]),
           ("Leute", [("/b", "Leute", ())])]
g = nav.gegliedert(GRUPPEN, "/a/y/3")
pruefe([x["name"] for x in g["gruppen"] if x["hier"]] == ["Planen"], "die offene Gruppe ist markiert")
pruefe([p["name"] for p in g["bereichsnav"]] == ["Erstens", "Zweitens"]
       and [p["name"] for p in g["bereichsnav"] if p["hier"]] == ["Zweitens"],
       "darunter ihre Punkte, der offene markiert – auch über einen weiteren Pfad")
g = nav.gegliedert(GRUPPEN, "/b")
pruefe(g["bereichsnav"] == [], "eine Gruppe mit nur einem Punkt hat keine Zeile darunter")
g = nav.gegliedert(GRUPPEN[:1], "/a")
pruefe(g["gruppen"] == [] and len(g["bereichsnav"]) == 2,
       "eine einzige Gruppe braucht keine eigene Zeile")
g = nav.gegliedert(GRUPPEN, "/woanders")
pruefe(not any(x["hier"] for x in g["gruppen"]) and g["bereichsnav"] == [],
       "eine fremde Seite markiert nichts")

print("Welche Reiter wer sieht")
def reiter(s, va, pfad="/helfer"):
    ziel = (nav.verwaltung(s, va) or [(None, [(None,)])])[0][1][0][0]
    return [b["schluessel"] for b in nav.bereiche(pfad, s, nutzt=va["nutzt"], verwaltung_ziel=ziel)]
pruefe(reiter(ADMIN, AA) == ["kennzeichen", "presse", "helfer", "ausgabe", "verwaltung"],
       "der Admin bei der AA: alles")
pruefe(reiter(ADMIN, XCO) == ["helfer", "verwaltung"],
       "beim XCO nur, was er nutzt – Helfer, dazu die Verwaltung")
pruefe(reiter(ORGA_PRESSE, AA) == ["presse"], "eine Orga-Person der Presse: nur die Presse")
pruefe(reiter(ORGA_PRESSE, XCO) == [], "und beim XCO gar nichts")
pruefe(reiter(LEITUNG, AA) == ["helfer"], "eine Bereichsleitung: nur Helfer, keine Ausgabe")
pruefe([b["schluessel"] for b in nav.bereiche("/helfer")] == ["kennzeichen", "presse", "helfer", "ausgabe"],
       "ohne Sitzung und Veranstaltung alle Bereiche, aber keine Verwaltung")

print("Die Verwaltung einer Veranstaltung")
g = nav.verwaltung(ADMIN, XCO)
pruefe([name for name, _ in g] == ["XCO 2027", "Alle Veranstaltungen", "Konten"],
       "die gewählte, alle, die Konten")
pruefe([n for _, n, _ in g[0][1]] == ["Allgemein", "Goodies & Verpflegung", "Import", "Zeitplan-Abruf"],
       "beim XCO ohne Materialausgabe kein Material und kein Tablet")
pruefe([n for _, n, _ in nav.verwaltung(ADMIN, AA)[0][1]][-2:] == ["Material", "Tablet"],
       "bei der AA mit")
pruefe("Konten" not in [name for name, _ in nav.verwaltung(ORGA_HELFER, AA)],
       "die Konten nur für Admins")
pruefe(nav.verwaltung(LEITUNG, AA) == [], "eine Bereichsleitung hat keine Verwaltung")
pruefe(nav.verwaltung(ORGA_PRESSE, AA) == [], "wer den Helferbereich nicht sieht, auch nicht")
ohne_dienst = nav.verwaltung(sitzung(verwaltung=False), AA)
pruefe([name for name, _ in ohne_dienst] == ["AA 2027"] and ohne_dienst[0][1][0][1] != "Allgemein",
       "ohne gemeinsamen Dienst nur, was der Helferbereich selbst kann")

print("Wohin nach dem Wechsel der Veranstaltung")
for pfad, ziel in (("/helfer/bereiche", "/helfer/bereiche"), ("/helfer/bereich/5", "/helfer"),
                   ("/helfer/schicht/2/aendern", "/helfer"), ("/helfer/ausgabe/3/zurueck", "/helfer/ausgabe"),
                   ("/veranstaltungen/7", "/veranstaltungen/{id}"), ("/konten/4", "/veranstaltungen")):
    pruefe(nav._weiter(pfad) == ziel, pfad + " → " + ziel)

print()
if fehler:
    print("FEHLGESCHLAGEN (" + str(len(fehler)) + "):")
    for eintrag in fehler:
        print("  - " + eintrag)
    sys.exit(1)
print("alle Pruefungen bestanden")
