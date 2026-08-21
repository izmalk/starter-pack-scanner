// Tri-state theme toggle: auto → light → dark → auto.
// Dark mode is applied via Vanilla Framework's `is-dark` class on <html>:
// - "auto"  → class follows the OS prefers-color-scheme setting
// - "light" → class removed
// - "dark"  → class added
// The choice persists in localStorage; `data-theme` records the current
// mode so the CSS can show the matching toggle icon.

(function () {
  "use strict";

  var STORAGE_KEY = "sps-theme";
  var MODES = ["auto", "light", "dark"];
  var LABELS = { auto: "Auto", light: "Light", dark: "Dark" };

  var root = document.documentElement;
  var button = document.getElementById("theme-toggle");
  var label = button ? button.querySelector("[data-label]") : null;
  var media = window.matchMedia("(prefers-color-scheme: dark)");

  function systemPrefersDark() {
    return media.matches;
  }

  function apply(mode) {
    root.setAttribute("data-theme", mode);
    var dark = mode === "dark" || (mode === "auto" && systemPrefersDark());
    root.classList.toggle("is-dark", dark);
    if (label) label.textContent = LABELS[mode] || mode;
  }

  function current() {
    var stored = null;
    try {
      stored = localStorage.getItem(STORAGE_KEY);
    } catch (e) {
      /* localStorage unavailable (private mode etc.) — stay on auto */
    }
    return MODES.indexOf(stored) !== -1 ? stored : "auto";
  }

  function save(mode) {
    try {
      localStorage.setItem(STORAGE_KEY, mode);
    } catch (e) {
      /* ignore */
    }
  }

  // Apply the persisted theme as early as possible to avoid a flash.
  apply(current());

  // In auto mode, follow OS theme changes live.
  if (media.addEventListener) {
    media.addEventListener("change", function () {
      if (current() === "auto") apply("auto");
    });
  }

  if (button) {
    button.addEventListener("click", function () {
      var next = MODES[(MODES.indexOf(current()) + 1) % MODES.length];
      apply(next);
      save(next);
    });
  }
})();
