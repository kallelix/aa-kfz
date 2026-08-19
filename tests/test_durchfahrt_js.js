/* Testet die Filterlogik der Durchfahrtsliste – dieselbe Datei, die der
 * Browser lädt.
 *
 *     node tests/test_durchfahrt_js.js
 *
 * Ohne `document` überspringt durchfahrt.js die DOM-Anbindung und exportiert
 * nur die beiden reinen Funktionen.
 */
"use strict";

const path = require("path");
const { kfzNormalisieren, passt, vergleiche } = require(
  path.join(__dirname, "..", "app", "static", "durchfahrt.js")
);

const fehler = [];

function pruefe(bedingung, text) {
  console.log((bedingung ? "  ok   " : "  FEHL ") + text);
  if (!bedingung) {
    fehler.push(text);
  }
}

console.log("Normalisierung");
[
  ["ka-xy 123", "KAXY123"],
  ["KA XY 123", "KAXY123"],
  ["kaxy123", "KAXY123"],
  ["  M-JS 2000  ", "MJS2000"],
  ["HH-DO 4", "HHDO4"],
  ["-", ""],
  ["", ""],
  [null, ""],
  ["Öztürk", "ÖZTÜRK"],
].forEach(function (paar) {
  const ergebnis = kfzNormalisieren(paar[0]);
  pruefe(ergebnis === paar[1], JSON.stringify(paar[0]) + " -> " + JSON.stringify(ergebnis));
});

// So, wie der Server sie in die data-Attribute schreibt.
const BERGER = { name: "andrea berger", kfz: "KAAB101" };
const OEZTUERK = { name: "dennis öztürk", kfz: "HHDO4" };
const OHNE_KFZ = { name: "eva ohnewagen", kfz: "" };

console.log("Leere Suche");
["", "   ", null, undefined].forEach(function (suche) {
  pruefe(passt(BERGER, suche), "leere Eingabe " + JSON.stringify(suche) + " zeigt alles");
});

console.log("Namenssuche");
[
  ["berger", true],
  ["BERGER", true],
  ["Berger", true],
  ["andrea", true],
  ["andrea berger", true],
  ["rge", true],
  ["  berger  ", true],
  ["öztürk", false],
  ["gibtesnicht", false],
].forEach(function (paar) {
  pruefe(passt(BERGER, paar[0]) === paar[1],
         "Berger + " + JSON.stringify(paar[0]) + " -> " + paar[1]);
});

pruefe(passt(OEZTUERK, "öztürk"), "Umlaute im Namen werden gefunden");
pruefe(passt(OEZTUERK, "ÖZTÜRK"), "auch in Großschrift");
pruefe(passt(OEZTUERK, "Dennis"), "Vorname wird gefunden");

console.log("Kennzeichensuche, trennzeichentolerant");
[
  ["KA-AB 101", true],
  ["kaab101", true],
  ["KAAB101", true],
  ["ka ab 101", true],
  ["KA-AB-101", true],
  ["ka.ab/101", true],
  ["ab101", true],
  ["101", true],
  ["HHDO4", false],
  ["KAAB102", false],
].forEach(function (paar) {
  pruefe(passt(BERGER, paar[0]) === paar[1],
         "Berger + " + JSON.stringify(paar[0]) + " -> " + paar[1]);
});

pruefe(passt(OEZTUERK, "hhdo4"), "hhdo4 findet HH-DO 4");
pruefe(passt(OEZTUERK, "hh do 4"), "hh do 4 auch");
pruefe(!passt(BERGER, "hhdo4"), "und trifft nicht den falschen");

console.log("Sonderfaelle");
pruefe(!passt(BERGER, "-"), "ein blosser Bindestrich trifft nicht alles");
pruefe(!passt(BERGER, "---"), "mehrere auch nicht");
pruefe(!passt(BERGER, "/ ."), "Trennzeichen gemischt ebenso wenig");
pruefe(!passt(OHNE_KFZ, "kaab101"), "Zeile ohne Kennzeichen wird nicht zufaellig getroffen");
pruefe(passt(OHNE_KFZ, "ohnewagen"), "ueber den Namen aber schon");
pruefe(passt(OHNE_KFZ, ""), "und bei leerer Suche steht sie da");

console.log("Sortierung");

function sortiert(werte, absteigend) {
  return werte.slice().sort(function (a, b) {
    return vergleiche(a, b, absteigend);
  });
}

pruefe(
  JSON.stringify(sortiert(["Vogt", "Berger", "Öztürk", "Ackermann"], false)) ===
    JSON.stringify(["Ackermann", "Berger", "Öztürk", "Vogt"]),
  "Umlaute sortieren beim Grundbuchstaben, nicht hinter Z: " +
    sortiert(["Vogt", "Berger", "Öztürk", "Ackermann"], false).join(", ")
);

pruefe(
  JSON.stringify(sortiert(["Berger", "Ackermann"], true)) ===
    JSON.stringify(["Berger", "Ackermann"]),
  "absteigend dreht um"
);

pruefe(
  JSON.stringify(sortiert(["KA-AB 10", "KA-AB 2", "KA-AB 1"], false)) ===
    JSON.stringify(["KA-AB 1", "KA-AB 2", "KA-AB 10"]),
  "Zahlen im Kennzeichen werden als Zahlen verglichen: " +
    sortiert(["KA-AB 10", "KA-AB 2", "KA-AB 1"], false).join(", ")
);

pruefe(vergleiche("berger", "Berger") === 0, "Gross- und Kleinschreibung ist egal");
pruefe(vergleiche("Ackermann", "Berger") < 0, "A vor B");
pruefe(vergleiche("Berger", "Ackermann") > 0, "B nach A");

pruefe(
  JSON.stringify(sortiert(["KA-AB 1", "—", "HH-DO 4"], false)) ===
    JSON.stringify(["HH-DO 4", "KA-AB 1", "—"]),
  "leere Felder landen am Ende: " + sortiert(["KA-AB 1", "—", "HH-DO 4"], false).join(", ")
);
pruefe(
  sortiert(["KA-AB 1", "—", "HH-DO 4"], true)[2] === "—",
  "auch absteigend stehen sie hinten, nicht ploetzlich vorn"
);
pruefe(vergleiche("", "—") === 0, "leer und Gedankenstrich gelten als gleich leer");
pruefe(vergleiche(null, "Berger") > 0, "null zaehlt als leer");
pruefe(vergleiche("  Berger  ", "Berger") === 0, "Leerzeichen aussen stoeren nicht");

console.log();
if (fehler.length) {
  console.log("FEHLGESCHLAGEN (" + fehler.length + "):");
  fehler.forEach(function (eintrag) {
    console.log("  - " + eintrag);
  });
} else {
  console.log("alle Pruefungen bestanden");
}
process.exit(fehler.length ? 1 : 0);
