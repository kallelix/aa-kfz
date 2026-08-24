/* Hält die Monitoransicht aktuell und zeigt eine angetippte Schicht groß.
 *
 * Drei Dinge, die auf einem Bildschirm an der Wand zählen:
 *
 * 1. Reißt die Verbindung ab, bleibt das Letzte stehen, was da war – mit
 *    einem sichtbaren Hinweis, von wann es ist. Eine leere oder halb geladene
 *    Seite wäre schlimmer als ein alter Stand, den man als alt erkennt.
 * 2. Die Uhr geht nach dem Server, nicht nach dem Rechner am Monitor. Der
 *    Abstand zwischen beiden wird bei jedem geglückten Abruf neu bestimmt;
 *    dazwischen zählt die lokale Uhr weiter, damit die Anzeige jede Sekunde
 *    stimmt und nicht nur jede Minute.
 * 3. Das Overlay schließt sich von selbst. Ohne das bliebe der Monitor in
 *    einer einzelnen Schicht hängen, sobald jemand sie öffnet und weggeht –
 *    und niemand merkt es, weil da ja etwas steht.
 */
(function () {
  "use strict";

  var skript = document.currentScript;
  var quelle = skript.getAttribute("data-quelle");
  var intervall = Number(skript.getAttribute("data-intervall") || 60) * 1000;
  if (!(intervall > 5000)) {
    intervall = 60000;
  }
  var overlayDauer = Number(skript.getAttribute("data-overlay-sekunden") || 90);
  if (!(overlayDauer >= 0)) {
    overlayDauer = 90;
  }

  var inhalt = document.getElementById("inhalt");
  var warnung = document.getElementById("warnung");
  var standAnzeige = document.getElementById("stand");
  var uhrAnzeige = document.getElementById("uhr");
  var tagAnzeige = document.getElementById("tag");

  var overlay = document.getElementById("overlay");
  var overlayInhalt = document.getElementById("overlay-inhalt");
  var overlayFuss = document.getElementById("overlay-fuss");
  var overlayRest = document.getElementById("overlay-rest");
  var overlayZu = document.getElementById("overlay-zu");

  /* Abstand zwischen Serveruhr und lokaler Uhr, in Millisekunden. */
  var abstand = 0;
  var letzterStand = null;

  /* Welche Schicht gerade offen ist (null = keine) und wann sie zugeht. */
  var offeneSchicht = null;
  var schliesstUm = 0;

  function zweistellig(zahl) {
    return (zahl < 10 ? "0" : "") + zahl;
  }

  function serverzeit() {
    return new Date(Date.now() + abstand);
  }

  function uhrStellen() {
    if (!uhrAnzeige) {
      return;
    }
    var jetzt = serverzeit();
    uhrAnzeige.textContent =
      zweistellig(jetzt.getHours()) + ":" + zweistellig(jetzt.getMinutes());
  }

  function standMerken() {
    var raster = inhalt.querySelector("[data-jetzt]");
    if (!raster) {
      return;
    }
    var gemeldet = new Date(raster.getAttribute("data-jetzt"));
    if (!isNaN(gemeldet.getTime())) {
      abstand = gemeldet.getTime() - Date.now();
      letzterStand = gemeldet;
    }
    var tag = raster.getAttribute("data-tag");
    if (tag && tagAnzeige) {
      tagAnzeige.textContent = tag;
    }
    uhrStellen();
  }

  function warnungZeigen(an) {
    if (!warnung) {
      return;
    }
    warnung.hidden = !an;
    if (an && standAnzeige && letzterStand) {
      standAnzeige.textContent =
        zweistellig(letzterStand.getHours()) + ":" +
        zweistellig(letzterStand.getMinutes());
    }
  }

  /* --- Overlay ----------------------------------------------------------- */

  function detailSuchen(nummer) {
    var kachel = inhalt.querySelector('.kachel[data-schicht="' + nummer + '"]');
    if (!kachel || !kachel.parentNode) {
      return null;
    }
    return kachel.parentNode.querySelector(".detail");
  }

  function oeffnen(nummer) {
    var detail = detailSuchen(nummer);
    if (!detail) {
      return;
    }
    offeneSchicht = nummer;
    overlayInhalt.innerHTML = detail.innerHTML;
    overlay.hidden = false;
    if (overlayDauer > 0) {
      schliesstUm = Date.now() + overlayDauer * 1000;
      overlayFuss.hidden = false;
      restStellen();
    } else {
      overlayFuss.hidden = true;
    }
    overlayZu.focus();
  }

  function schliessen() {
    offeneSchicht = null;
    schliesstUm = 0;
    overlay.hidden = true;
    overlayInhalt.innerHTML = "";
  }

  function restStellen() {
    if (!offeneSchicht || !schliesstUm) {
      return;
    }
    var rest = Math.ceil((schliesstUm - Date.now()) / 1000);
    if (rest <= 0) {
      schliessen();
      return;
    }
    overlayRest.textContent = String(rest);
  }

  inhalt.addEventListener("click", function (ereignis) {
    var kachel = ereignis.target.closest
      ? ereignis.target.closest(".kachel")
      : null;
    if (kachel) {
      oeffnen(kachel.getAttribute("data-schicht"));
    }
  });

  overlayZu.addEventListener("click", schliessen);

  /* Tippen neben den Kasten schließt ebenfalls – auf einem Touchscreen die
   * naheliegendste Geste. */
  overlay.addEventListener("click", function (ereignis) {
    if (ereignis.target === overlay) {
      schliessen();
    }
  });

  document.addEventListener("keydown", function (ereignis) {
    if (ereignis.key === "Escape" && offeneSchicht) {
      schliessen();
    }
  });

  /* --- Auffrischen ------------------------------------------------------- */

  function holen() {
    /* Kein AbortSignal.timeout: das kennen ältere Browser nicht, und auf so
     * einem Monitor steht gern etwas Betagtes. Bleibt die Antwort aus, greift
     * beim nächsten Durchlauf ohnehin dieselbe Warnung. */
    fetch(quelle, { cache: "no-store", credentials: "same-origin" })
      .then(function (antwort) {
        if (!antwort.ok) {
          throw new Error("HTTP " + antwort.status);
        }
        return antwort.text();
      })
      .then(function (text) {
        inhalt.innerHTML = text;
        standMerken();
        warnungZeigen(false);

        /* Steht jemand vor einer geöffneten Schicht, bekommt er die frischen
         * Zahlen – ohne dass ihm die Ansicht weggenommen wird. Ist die
         * Schicht inzwischen aus der Übersicht gelaufen (etwa weil sie zu
         * Ende ist), bleibt der letzte Stand stehen, bis der Selbstschließer
         * greift. Zuklappen unter den Augen des Lesenden wäre schlimmer. */
        if (offeneSchicht) {
          var detail = detailSuchen(offeneSchicht);
          if (detail) {
            overlayInhalt.innerHTML = detail.innerHTML;
          }
        }
      })
      .catch(function () {
        /* Der alte Inhalt bleibt genau so stehen, wie er ist – samt einem
         * offenen Overlay, das sich aus ihm speist. */
        warnungZeigen(true);
      });
  }

  standMerken();
  setInterval(function () {
    uhrStellen();
    restStellen();
  }, 1000);
  setInterval(holen, intervall);
})();
