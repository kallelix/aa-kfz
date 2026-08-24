/* Hält die Monitoransicht aktuell, ohne die Seite neu zu laden.
 *
 * Zwei Dinge, die auf einem Bildschirm an der Wand zählen:
 *
 * 1. Reißt die Verbindung ab, bleibt das Letzte stehen, was da war – mit
 *    einem sichtbaren Hinweis, von wann es ist. Eine leere oder halb geladene
 *    Seite wäre schlimmer als ein alter Stand, den man als alt erkennt.
 * 2. Die Uhr geht nach dem Server, nicht nach dem Rechner am Monitor. Der
 *    Abstand zwischen beiden wird bei jedem geglückten Abruf neu bestimmt;
 *    dazwischen zählt die lokale Uhr weiter, damit die Anzeige jede Sekunde
 *    stimmt und nicht nur jede Minute.
 */
(function () {
  "use strict";

  var skript = document.currentScript;
  var quelle = skript.getAttribute("data-quelle");
  var intervall = Number(skript.getAttribute("data-intervall") || 60) * 1000;
  if (!(intervall > 5000)) {
    intervall = 60000;
  }

  var inhalt = document.getElementById("inhalt");
  var warnung = document.getElementById("warnung");
  var standAnzeige = document.getElementById("stand");
  var uhrAnzeige = document.getElementById("uhr");
  var tagAnzeige = document.getElementById("tag");

  /* Abstand zwischen Serveruhr und lokaler Uhr, in Millisekunden. */
  var abstand = 0;
  var letzterStand = null;

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
      })
      .catch(function () {
        /* Der alte Inhalt bleibt genau so stehen, wie er ist. */
        warnungZeigen(true);
      });
  }

  standMerken();
  setInterval(uhrStellen, 1000);
  setInterval(holen, intervall);
})();
