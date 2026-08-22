// Client-side YAML validation for the batch field.
//
// On submit, the batch YAML is parsed in the browser with js-yaml. If the
// syntax is invalid, the submission is cancelled and the parser's error
// (with line/column) is shown under the field. Semantic validation (unknown
// keys, bad URLs, ...) still happens on the server.

(function () {
  "use strict";

  function init() {
    var form = document.querySelector('[data-panel="batch"] form');
    var textarea = document.getElementById("batch-yaml");
    var errorEl = document.getElementById("batch-yaml-error");
    if (!form || !textarea || !errorEl) return;
    if (typeof jsyaml === "undefined") return; // CDN unavailable; server still validates

    form.addEventListener("htmx:configRequest", function (event) {
      errorEl.hidden = true;
      textarea.classList.remove("input-invalid");

      var value = textarea.value;
      if (!value.trim()) return; // empty = run the example (server-side)

      try {
        jsyaml.load(value);
      } catch (exc) {
        event.preventDefault();
        var detail = "";
        if (exc.mark) {
          detail = " (line " + exc.mark.line + ", column " + exc.mark.column + ")";
        }
        errorEl.textContent = "Invalid YAML" + detail + ": " + (exc.reason || exc.message);
        errorEl.hidden = false;
        textarea.classList.add("input-invalid");
      }
    });

    // Clear the error as soon as the user edits the text.
    textarea.addEventListener("input", function () {
      errorEl.hidden = true;
      textarea.classList.remove("input-invalid");
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
