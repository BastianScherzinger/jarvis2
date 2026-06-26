/* Kostenrechner — unverbindliche Sofort-Schätzung im Hero.
   Liest die Branchen-Posten aus <script id="rechner-data"> (Django json_script),
   baut die Leistungs-Auswahl, rechnet Posten × Umfang → Preisspanne. Rein clientseitig,
   render-sicher: fehlen Daten, wird die Karte sauber ausgeblendet. */
(function () {
  "use strict";

  var DEFAULT_POSTEN = [
    { name: "Kleiner Auftrag", ab: 150, bis: 600 },
    { name: "Mittleres Projekt", ab: 600, bis: 3000 },
    { name: "Großes Projekt", ab: 3000, bis: 15000 }
  ];
  // Umfang-Stufen: klein/mittel/groß → Faktor auf die Richtwert-Spanne.
  var UMFANG = { 1: { lbl: "klein", f: 0.7 }, 2: { lbl: "mittel", f: 1.0 }, 3: { lbl: "groß", f: 1.45 } };

  function readData() {
    var el = document.getElementById("rechner-data");
    if (!el) return null;
    try {
      var d = JSON.parse(el.textContent || "null");
      if (d && Array.isArray(d.posten) && d.posten.length) return d;
    } catch (e) { /* fällt unten auf Default */ }
    return null;
  }

  function euro(n) {
    return new Intl.NumberFormat("de-DE", {
      style: "currency", currency: "EUR", maximumFractionDigits: 0
    }).format(Math.max(0, Math.round(n / 10) * 10));
  }

  function init() {
    var card = document.querySelector(".hero-rechner");
    if (!card) return;
    var data = readData();
    var posten = (data && data.posten) || DEFAULT_POSTEN;

    var sel = document.getElementById("hr-leistung");
    var range = document.getElementById("hr-umfang");
    var umfLbl = document.getElementById("hr-umfang-lbl");
    var out = document.getElementById("hr-result");
    if (!sel || !range || !out) return;

    posten.forEach(function (p, i) {
      var o = document.createElement("option");
      o.value = String(i);
      o.textContent = p.name;
      sel.appendChild(o);
    });

    function update() {
      var p = posten[parseInt(sel.value, 10) || 0] || posten[0];
      var u = UMFANG[range.value] || UMFANG[2];
      if (umfLbl) umfLbl.textContent = u.lbl;
      var lo = (p.ab || 0) * u.f;
      var hi = (p.bis || p.ab || 0) * u.f;
      out.textContent = "ca. " + euro(lo) + " – " + euro(hi);
    }

    sel.addEventListener("change", update);
    range.addEventListener("input", update);
    update();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
