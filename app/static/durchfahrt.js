/* Filtert die Durchfahrtsliste im Browser.
 *
 * An der Straßensperre ist der Empfang mies, deshalb steht die vollständige
 * Liste bereits in der Seite und es geht bei der Suche keine einzige Anfrage
 * mehr raus. Einmal laden, solange Netz da ist, dann läuft es offline weiter.
 *
 * Die Normalisierung passiert schon auf dem Server (siehe
 * db.kfz_normalisieren): jede Zeile trägt data-name kleingeschrieben und
 * data-kfz ohne Trennzeichen. Hier wird nur noch die Eingabe genauso
 * zugerichtet und verglichen.
 */
(function () {
  "use strict";

  function kfzNormalisieren(text) {
    return String(text || "").replace(/[^\p{L}\p{N}]/gu, "").toUpperCase();
  }

  function passt(zeile, suche) {
    var roh = String(suche || "").trim().toLowerCase();
    if (roh === "") {
      return true;
    }
    if (zeile.name.indexOf(roh) !== -1) {
      return true;
    }
    var kfz = kfzNormalisieren(suche);
    // Eine Eingabe aus lauter Trennzeichen darf nicht plötzlich alles treffen.
    return kfz !== "" && zeile.kfz.indexOf(kfz) !== -1;
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = { kfzNormalisieren: kfzNormalisieren, passt: passt };
  }

  if (typeof document === "undefined") {
    return;
  }

  document.addEventListener("DOMContentLoaded", function () {
    var eingabe = document.getElementById("suche");
    var tabelle = document.getElementById("durchfahrt");
    if (!eingabe || !tabelle) {
      return;
    }

    var zeilen = Array.prototype.map.call(
      tabelle.querySelectorAll("tbody tr"),
      function (element) {
        return {
          element: element,
          name: element.getAttribute("data-name") || "",
          kfz: element.getAttribute("data-kfz") || "",
        };
      }
    );

    var trefferzahl = document.getElementById("trefferzahl");
    var nichts = document.getElementById("nichts-gefunden");
    var zuruecksetzen = document.getElementById("zuruecksetzen");

    function filtern() {
      var suche = eingabe.value;
      var sichtbar = 0;

      zeilen.forEach(function (zeile) {
        var treffer = passt(zeile, suche);
        zeile.element.classList.toggle("weg", !treffer);
        if (treffer) {
          sichtbar += 1;
        }
      });

      if (trefferzahl) {
        trefferzahl.textContent =
          sichtbar === 1 ? "1 Fahrzeug berechtigt" : sichtbar + " Fahrzeuge berechtigt";
      }
      if (nichts) {
        nichts.classList.toggle("weg", sichtbar > 0);
      }
      if (zuruecksetzen) {
        zuruecksetzen.classList.toggle("weg", eingabe.value === "");
      }
      tabelle.classList.toggle("weg", sichtbar === 0);
    }

    eingabe.addEventListener("input", filtern);

    // Enter darf die Seite nicht neu laden – ohne Netz käme sie nicht wieder.
    eingabe.addEventListener("keydown", function (ereignis) {
      if (ereignis.key === "Enter") {
        ereignis.preventDefault();
      }
    });

    if (zuruecksetzen) {
      zuruecksetzen.addEventListener("click", function (ereignis) {
        ereignis.preventDefault();
        eingabe.value = "";
        filtern();
        eingabe.focus();
      });
    }

    filtern();
  });
})();
