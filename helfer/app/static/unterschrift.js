/* Das Unterschriften-Tablet.
 *
 * Zwei Aufgaben: im Takt nachfragen, ob etwas ansteht, und eine Unterschrift
 * entgegennehmen.
 *
 * Drei Dinge, die im Betrieb den Unterschied machen:
 *
 * 1. Solange jemand zeichnet, wird der Inhalt NICHT ausgetauscht. Eine
 *    halbfertige Unterschrift unter den Fingern wegzunehmen, weil im
 *    Hintergrund eine Uhr abgelaufen ist, wäre die unangenehmste Art, aktuell
 *    sein zu wollen.
 * 2. Der Pfad wird als SVG-Punktfolge gesammelt, nicht als Rasterbild. Das
 *    bleibt in jeder Größe scharf, ist ein Bruchteil so groß und kommt ohne
 *    data:-URI aus, die die Content-Security-Policy ohnehin abweisen würde.
 * 3. Gezeichnet wird auf einem Canvas in Gerätepunkten. Ohne die Umrechnung
 *    über devicePixelRatio ist der Strich auf einem Tablet unscharf und sitzt
 *    daneben.
 */
(function () {
  "use strict";

  var skript = document.currentScript;
  var quelle = skript.getAttribute("data-quelle");
  var takt = Number(skript.getAttribute("data-takt") || 2) * 1000;
  if (!(takt >= 1000)) {
    takt = 2000;
  }

  var inhalt = document.getElementById("inhalt");
  var meldung = document.getElementById("meldung");

  /* Eine Meldung kommt als Parameter in der Adresse an und bliebe dort
   * stehen: bei jeder weiteren Übergabe schöbe sie die Knöpfe ein Stück
   * weiter nach unten aus dem Bild. Sie verschwindet deshalb nach ein paar
   * Sekunden, und die Adresse wird gleich mit aufgeräumt - sonst wäre sie
   * nach dem nächsten Neuladen wieder da. */
  if (meldung) {
    setTimeout(function () {
      meldung.parentNode.removeChild(meldung);
      meldung = null;
    }, 8000);
  }
  if (window.history && window.history.replaceState
      && window.location.search) {
    window.history.replaceState(null, "", window.location.pathname);
  }

  function meldungWeg() {
    if (meldung && meldung.parentNode) {
      meldung.parentNode.removeChild(meldung);
      meldung = null;
    }
  }

  /* Welcher Vorgang gerade angezeigt wird, und ob jemand dabei ist. */
  var gezeigt = null;
  var zeichnetGerade = false;

  /* --- Zeichenfläche ------------------------------------------------------ */

  function flaecheEinrichten() {
    var canvas = document.getElementById("flaeche");
    if (!canvas) {
      return;
    }

    var feld = document.getElementById("pfad");
    var fertig = document.getElementById("fertig");
    var loeschen = document.getElementById("loeschen");
    var formular = document.getElementById("zeichenformular");

    var punkte = [];          /* Liste von Strichen, jeder eine Punktliste */
    var strich = null;
    var stift = canvas.getContext("2d");
    var dichte = window.devicePixelRatio || 1;

    function groesseSetzen() {
      var kasten = canvas.getBoundingClientRect();
      canvas.width = Math.round(kasten.width * dichte);
      canvas.height = Math.round(kasten.height * dichte);
      stift.scale(dichte, dichte);
      stift.lineWidth = 2.5;
      stift.lineCap = "round";
      stift.lineJoin = "round";
      stift.strokeStyle = "#13160f";
      stift.fillStyle = "#13160f";
      neuZeichnen(kasten.width, kasten.height);
    }

    function tupfen(punkt) {
      stift.beginPath();
      stift.arc(punkt.x, punkt.y, stift.lineWidth / 2, 0, 2 * Math.PI);
      stift.fill();
    }

    function neuZeichnen(breite, hoehe) {
      stift.clearRect(0, 0, breite || canvas.width, hoehe || canvas.height);
      punkte.forEach(function (einStrich) {
        if (einStrich.length < 1) {
          return;
        }
        if (einStrich.length === 1) {
          tupfen(einStrich[0]);
          return;
        }
        stift.beginPath();
        stift.moveTo(einStrich[0].x, einStrich[0].y);
        einStrich.forEach(function (punkt) {
          stift.lineTo(punkt.x, punkt.y);
        });
        stift.stroke();
      });
    }

    function stelle(ereignis) {
      var kasten = canvas.getBoundingClientRect();
      return {
        x: Math.round((ereignis.clientX - kasten.left) * 10) / 10,
        y: Math.round((ereignis.clientY - kasten.top) * 10) / 10,
      };
    }

    function stand() {
      var etwasDa = punkte.some(function (s) { return s.length >= 1; });
      if (fertig) {
        fertig.disabled = !etwasDa;
      }
      /* Ein angefangener Strich zählt schon: ab dem ersten Aufsetzen soll die
       * Auffrischung nichts mehr austauschen. */
      zeichnetGerade = punkte.length > 0;
    }

    canvas.addEventListener("pointerdown", function (ereignis) {
      ereignis.preventDefault();
      canvas.setPointerCapture(ereignis.pointerId);
      strich = [stelle(ereignis)];
      punkte.push(strich);
      tupfen(strich[0]);
      stand();
    });

    canvas.addEventListener("pointermove", function (ereignis) {
      if (!strich) {
        return;
      }
      ereignis.preventDefault();
      var punkt = stelle(ereignis);
      var vorher = strich[strich.length - 1];
      /* Punkte, die kaum auseinanderliegen, bringen nichts und blähen den
       * Pfad auf. */
      if (Math.abs(punkt.x - vorher.x) < 1 && Math.abs(punkt.y - vorher.y) < 1) {
        return;
      }
      strich.push(punkt);
      stift.beginPath();
      stift.moveTo(vorher.x, vorher.y);
      stift.lineTo(punkt.x, punkt.y);
      stift.stroke();
      stand();
    });

    function loslassen() {
      strich = null;
      stand();
    }

    canvas.addEventListener("pointerup", loslassen);
    canvas.addEventListener("pointercancel", loslassen);
    canvas.addEventListener("pointerleave", loslassen);

    if (loeschen) {
      loeschen.addEventListener("click", function () {
        punkte = [];
        strich = null;
        var kasten = canvas.getBoundingClientRect();
        neuZeichnen(kasten.width, kasten.height);
        stand();
      });
    }

    if (formular) {
      formular.addEventListener("submit", function (ereignis) {
        var teile = [];
        punkte.forEach(function (einStrich) {
          if (einStrich.length < 1) {
            return;
          }
          if (einStrich.length === 1) {
            /* Eine Strecke der Laenge null. Mit stroke-linecap="round"
             * zeichnet SVG daraus einen Punkt - so ueberlebt der i-Punkt
             * den Weg vom Tablet in die Vorschau. */
            teile.push("M" + einStrich[0].x + "," + einStrich[0].y
                       + "L" + einStrich[0].x + "," + einStrich[0].y);
            return;
          }
          var stueck = "M" + einStrich[0].x + "," + einStrich[0].y;
          einStrich.slice(1).forEach(function (punkt) {
            stueck += "L" + punkt.x + "," + punkt.y;
          });
          teile.push(stueck);
        });
        if (!teile.length) {
          ereignis.preventDefault();
          return;
        }
        feld.value = teile.join("");
        /* Ab hier darf wieder ausgetauscht werden. */
        zeichnetGerade = false;
      });
    }

    groesseSetzen();
    window.addEventListener("resize", groesseSetzen);
  }

  function uebernehmen() {
    var kasten = inhalt.querySelector("[data-vorgang]");
    gezeigt = kasten ? kasten.getAttribute("data-vorgang") : null;
    zeichnetGerade = false;
    flaecheEinrichten();
  }

  /* --- Nachfragen --------------------------------------------------------- */

  function holen() {
    /* Wer zeichnet, wird nicht unterbrochen. */
    if (zeichnetGerade) {
      return;
    }
    fetch(quelle, { cache: "no-store", credentials: "same-origin" })
      .then(function (antwort) {
        if (!antwort.ok) {
          throw new Error("HTTP " + antwort.status);
        }
        return antwort.text();
      })
      .then(function (text) {
        /* Nur austauschen, wenn sich wirklich etwas geändert hat: sonst
         * flackerte das Feld im Takt und man könnte gar nicht zeichnen. */
        var probe = document.createElement("div");
        probe.innerHTML = text;
        var neuerKasten = probe.querySelector("[data-vorgang]");
        var neu = neuerKasten ? neuerKasten.getAttribute("data-vorgang") : null;
        if (neu === gezeigt) {
          return;
        }
        /* Sobald etwas Neues ansteht, ist die alte Meldung erledigt. */
        meldungWeg();
        inhalt.innerHTML = text;
        uebernehmen();
      })
      .catch(function () {
        /* Kein Netz: das Bisherige bleibt stehen. Am Tisch merkt man das
         * daran, dass nichts erscheint – und kann auf Papier ausweichen. */
      });
  }

  uebernehmen();
  setInterval(holen, takt);
})();
