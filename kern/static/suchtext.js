/* Suchbegriffe normalisieren - dieselbe Umformung wie kern/suchen.py.
 *
 * Die Listen filtern im Browser: der durchsuchbare Text steht als
 * data-suche an der Zeile, der Suchbegriff kommt aus dem Eingabefeld. Beide
 * muessen durch dieselbe Muehle, sonst findet ein getippter Umlaut nichts -
 * genau das war der Fehler, aus dem diese Datei entstanden ist.
 *
 * Dass Python und JavaScript hier dasselbe tun, prueft
 * tests/test_suchen_js.js gegen genau diese Datei.
 */
(function (global) {
  "use strict";

  /* Was aufgeloest wird, bevor die Diakritika fallen. Das scharfe S steht
   * nicht hier, sondern schon in grundform - siehe kern/suchen.py: Pythons
   * casefold() loest es auf, toLowerCase() nicht. Beide machen es deshalb
   * ausdruecklich, sonst gehen sie auseinander. */
  var DEUTSCH = [["ä", "ae"], ["ö", "oe"], ["ü", "ue"]];

  function grundform(roh) {
    return String(roh === undefined || roh === null ? "" : roh)
      .toLowerCase()
      .split("ß").join("ss")
      .replace(/\s+/g, " ")
      .trim();
  }

  function entkleidet(text) {
    /* NFD zerlegt "ä" in "a" und ein kombinierendes Zeichen; die Klasse
     * Mark/nonspacing faellt danach weg. Entspricht unicodedata.combining
     * in Python. */
    return text.normalize("NFKD").replace(/\p{Mn}/gu, "");
  }

  /* Die Schreibweisen, unter denen ein Text zu finden sein soll. Immer
   * mindestens eine; die zweite nur, wenn sie sich unterscheidet. */
  function varianten(roh) {
    var grund = grundform(roh);
    if (grund === "") {
      return [];
    }
    var deutsch = grund;
    for (var i = 0; i < DEUTSCH.length; i += 1) {
      deutsch = deutsch.split(DEUTSCH[i][0]).join(DEUTSCH[i][1]);
    }
    deutsch = entkleidet(deutsch);
    var blank = entkleidet(grund);
    return deutsch === blank ? [deutsch] : [deutsch, blank];
  }

  function suchtext() {
    var teile = [];
    for (var i = 0; i < arguments.length; i += 1) {
      if (arguments[i]) {
        teile.push(arguments[i]);
      }
    }
    return varianten(teile.join(" ")).join(" ");
  }

  /* Ob der Suchbegriff in irgendeiner seiner Schreibweisen vorkommt. */
  function passt(heuhaufen, nadel) {
    var gesucht = varianten(nadel);
    if (gesucht.length === 0) {
      return true;
    }
    var heu = String(heuhaufen || "");
    for (var i = 0; i < gesucht.length; i += 1) {
      if (heu.indexOf(gesucht[i]) !== -1) {
        return true;
      }
    }
    return false;
  }

  var werkzeug = {varianten: varianten, suchtext: suchtext, passt: passt};

  if (typeof module !== "undefined" && module.exports) {
    module.exports = werkzeug;      /* fuer den Abgleich unter node */
  }
  global.Suchtext = werkzeug;
})(typeof globalThis !== "undefined" ? globalThis : this);
