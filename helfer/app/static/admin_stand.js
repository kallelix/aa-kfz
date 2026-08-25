/* Fragt im Backoffice nach, ob inzwischen jemand unterschrieben hat.
 *
 * Kein WebSocket. Der bräuchte einen Umbau am nginx (Upgrade-Header, längeres
 * proxy_read_timeout), Wiederverbinden mit Backoff nach jedem Netzzucken und
 * trotzdem einen Abgleich für die in der Lücke verpassten Nachrichten – also
 * am Ende beides. Und er hätte eine Falle: die Verteilung liefe über eine
 * Liste offener Verbindungen im Prozess, und mit einem zweiten uvicorn-Worker
 * bekäme die Hälfte der Geräte stillschweigend nichts mehr.
 *
 * Zwei bis drei Sekunden Verzögerung sind an einem Ausgabetisch nicht
 * wahrnehmbar. Der Preis dafür ist eine kleine Anfrage im Takt, die nur
 * zurückgibt, was sich seit der letzten geändert hat.
 *
 * Wichtig: es wird NICHT neu geladen. In den Listen steht eine Suche, die
 * jemand getippt hat, und ein Bildlauf, an dem er gerade ist – beides wäre
 * nach einem Neuladen weg, und genau das ist der Grund, warum es hier
 * überhaupt etwas zu tun gibt.
 */
(function () {
  "use strict";

  var skript = document.currentScript;
  var marke = Number(skript.getAttribute("data-marke") || 0);
  var takt = Number(skript.getAttribute("data-takt") || 3) * 1000;
  if (!(takt >= 1000)) {
    return; /* abgeschaltet */
  }

  var leiste = document.getElementById("tabletleiste");
  var leisteTitel = document.getElementById("tabletleiste-titel");
  var leistePerson = document.getElementById("tabletleiste-person");

  /* Welche Art von Vorgängen auf dieser Seite steht – dann muss die Antwort
   * nur die betreffenden tragen. Ohne Treffer fragen wir nach allem, damit
   * die Leiste oben trotzdem stimmt. */
  function art() {
    var feld = document.querySelector("[data-unterschrift]");
    if (!feld) {
      return "";
    }
    return feld.getAttribute("data-unterschrift").split("-")[0];
  }

  var meineArt = art();

  function leisteSetzen(offen) {
    if (!leiste) {
      return;
    }
    leiste.classList.toggle("weg", !offen);
    if (offen) {
      leisteTitel.textContent = offen.titel || "";
      leistePerson.textContent = offen.person || "";
    }
  }

  function eintragen(neu) {
    var kennung = neu.art + "-" + neu.vorgang_id + "-" + neu.richtung;
    var feld = document.querySelector('[data-unterschrift="' + kennung + '"]');
    if (!feld) {
      return;
    }
    /* textContent statt innerHTML: der Name kommt aus einer Eingabe am
     * Tablet und hat im Markup nichts verloren. */
    var marke2 = document.createElement("span");
    marke2.className = "marke marke-voll";
    marke2.textContent = "unterschrieben";
    if (neu.wann) {
      marke2.title = "unterschrieben " + neu.wann
        + (neu.person ? " von " + neu.person : "");
    }
    feld.innerHTML = "";
    feld.appendChild(marke2);

    /* In einer langen Liste übersieht man die Änderung sonst. */
    var zeile = feld.closest ? feld.closest("tr") : null;
    if (zeile) {
      zeile.classList.remove("frisch");
      /* Neu anstoßen, damit die Hervorhebung auch beim zweiten Mal läuft. */
      void zeile.offsetWidth;
      zeile.classList.add("frisch");
    }
  }

  function nachfragen() {
    var adresse = "/admin/stand?seit=" + encodeURIComponent(marke)
      + (meineArt ? "&art=" + encodeURIComponent(meineArt) : "");
    fetch(adresse, { cache: "no-store", credentials: "same-origin" })
      .then(function (antwort) {
        if (!antwort.ok) {
          throw new Error("HTTP " + antwort.status);
        }
        return antwort.json();
      })
      .then(function (daten) {
        marke = daten.marke;
        leisteSetzen(daten.offen);
        (daten.neu || []).forEach(eintragen);
      })
      .catch(function () {
        /* Kein Netz oder abgemeldet: beim nächsten Takt wieder. Die Seite
         * bleibt stehen, wie sie ist. */
      });
  }

  setInterval(nachfragen, takt);
})();
