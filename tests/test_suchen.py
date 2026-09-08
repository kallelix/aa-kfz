"""Suchen mit Umlauten – die Regel und der Abgleich mit JavaScript.

    python tests/test_suchen.py

Ohne Server und ohne Datenbank. Was hier geprüft wird, ist die Umformung
selbst: dass beide Seiten einer Suche dieselbe bekommen, und dass Python und
JavaScript sie gleich vornehmen.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WURZEL))

from kern import suchen  # noqa: E402

fehler = []


def pruefe(bedingung, text):
    print(("  ok   " if bedingung else "  FEHL ") + text)
    if not bedingung:
        fehler.append(text)


# Der Fall aus dem Betrieb: ein getippter Umlaut fand nichts.
NAME = "Öztürk Müller"
HEU = suchen.suchtext(NAME, "oe@example.org")

print("Wie der Name auch geschrieben wird, er wird gefunden")
for eingabe in ("Öztürk", "öztürk", "ÖZTÜRK", "OEZTUERK", "oeztuerk",
                "Ozturk", "ozturk", "Müller", "mueller", "Muller",
                "türk", "tuerk", "turk"):
    pruefe(suchen.passt(HEU, eingabe), repr(eingabe))

print("Und was nicht passt, passt nicht")
for eingabe in ("Meier", "Schmidt", "zzz"):
    pruefe(not suchen.passt(HEU, eingabe), repr(eingabe))
pruefe(suchen.passt(HEU, "   "), "ein leerer Begriff filtert gar nicht")

print("Das scharfe S ebenso")
strasse = suchen.suchtext("Bahnhofstraße")
pruefe(suchen.passt(strasse, "straße") and suchen.passt(strasse, "strasse"),
       "„Straße“ und „Strasse“ finden einander")

print("Andere Diakritika fallen auch")
pruefe(suchen.passt(suchen.suchtext("Renée Dvořák"), "renee dvorak"),
       "„Renée Dvořák“ ist als „renee dvorak“ zu finden")

print("Der durchsuchbare Text traegt beide Schreibweisen")
pruefe(suchen.varianten("Müller") == ["mueller", "muller"],
       "mit Umlaut zwei: " + str(suchen.varianten("Müller")))
pruefe(suchen.varianten("Meier") == ["meier"],
       "ohne Umlaut eine: " + str(suchen.varianten("Meier")))
pruefe(suchen.varianten("") == [] and suchen.varianten(None) == [],
       "und aus nichts wird keine")

print("Leerraum wird eingeebnet")
pruefe(suchen.varianten("  Anna   Berg  ") == ["anna berg"],
       "mehrfache Leerzeichen und Raender: "
       + str(suchen.varianten("  Anna   Berg  ")))

# --- Abgleich mit JavaScript -------------------------------------------------
print("Python und JavaScript formen gleich um")
if shutil.which("node") is None:
    print("  ---  node nicht gefunden, Abgleich uebersprungen")
else:
    faelle = [
        "Öztürk", "öztürk", "ÖZTÜRK", "Müller", "mueller", "Muller",
        "Bahnhofstraße", "Renée Dvořák", "  Anna   Berg  ", "Meier",
        "", "IL-A 123", "Groß-Gerau", "Café", "Ærø",
    ]
    erwartet = [[f, suchen.varianten(f)] for f in faelle]
    ergebnis = subprocess.run(
        ["node", str(WURZEL / "tests" / "test_suchen_js.js"),
         json.dumps(erwartet, ensure_ascii=False)],
        capture_output=True, text=True, encoding="utf-8")
    for zeile in (ergebnis.stdout or "").splitlines():
        if zeile.strip():
            print("  " + zeile.strip())
    pruefe(ergebnis.returncode == 0,
           "JavaScript kommt auf dieselben Schreibweisen wie Python")

print()
if fehler:
    print("FEHLGESCHLAGEN (" + str(len(fehler)) + "):")
    for eintrag in fehler:
        print("  - " + eintrag)
    sys.exit(1)
print("alle Pruefungen bestanden")
