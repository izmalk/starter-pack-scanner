// Convert report timestamps from UTC to the viewer's local timezone.
//
// The server renders timestamps in UTC inside <time datetime="..."> elements
// (with a UTC fallback text). This script rewrites the visible text to the
// local timezone using Intl.DateTimeFormat — no permissions, no storage,
// no extra requests; the browser already knows the local timezone.

(function () {
  "use strict";

  function formatLocal(iso) {
    var date = new Date(iso);
    if (isNaN(date.getTime())) return null;
    var pad = function (n) { return String(n).padStart(2, "0"); };
    // DD.MM.YY HH:MM (TZ)
    var datePart = pad(date.getDate()) + "." + pad(date.getMonth() + 1) +
      "." + pad(String(date.getFullYear()).slice(2));
    var timePart = pad(date.getHours()) + ":" + pad(date.getMinutes());
    // Short timezone name, e.g. "UTC+1", "BST", "CEST".
    var tz = new Intl.DateTimeFormat(undefined, { timeZoneName: "short" })
      .formatToParts(date)
      .filter(function (p) { return p.type === "timeZoneName"; })
      .map(function (p) { return p.value; })[0];
    return datePart + " " + timePart + (tz ? " (" + tz + ")" : "");
  }

  function convert(root) {
    var elements = (root || document).querySelectorAll("time.timestamp[datetime]");
    elements.forEach(function (el) {
      var local = formatLocal(el.getAttribute("datetime"));
      if (local) el.textContent = local;
    });
  }

  // Convert on initial load.
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { convert(document); });
  } else {
    convert(document);
  }

  // Convert again whenever HTMX swaps in new content.
  document.body.addEventListener("htmx:afterSwap", function (event) {
    convert(event.target);
  });
})();
