/* Python und JavaScript müssen beim Suchen dasselbe tun.
 *
 *     node tests/test_suchen_js.js
 *
 * Der durchsuchbare Text wird in Python gebaut (kern/suchen.py), gefiltert
 * wird im Browser (kern/static/suchtext.js). Laufen die beiden auseinander,
 * findet die Liste etwas anderes als die Datenbank – und niemand merkt es,
 * weil beide für sich plausibel aussehen.
 *
 * Die erwarteten Werte stehen nicht hier, sondern kommen aus Python: dieses
 * Skript wird von tests/test_suchen.py mit ihnen aufgerufen. Ohne Argument
 * prüft es nur sich selbst gegen die Fälle unten.
 */
"use strict";

const pfad = require("path");
const s = require(pfad.join(__dirname, "..", "kern", "static", "suchtext.js"));

let fehler = 0;

function pruefe(bedingung, text) {
  console.log((bedingung ? "  ok   " : "  FEHL ") + text);
  if (!bedingung) {
    fehler += 1;
  }
}

/* Von Python gereicht: [[eingabe, erwartete_varianten], …] */
const argument = process.argv[2];
if (argument) {
  const faelle = JSON.parse(argument);
  for (const [eingabe, erwartet] of faelle) {
    const bekommen = s.varianten(eingabe);
    pruefe(
      JSON.stringify(bekommen) === JSON.stringify(erwartet),
      JSON.stringify(eingabe) + " -> " + JSON.stringify(bekommen) +
        (JSON.stringify(bekommen) === JSON.stringify(erwartet)
          ? ""
          : " statt " + JSON.stringify(erwartet))
    );
  }
} else {
  const heu = s.suchtext("Öztürk Müller", "oe@example.org");
  for (const eingabe of ["Öztürk", "öztürk", "OEZTUERK", "Ozturk", "Müller",
                         "mueller", "Muller"]) {
    pruefe(s.passt(heu, eingabe), JSON.stringify(eingabe) + " findet den Eintrag");
  }
  pruefe(!s.passt(heu, "Meier"), "\"Meier\" findet ihn nicht");
  pruefe(s.passt(heu, "  "), "ein leerer Begriff filtert nicht");
}

console.log("");
if (fehler > 0) {
  console.log("FEHLGESCHLAGEN (" + fehler + ")");
  process.exit(1);
}
console.log("alle Pruefungen bestanden");
