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

      /* Nur anwenden, wenn die Adresse gar nichts dazu sagt - eine
       * ausdrueckliche Wahl in der Adresse hat immer Vorrang, sonst koennte
       * man einen Link nicht mehr teilen. */
      if (window.location.search.indexOf(feld + "=") !== -1) {
        return;
      }
      var gemerkt = lesen(name);
      if (!gemerkt) {
        return;
      }
      var ziel = gruppe.querySelector('[data-wert="' + gemerkt + '"]');
      if (ziel && ziel.getAttribute("href")) {
        /* replace statt assign: der Zurueck-Knopf soll nicht auf die
         * Fassung ohne Filter zeigen und einen dorthin zuruecktreten
         * lassen, aus der er sofort wieder wegspringt. */
        window.location.replace(ziel.getAttribute("href"));
      }
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    klappzustaende();
    umschalter();
  });
})();
