/* Filtert und sortiert die Durchfahrtsliste im Browser.
 *
 * An der Straßensperre ist der Empfang mies, deshalb steht die vollständige
 * Liste bereits in der Seite und es geht weder beim Suchen noch beim Sortieren
 * eine Anfrage raus. Einmal laden, solange Netz da ist, dann läuft es offline
 * weiter.
 *
 * Die Normalisierung fürs Suchen passiert schon auf dem Server (siehe
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

  /* Vergleich für die Sortierung.
   *
   * localeCompare mit "de": Umlaute landen bei ihrem Grundbuchstaben, Ö also
   * bei O und nicht hinter Z. numeric sorgt dafür, dass "KA-AB 2" vor
   * "KA-AB 10" steht statt dahinter.
   *
   * Die Richtung steckt bewusst im Vergleich und wird nicht aussen negiert:
   * leere Felder (—) sollen in beiden Richtungen unten bleiben. Wer nach
   * Kennzeichen sortiert, sucht ein Kennzeichen und keine Platzhalter. */
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
    module.exports = {
      kfzNormalisieren: kfzNormalisieren,
      passt: passt,
      vergleiche: vergleiche,
    };
  }

  if (typeof document === "undefined") {
    return;
  }

  document.addEventListener("DOMContentLoaded", function () {
    var eingabe = document.getElementById("suche");
    var tabelle = document.getElementById("durchfahrt");
    if (!tabelle) {
      return;
    }

    var koerper = tabelle.tBodies[0];
    var zeilen = Array.prototype.map.call(
      koerper.querySelectorAll("tr"),
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

    // --- Filtern ------------------------------------------------------------

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
          sichtbar === 1 ? "1 Fahrzeug berechtigt" : sichtbar + " Fahrzeuge berechtigt";
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

      // Enter darf die Seite nicht neu laden – ohne Netz käme sie nicht wieder.
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
        }
        filtern();
        if (eingabe) {
          eingabe.focus();
        }
      });
    }

    // --- Sortieren ----------------------------------------------------------

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
      // appendChild verschiebt vorhandene Knoten, es entstehen keine neuen –
      // die Verweise in `zeilen` bleiben also gültig.
      sortiert.forEach(function (zeile) {
        koerper.appendChild(zeile.element);
      });
      marken(spalte, absteigend);
    }

    // Vorgabe: Kennzeichen aufsteigend. Der Server liefert schon so, hier wird
    // trotzdem einmal sortiert – dann stimmt die Reihenfolge auf die Stelle
    // genau mit dem ueberein, was ein Klick auf dieselbe Spalte ergibt, und der
    // Pfeil steht von Anfang an richtig.
    var aktuelleSpalte = 2;
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
