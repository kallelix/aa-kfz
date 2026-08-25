/* Merkt sich, wie das Backoffice zuletzt eingestellt war.
 *
 * Zweierlei:
 *
 * 1. Welche aufklappbaren Bloecke zu sind. Das Klappen macht der Browser
 *    selbst (details/summary); ohne das Merken muesste man an einem
 *    Ausgabetisch nach jedem Seitenwechsel wieder zuklappen.
 *
 * 2. Welche Seite eines Umschalters gewaehlt war - etwa "nur was noch
 *    draussen ist". Der Filter steht in der Adresse, weil er serverseitig
 *    wirkt; gemerkt wird deshalb nur die Vorliebe, und beim naechsten Aufruf
 *    ohne Angabe wird sie einmal angewandt.
 *
 * localStorage in try/catch: im privaten Modus mancher Browser wirft schon
 * der Zugriff. Dann gilt eben die Vorgabe der Seite, statt dass etwas
 * stehenbleibt.
 */
(function () {
  "use strict";

  function lesen(name) {
    try {
      return window.localStorage.getItem(name);
    } catch (fehler) {
      return null;
    }
  }

  function schreiben(name, wert) {
    try {
      window.localStorage.setItem(name, wert);
    } catch (fehler) {
      /* Kein Speicher verfuegbar. */
    }
  }

  function klappzustaende() {
    var bloecke = document.querySelectorAll("details[data-merken]");
    Array.prototype.forEach.call(bloecke, function (block) {
      var name = "klapp:" + block.getAttribute("data-merken");
      var gemerkt = lesen(name);
      if (gemerkt !== null) {
        block.open = gemerkt === "auf";
      }
      block.addEventListener("toggle", function () {
        schreiben(name, block.open ? "auf" : "zu");
      });
    });
  }

  function umschalter() {
    var gruppen = document.querySelectorAll("[data-merken-filter]");
    Array.prototype.forEach.call(gruppen, function (gruppe) {
      var name = "filter:" + gruppe.getAttribute("data-merken-filter");
      var feld = gruppe.getAttribute("data-feld") || "offen";

      var teile = gruppe.querySelectorAll("[data-wert]");
      Array.prototype.forEach.call(teile, function (teil) {
        teil.addEventListener("click", function () {
          schreiben(name, teil.getAttribute("data-wert"));
        });
      });

      /* Eine ausdrueckliche Wahl in der Adresse hat Vorrang: sonst liesse
       * sich ein Link nicht mehr teilen. */
      if (window.location.search.indexOf(feld + "=") !== -1) {
        return;
      }
      var gemerkt = lesen(name);
      if (!gemerkt) {
        return;
      }

      /* Der entscheidende Vergleich ist der mit dem, was die Seite gerade
       * ZEIGT - nicht der mit dem, was in der Adresse steht.
       *
       * Die Seite "Alle" hat keinen Filter in der Adresse. Wer danach ginge,
       * faende dort nie eine Angabe, wuerde die gemerkte Wahl anwenden,
       * wieder auf "Alle" landen, wieder nichts finden - und so fort. Genau
       * dieses endlose Neuladen stand hier. Steht ohnehin schon das Richtige
       * da, ist nichts zu tun; damit kann es sich nicht wiederholen. */
      var aktiv = gruppe.querySelector("[data-wert].ist-aktiv");
      if (aktiv && aktiv.getAttribute("data-wert") === gemerkt) {
        return;
      }

      var ziel = gruppe.querySelector('[data-wert="' + gemerkt + '"]');
      if (!ziel || !ziel.getAttribute("href")) {
        return;
      }
      if (ziel.pathname + ziel.search === window.location.pathname
                                         + window.location.search) {
        return;
      }
      /* replace statt assign: der Zurueck-Knopf soll nicht auf die Fassung
       * zeigen, aus der man gerade weggeschickt wurde. */
      window.location.replace(ziel.getAttribute("href"));
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    klappzustaende();
    umschalter();
  });
})();
