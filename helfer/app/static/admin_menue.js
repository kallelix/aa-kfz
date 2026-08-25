/* Schliesst das zusammengefasste Menue in der Hauptnavigation wieder.
 *
 * Das Auf- und Zuklappen selbst macht der Browser (details/summary) - ohne
 * Skript funktioniert das Menue also vollstaendig, es bliebe nur offen
 * stehen, bis man den Punkt erneut trifft. Ein aufgeklapptes Menue liegt
 * ueber der Seite; wer daneben tippt, meint damit fast immer "zu".
 */
(function () {
  "use strict";

  function menues() {
    return document.querySelectorAll("details[data-menue]");
  }

  function schliessen(ausser) {
    Array.prototype.forEach.call(menues(), function (menue) {
      if (menue !== ausser) {
        menue.open = false;
      }
    });
  }

  document.addEventListener("click", function (ereignis) {
    var offen = null;
    Array.prototype.forEach.call(menues(), function (menue) {
      if (menue.open && menue.contains(ereignis.target)) {
        offen = menue;
      }
    });
    /* Ein Klick im Menue selbst ist entweder der Punkt zum Zuklappen oder ein
     * Ziel, das die Seite ohnehin wechselt - beides braucht uns nicht. */
    schliessen(offen);
  });

  document.addEventListener("keydown", function (ereignis) {
    if (ereignis.key !== "Escape") {
      return;
    }
    Array.prototype.forEach.call(menues(), function (menue) {
      if (!menue.open) {
        return;
      }
      menue.open = false;
      /* Zurueck auf den Punkt, von dem aus geoeffnet wurde - sonst faengt
       * die Tabulatortaste wieder ganz vorn an. */
      var knopf = menue.querySelector("summary");
      if (knopf) {
        knopf.focus();
      }
    });
  });
})();
