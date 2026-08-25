/* Merkt sich, welche aufklappbaren Bloecke im Backoffice zu sind.
 *
 * Das Auf- und Zuklappen macht der Browser selbst (details/summary). Hier
 * wird nur gemerkt, wie es zuletzt stand - sonst muesste man an einem
 * Ausgabetisch nach jedem Seitenwechsel wieder zuklappen, und genau das ist
 * der Grund, warum es die Funktion ueberhaupt gibt.
 *
 * localStorage in try/catch: im privaten Modus mancher Browser wirft schon
 * der Zugriff. Dann klappt eben nichts mehr nach, statt dass die Seite
 * stehenbleibt.
 */
(function () {
  "use strict";

  function lesen(name) {
    try {
      return window.localStorage.getItem("klapp:" + name);
    } catch (fehler) {
      return null;
    }
  }

  function schreiben(name, wert) {
    try {
      window.localStorage.setItem("klapp:" + name, wert);
    } catch (fehler) {
      /* Kein Speicher verfügbar – dann gilt eben die Vorgabe der Seite. */
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    var bloecke = document.querySelectorAll("details[data-merken]");
    Array.prototype.forEach.call(bloecke, function (block) {
      var name = block.getAttribute("data-merken");
      var gemerkt = lesen(name);
      if (gemerkt !== null) {
        block.open = gemerkt === "auf";
      }
      block.addEventListener("toggle", function () {
        schreiben(name, block.open ? "auf" : "zu");
      });
    });
  });
})();
