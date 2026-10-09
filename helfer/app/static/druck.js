// Der Knopf „Drucken“ der Druckansichten. Ein eigenes Skript statt eines
// onclick im HTML – die CSP lässt keine Skripte im Text zu.
(function () {
  "use strict";
  Array.prototype.forEach.call(document.querySelectorAll("[data-drucken]"), function (knopf) {
    knopf.addEventListener("click", function () { window.print(); });
  });
})();
