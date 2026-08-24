/* Filtert und sortiert eine Tabelle im Browser.
 *
 * Am Schalter soll das Tippen sofort etwas zeigen und nicht auf den Server
 * warten. Die Häkchen daneben ändern Serverzustand und laden neu – das ist in
 * Ordnung, weil pro Besucher ohnehin einmal gesucht wird.
 *
 * Erwartet:
 *   #suche          Eingabefeld (optional)
 *   table[data-liste] Tabelle, deren Zeilen ein data-suche tragen
 *   #trefferzahl    Anzeige der sichtbaren Zeilen (optional)
 *   #nichts-gefunden Meldung, wenn nichts passt (optional)
 *   thead .sortknopf mit data-spalte
 *
 * Die Normalisierung des Suchtexts passiert auf dem Server (kleingeschrieben
 * in data-suche), damit sie nur einmal existiert.
 */
(function () {
  "use strict";

  function passt(zeile, suche) {
    var roh = String(suche || "").trim().toLowerCase();
    return roh === "" || zeile.suche.indexOf(roh) !== -1;
  }

  /* localeCompare mit "de": Umlaute landen bei ihrem Grundbuchstaben, Ö also
   * bei O und nicht hinter Z. numeric vergleicht Zahlen in Zeichenketten als
   * Zahlen.
   *
   * Die Richtung steckt bewusst im Vergleich und wird nicht aussen negiert:
   * leere Felder sollen in beiden Richtungen unten bleiben. */
  function vergleiche(a, b, absteigend) {
    var links = String(a === undefined || a === null ? "" : a).trim();
    var rechts = String(b === undefined || b === null ? "" : b).trim();
    var leerL = links === "" || links === "—";
    var leerR = rechts === "" || rechts === "—";
    if (leerL !== leerR) {
      return leerL ? 1 : -1;
    }
    if (leerL && leerR) {
      return 0;
    }
    var wert = links.localeCompare(rechts, "de", {
      numeric: true,
      sensitivity: "base",
    });
    return absteigend ? -wert : wert;
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = { passt: passt, vergleiche: vergleiche };
  }

  if (typeof document === "undefined") {
    return;
  }

  document.addEventListener("DOMContentLoaded", function () {
    var tabelle = document.querySelector("table[data-liste]");
    if (!tabelle) {
      return;
    }

    var eingabe = document.getElementById("suche");
    var koerper = tabelle.tBodies[0];
    var trefferzahl = document.getElementById("trefferzahl");
    var nichts = document.getElementById("nichts-gefunden");
    var zuruecksetzen = document.getElementById("zuruecksetzen");
    var einheit = tabelle.getAttribute("data-einheit") || "Eintrag";
    var einheitMehrzahl = tabelle.getAttribute("data-einheit-mehrzahl") || einheit;

    var zeilen = Array.prototype.map.call(
      koerper.querySelectorAll("tr"),
      function (element) {
        return {
          element: element,
          suche: element.getAttribute("data-suche") || "",
        };
      }
    );

    function filtern() {
      var suche = eingabe ? eingabe.value : "";
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
          sichtbar + " " + (sichtbar === 1 ? einheit : einheitMehrzahl);
      }
      if (nichts) {
        nichts.classList.toggle("weg", sichtbar > 0);
      }
      if (zuruecksetzen && eingabe) {
        zuruecksetzen.classList.toggle("weg", eingabe.value === "");
      }
      tabelle.classList.toggle("weg", sichtbar === 0);
    }

    if (eingabe) {
      eingabe.addEventListener("input", filtern);
      // Enter soll nicht irgendein Formular in der Seite abschicken.
      eingabe.addEventListener("keydown", function (ereignis) {
        if (ereignis.key === "Enter") {
          ereignis.preventDefault();
        }
      });
    }

    if (zuruecksetzen) {
      zuruecksetzen.addEventListener("click", function (ereignis) {
        ereignis.preventDefault();
        if (eingabe) {
          eingabe.value = "";
          filtern();
          eingabe.focus();
        }
      });
    }

    var knoepfe = Array.prototype.slice.call(
      tabelle.querySelectorAll("thead .sortknopf")
    );

    function marken(spalte, absteigend) {
      knoepfe.forEach(function (knopf) {
        var eigene = Number(knopf.getAttribute("data-spalte")) === spalte;
        var kopf = knopf.closest("th");
        if (kopf) {
          kopf.setAttribute(
            "aria-sort",
            eigene ? (absteigend ? "descending" : "ascending") : "none"
          );
        }
        var pfeil = knopf.querySelector(".sortpfeil");
        if (pfeil) {
          pfeil.textContent = eigene ? (absteigend ? "▼" : "▲") : "";
        }
      });
    }

    function sortieren(spalte, absteigend) {
      var sortiert = zeilen.slice().sort(function (a, b) {
        return vergleiche(
          a.element.cells[spalte] ? a.element.cells[spalte].textContent : "",
          b.element.cells[spalte] ? b.element.cells[spalte].textContent : "",
          absteigend
        );
      });
      // appendChild verschiebt vorhandene Knoten – die Verweise bleiben gültig.
      sortiert.forEach(function (zeile) {
        koerper.appendChild(zeile.element);
      });
      marken(spalte, absteigend);
    }

    // Beim Absenden einer Zeilenaktion den aktuellen Suchbegriff mitgeben, damit
    // die Liste nach dem Neuladen wieder genauso gefiltert ist. Zusammen mit der
    // Sprungmarke aus der Antwort landet man dort, wo man geklickt hat.
    tabelle.addEventListener("submit", function (ereignis) {
      if (!eingabe) {
        return;
      }
      var feld = ereignis.target.querySelector('input[name="suche"]');
      if (feld) {
        feld.value = eingabe.value;
      }
    });

    var aktuelleSpalte = Number(tabelle.getAttribute("data-sortspalte") || 0);
    var aktuellAbsteigend = false;

    knoepfe.forEach(function (knopf) {
      knopf.addEventListener("click", function () {
        var spalte = Number(knopf.getAttribute("data-spalte"));
        aktuellAbsteigend = spalte === aktuelleSpalte ? !aktuellAbsteigend : false;
        aktuelleSpalte = spalte;
        sortieren(spalte, aktuellAbsteigend);
      });
    });

    sortieren(aktuelleSpalte, aktuellAbsteigend);
    filtern();
  });
})();
