// Tab switching between single-scan and batch-scan panels, plus
// auto-scrolling to the results once HTMX swaps them in.

(function () {
  "use strict";

  var tabs = document.querySelectorAll(".tab");
  var panels = document.querySelectorAll("[data-panel]");

  tabs.forEach(function (tab) {
    tab.addEventListener("click", function () {
      var name = tab.getAttribute("data-tab");
      tabs.forEach(function (t) {
        var active = t === tab;
        t.classList.toggle("tab-active", active);
        t.setAttribute("aria-selected", active ? "true" : "false");
      });
      panels.forEach(function (p) {
        p.hidden = p.getAttribute("data-panel") !== name;
      });
    });
  });

  // After a scan finishes, bring the results into view — otherwise the
  // report can render below the fold and look like nothing happened.
  document.body.addEventListener("htmx:afterSwap", function (event) {
    if (event.target.id !== "results") return;
    if (!event.target.innerHTML.trim()) return;
    event.target.scrollIntoView({ behavior: "smooth", block: "start" });
  });
})();
