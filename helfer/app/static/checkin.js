/* Check-in (Lastenheft 4.1, T-01) – nur Komfort.
 *
 * Ohne dieses Skript geht alles: ein Scanner schreibt den Code ins Suchfeld
 * wie eine Tastatur, und wer nichts dabeihat, wird nach dem Namen gesucht.
 * Mit ihm lässt sich der Code auch mit der Kamera lesen – aber nur, wo der
 * Browser QR-Codes selbst erkennt (BarcodeDetector). Kein Skript von außen.
 */
(function () {
  "use strict";

  var form = document.querySelector("form[data-checkin]");
  var knopf = form && form.querySelector("[data-kamera]");
  var bild = form && form.querySelector("[data-bild]");
  if (!form || !knopf || !bild || !("BarcodeDetector" in window) ||
      !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    return;
  }

  var leser;
  try {
    leser = new window.BarcodeDetector({ formats: ["qr_code"] });
  } catch (fehler) {
    return;
  }
  knopf.hidden = false;

  var strom = null;
  var anhalten = function () {
    if (strom) {
      strom.getTracks().forEach(function (spur) { spur.stop(); });
      strom = null;
    }
    bild.hidden = true;
    knopf.textContent = "Mit der Kamera scannen";
  };

  var suchen = function () {
    if (!strom) { return; }
    leser.detect(bild).then(function (codes) {
      if (codes.length) {
        form.querySelector('input[name="q"]').value = codes[0].rawValue;
        anhalten();
        form.submit();
        return;
      }
      window.setTimeout(suchen, 250);
    }).catch(function () { window.setTimeout(suchen, 500); });
  };

  knopf.addEventListener("click", function () {
    if (strom) { anhalten(); return; }
    navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } })
      .then(function (s) {
        strom = s;
        bild.srcObject = s;
        bild.hidden = false;
        knopf.textContent = "Kamera aus";
        return bild.play();
      })
      .then(suchen)
      .catch(anhalten);
  });
})();
