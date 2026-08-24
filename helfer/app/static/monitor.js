/* Hält die Monitoransicht aktuell, zeigt eine angetippte Schicht groß und
 * lässt einen ganzen Tag vorausschauen.
 *
 * Vier Dinge, die auf einem Bildschirm an der Wand zählen:
 *
 * 1. Reißt die Verbindung ab, bleibt das Letzte stehen, was da war – mit
 *    einem sichtbaren Hinweis, von wann es ist. Eine leere oder halb geladene
 *    Seite wäre schlimmer als ein alter Stand, den man als alt erkennt.
 * 2. Die Uhr geht nach dem Server, nicht nach dem Rechner am Monitor. Der
 *    Abstand zwischen beiden wird bei jedem geglückten Abruf neu bestimmt;
 *    dazwischen zählt die lokale Uhr weiter, damit die Anzeige jede Sekunde
 *    stimmt und nicht nur jede Minute.
 * 3. Alles, was jemand aufschlägt, schließt sich von selbst wieder: das
 *    Overlay und der Tagesblick. Ohne das bliebe der Monitor beim ersten
 *    Neugierigen stehen, der weggeht – und niemandem fiele es auf, weil ja
 *    etwas zu sehen ist.
 * 4. Der Selbstrücksprung ruht, solange ein Overlay offen ist. Jemandem die
 *    Namensliste unter den Augen wegzuziehen, weil im Hintergrund eine Uhr
 *    abgelaufen ist, wäre die unangenehmste Art, hilfreich sein zu wollen.
 */
(function () {
  "use strict";

  var skript = document.currentScript;
  var quelle = skript.getAttribute("data-quelle");

  function zahl(name, vorgabe, mindest) {
    var wert = Number(skript.getAttribute(name));
    return wert >= (mindest === undefined ? 0 : mindest) ? wert : vorgabe;
  }

  var intervall = zahl("data-intervall", 60, 5) * 1000;
  var overlayDauer = zahl("data-overlay-sekunden", 90);
  var tagesblickDauer = zahl("data-tagesblick-sekunden", 120);

  var inhalt = document.getElementById("inhalt");
  var warnung = document.getElementById("warnung");
  var standAnzeige = document.getElementById("stand");
  var uhrAnzeige = document.getElementById("uhr");
  var tagAnzeige = document.getElementById("tag");

  var leiste = document.getElementById("tagesleiste");
  var rueckkehr = document.getElementById("rueckkehr");
  var rueckkehrRest = document.getElementById("rueckkehr-rest");

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
  var overlaySchliesstUm = 0;

  /* Welcher Tag gerade vorausgeschaut wird ("" = die Jetzt-Ansicht). */
  var offenerTag = "";
  var tagEndetUm = 0;

  function zweistellig(wert) {
    return (wert < 10 ? "0" : "") + wert;
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

  /* --- Overlay: eine Schicht groß ---------------------------------------- */

  /* Die Langfassung wird ueber ihre eigene Kennung gesucht, nicht ueber die
   * Kachel daneben: im Tagesblick koennen zwei Dinge dieselbe Schicht
   * oeffnen, die Kachel in der Liste und der Balken im Band. Nur eines von
   * beiden traegt die Langfassung bei sich. */
  function detailSuchen(nummer) {
    return inhalt.querySelector('[data-detail="' + nummer + '"]');
  }

  function overlayOeffnen(nummer) {
    var detail = detailSuchen(nummer);
    if (!detail) {
      return;
    }
    offeneSchicht = nummer;
    overlayInhalt.innerHTML = detail.innerHTML;
    overlay.hidden = false;
    if (overlayDauer > 0) {
      overlaySchliesstUm = Date.now() + overlayDauer * 1000;
      overlayFuss.hidden = false;
      overlayRest.textContent = String(overlayDauer);
    } else {
      overlayFuss.hidden = true;
    }
    overlayZu.focus();
  }

  function overlaySchliessen() {
    offeneSchicht = null;
    overlaySchliesstUm = 0;
    overlay.hidden = true;
    overlayInhalt.innerHTML = "";
    /* Die Uhr des Tagesblicks lief derweil nicht weiter – sie fängt jetzt von
     * vorn an, damit nach dem Zuklappen noch Zeit zum Weiterschauen bleibt. */
    if (offenerTag && tagesblickDauer > 0) {
      tagEndetUm = Date.now() + tagesblickDauer * 1000;
    }
  }

  /* --- Tagesblick --------------------------------------------------------- */

  function leisteMarkieren() {
    var knoepfe = leiste.querySelectorAll(".tagknopf");
    for (var i = 0; i < knoepfe.length; i += 1) {
      var eigen = knoepfe[i].getAttribute("data-tag") === offenerTag;
      knoepfe[i].classList.toggle("ist-aktiv", eigen);
      knoepfe[i].setAttribute("aria-pressed", eigen ? "true" : "false");
    }
    rueckkehr.hidden = !(offenerTag && tagesblickDauer > 0);
    /* Im Tagesblick darf die Seite rollen - am Samstag passt der Tag nicht
     * auf einen Bildschirm. In der Jetzt-Ansicht bleibt sie starr: dort soll
     * alles Wichtige gleichzeitig zu sehen sein, ohne dass jemand hinfasst. */
    document.body.classList.toggle("tagesblick", Boolean(offenerTag));
  }

  function tagWaehlen(tag) {
    if (offeneSchicht) {
      overlaySchliessen();
    }
    offenerTag = tag || "";
    tagEndetUm = offenerTag && tagesblickDauer > 0
      ? Date.now() + tagesblickDauer * 1000
      : 0;
    if (rueckkehrRest) {
      rueckkehrRest.textContent = String(tagesblickDauer);
    }
    leisteMarkieren();
    /* Nach dem Wechsel wieder nach oben - sonst landet man im neuen Tag an
     * der Stelle, an der man im alten aufgehoert hat. */
    window.scrollTo(0, 0);
    holen();
  }

  /* Wer blaettert, liest. Solange jemand das tut, faengt die Uhr bis zur
   * Rueckkehr von vorn an - sonst springt der Bildschirm mitten im Lesen auf
   * die Jetzt-Ansicht zurueck. Bewusst nur benutzergetriebene Ereignisse:
   * "scroll" allein feuert auch, wenn das Skript selbst nach oben rollt. */
  function weiterlesen() {
    if (offenerTag && tagesblickDauer > 0) {
      tagEndetUm = Date.now() + tagesblickDauer * 1000;
    }
  }

  ["wheel", "touchmove", "pointerdown", "keydown"].forEach(function (art) {
    window.addEventListener(art, weiterlesen, { passive: true });
  });

  function sekundentakt() {
    uhrStellen();

    if (offeneSchicht && overlaySchliesstUm) {
      var restOverlay = Math.ceil((overlaySchliesstUm - Date.now()) / 1000);
      if (restOverlay <= 0) {
        overlaySchliessen();
      } else {
        overlayRest.textContent = String(restOverlay);
      }
      /* Solange jemand liest, ruht der Rücksprung zur Jetzt-Ansicht. */
      if (offenerTag && tagesblickDauer > 0) {
        tagEndetUm = Date.now() + tagesblickDauer * 1000;
      }
    }

    if (offenerTag && tagEndetUm) {
      var restTag = Math.ceil((tagEndetUm - Date.now()) / 1000);
      if (restTag <= 0) {
        tagWaehlen("");
      } else if (rueckkehrRest) {
        rueckkehrRest.textContent = String(restTag);
      }
    }
  }

  /* --- Bedienung ---------------------------------------------------------- */

  inhalt.addEventListener("click", function (ereignis) {
    var ausloeser = ereignis.target.closest
      ? ereignis.target.closest("[data-schicht]")
      : null;
    if (ausloeser) {
      overlayOeffnen(ausloeser.getAttribute("data-schicht"));
    }
  });

  leiste.addEventListener("click", function (ereignis) {
    var knopf = ereignis.target.closest
      ? ereignis.target.closest(".tagknopf")
      : null;
    if (knopf) {
      tagWaehlen(knopf.getAttribute("data-tag"));
    }
  });

  overlayZu.addEventListener("click", overlaySchliessen);

  /* Tippen neben den Kasten schließt ebenfalls – auf einem Touchscreen die
   * naheliegendste Geste. */
  overlay.addEventListener("click", function (ereignis) {
    if (ereignis.target === overlay) {
      overlaySchliessen();
    }
  });

  document.addEventListener("keydown", function (ereignis) {
    if (ereignis.key !== "Escape") {
      return;
    }
    if (offeneSchicht) {
      overlaySchliessen();
    } else if (offenerTag) {
      tagWaehlen("");
    }
  });

  /* --- Auffrischen -------------------------------------------------------- */

  function holen() {
    /* Der Tagesblick frischt sich mit auf: wer den Sonntag durchgeht, während
     * im Backoffice jemand einteilt, soll die neuen Zahlen sehen.
     *
     * Kein AbortSignal.timeout: das kennen ältere Browser nicht, und auf so
     * einem Monitor steht gern etwas Betagtes. Bleibt die Antwort aus, greift
     * beim nächsten Durchlauf ohnehin dieselbe Warnung. */
    var gefragterTag = offenerTag;
    var adresse = gefragterTag
      ? quelle + "?tag=" + encodeURIComponent(gefragterTag)
      : quelle;

    fetch(adresse, { cache: "no-store", credentials: "same-origin" })
      .then(function (antwort) {
        if (!antwort.ok) {
          throw new Error("HTTP " + antwort.status);
        }
        return antwort.text();
      })
      .then(function (text) {
        /* Zwischen Absenden und Antwort kann jemand den Tag gewechselt haben.
         * Dann gehört diese Antwort nicht mehr auf den Bildschirm. */
        if (gefragterTag !== offenerTag) {
          return;
        }
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
  leisteMarkieren();
  setInterval(sekundentakt, 1000);
  setInterval(holen, intervall);
})();
