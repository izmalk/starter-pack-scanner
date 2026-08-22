// Tab switching between single-scan and batch-scan panels, plus
// auto-scrolling to the results once HTMX swaps them in.

(function () {
  "use strict";

  var tabs = document.querySelectorAll(".tab");
  var panels = document.querySelectorAll("[data-panel]");
  var resultsContainers = document.querySelectorAll(".results-container");

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
      // Each tab owns its own results container: switching tabs swaps the
      // visible results too, so a batch report never leaks into the single
      // tab's view (and vice versa).
      resultsContainers.forEach(function (r) {
        r.hidden = r.id !== "results-" + name;
      });
    });
  });

  // After a scan finishes, bring the results into view — otherwise the
  // report can render below the fold and look like nothing happened.
  document.body.addEventListener("htmx:afterSwap", function (event) {
    if (!event.target.classList || !event.target.classList.contains("results-container")) return;
    if (!event.target.innerHTML.trim()) return;
    event.target.scrollIntoView({ behavior: "smooth", block: "start" });
  });
})();
