/* Die öffentliche Anmeldung (Lastenheft 2.2) – nur Komfort.
 *
 * Ohne dieses Skript geht alles: die Auswahl ist ein Formular, der Server
 * prüft beim Absenden. Mit ihm zählt die Leiste mit, was gewählt ist, und
 * Schichten, die sich mit einer gewählten überschneiden, sind ausgegraut –
 * mit Grund (K-01). Dazu die Filter nach Tag und Bereich.
 */
(function () {
  "use strict";

  // --- Auswahl der Schichten ---------------------------------------------
  var form = document.querySelector("form[data-auswahl]");
  if (form) {
    var karten = Array.prototype.slice.call(form.querySelectorAll("[data-schicht]"));
    var weiter = document.getElementById("weiter");
    var filter = { tag: "", bereich: "" };

    var kaestchen = function (karte) { return karte.querySelector('input[name="s"]'); };
    var ueberschneiden = function (a, b) {
      return a.dataset.beginn < b.dataset.ende && b.dataset.beginn < a.dataset.ende;
    };

    var aktualisieren = function () {
      var gewaehlt = karten.filter(function (k) { var b = kaestchen(k); return b && b.checked; });
      karten.forEach(function (karte) {
        var box = kaestchen(karte);
        var grund = karte.querySelector("[data-grund]");
        if (!box) { return; }
        karte.classList.toggle("gewaehlt", box.checked);
        var konflikt = box.checked ? null : gewaehlt.filter(function (g) {
          return ueberschneiden(g, karte);
        })[0];
        box.disabled = !!konflikt;
        karte.classList.toggle("gesperrt", !!konflikt);
        if (grund) {
          grund.textContent = konflikt ? "Überschneidet sich mit " + konflikt.dataset.text : "";
        }
      });
      var springer = form.querySelectorAll('input[name="z"]:checked').length;
      // Die Warteliste (R-04) zählt mit, sperrt aber nichts: ob es sich mit
      // etwas überschneidet, zählt erst, wenn ein Platz frei wird.
      var n = gewaehlt.length + form.querySelectorAll('input[name="w"]:checked').length;
      weiter.textContent = n ? "Weiter mit " + n + (n === 1 ? " Schicht" : " Schichten")
        : springer ? "Weiter als Springer" : "Erst eine Schicht wählen";
      weiter.disabled = !n && !springer;
    };

    var filtern = function () {
      karten.forEach(function (karte) {
        var passt = (!filter.tag || karte.dataset.tag === filter.tag) &&
          (!filter.bereich || karte.dataset.bereich === filter.bereich);
        karte.classList.toggle("ausgeblendet", !passt);
      });
      Array.prototype.forEach.call(form.querySelectorAll(".tagkopf"), function (kopf) {
        var sichtbar = karten.some(function (k) {
          return k.dataset.tag === kopf.dataset.tag && !k.classList.contains("ausgeblendet");
        });
        kopf.classList.toggle("ausgeblendet", !sichtbar);
      });
    };

    Array.prototype.forEach.call(form.querySelectorAll("[data-filter]"), function (leiste) {
      leiste.hidden = false;
      leiste.addEventListener("click", function (ereignis) {
        var knopf = ereignis.target.closest("button");
        if (!knopf) { return; }
        filter[leiste.dataset.filter] = knopf.dataset.wert;
        Array.prototype.forEach.call(leiste.querySelectorAll("button"), function (b) {
          b.setAttribute("aria-pressed", String(b === knopf));
        });
        filtern();
      });
    });

    form.addEventListener("change", aktualisieren);
    aktualisieren();
  }

  // --- Angaben: das Geburtsdatum nur, wenn jemand jünger als 18 ist --------
  Array.prototype.forEach.call(document.querySelectorAll("[data-nur-juenger]"), function (feld) {
    var praefix = feld.dataset.nurJuenger;
    var radios = document.querySelectorAll('input[name="' + praefix + 'volljaehrig"]');
    var zeigen = function () {
      var nein = document.querySelector('input[name="' + praefix + 'volljaehrig"][value="nein"]');
      feld.hidden = !(nein && nein.checked);
    };
    Array.prototype.forEach.call(radios, function (r) { r.addEventListener("change", zeigen); });
    zeigen();
  });
})();
