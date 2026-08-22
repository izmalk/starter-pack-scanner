/* Retro progress modal controller.
 *
 * Flow (HTMX):
 *  1. The scan form posts to /scan or /batch. The response is the
 *     _progress.html modal shell, swapped into the form's results container
 *     (#results-single or #results-batch). The modal is styled as a fixed
 *     overlay, so it floats above the page regardless of where it lands.
 *  2. Inside the modal, #progress-poll polls /progress/{job_id} every
 *     400ms; each poll swaps in the updated bar (_progress_bar.html).
 *  3. When the job finishes, the poll response contains #progress-done
 *     with the final results HTML inside. This script detects it, moves
 *     the results into the owning container, and removes the modal.
 */
(function () {
  "use strict";

  var POLL_INTERVAL_MS = 400;

  function isModal(el) {
    return el && el.id === "progress-modal";
  }

  // When the modal shell first arrives (swapped into a results container),
  // stamp it with that container's selector so the completion handler knows
  // where to put the finished report.
  document.addEventListener("htmx:afterSwap", function (evt) {
    var target = evt.target;
    if (!target || !target.classList || !target.classList.contains("results-container")) return;
    var modal = target.querySelector("#progress-modal");
    if (modal && !modal.getAttribute("data-results-target")) {
      modal.setAttribute("data-results-target", "#" + target.id);
    }
  });

  // Watch for the poll response landing inside the modal. HTMX fires
  // afterSwap on the polling element's parent for each poll.
  document.addEventListener("htmx:afterSwap", function (evt) {
    var target = evt.target;
    if (!target || !target.closest || !target.closest("#progress-modal")) return;

    var done = target.querySelector("#progress-done") ||
               (target.id === "progress-done" ? target : null);
    if (!done) return;

    var modal = document.getElementById("progress-modal");
    // Results go into the container owned by the tab that started the scan:
    // the modal carries data-results-target (set when the modal arrived).
    var selector = modal && modal.getAttribute("data-results-target");
    var results = selector ? document.querySelector(selector) : null;
    var status = done.getAttribute("data-status");

    if (status === "ok" && results) {
      // Move the rendered report out of the modal into the results area.
      results.innerHTML = "";
      while (done.firstChild) {
        results.appendChild(done.firstChild);
      }
      // The moved nodes were never part of an HTMX swap, so HTMX hasn't
      // wired up their hx-* attributes (e.g. the Re-scan buttons). Process
      // them explicitly.
      if (window.htmx && window.htmx.process) {
        window.htmx.process(results);
      }
    } else if (status === "error" && results) {
      results.innerHTML = "";
      var card = document.createElement("section");
      card.className = "card error-card";
      card.setAttribute("role", "alert");
      var h2 = document.createElement("h2");
      h2.textContent = "Scan failed";
      var p = document.createElement("p");
      p.textContent = done.textContent.trim();
      card.appendChild(h2);
      card.appendChild(p);
      results.appendChild(card);
    } else if (status === "gone" && results) {
      results.innerHTML = "";
      var note = document.createElement("p");
      note.className = "muted";
      note.textContent = done.textContent.trim();
      results.appendChild(note);
    }

    if (modal) modal.remove();
  });

  // Safety net: if the modal is present but polling has stopped (e.g. an
  // HTMX error), poll manually so the user is never stuck. Also stamps the
  // modal with the results container of the form that started the scan.
  document.addEventListener("htmx:afterSwap", function (evt) {
    if (!isModal(evt.target)) return;

    var modal = evt.target;
    var poll = modal.querySelector("#progress-poll");
    if (!poll) return;
    var url = poll.getAttribute("hx-get");
    if (!url) return;

    var timer = setInterval(function () {
      // Stop once the modal is gone (job finished via the normal path).
      if (!document.getElementById("progress-modal")) {
        clearInterval(timer);
        return;
      }
      // Stop if HTMX is still polling on its own (element still present
      // with the trigger attribute and no #progress-done yet).
      if (document.getElementById("progress-done")) {
        clearInterval(timer);
        return;
      }
      fetch(url, { headers: { "HX-Request": "true" } })
        .then(function (r) { return r.text(); })
        .then(function (text) {
          if (text.indexOf('id="progress-done"') !== -1) {
            // Inject and let the afterSwap handler above process it.
            poll.innerHTML = text;
            poll.dispatchEvent(new CustomEvent("htmx:afterSwap", { bubbles: true }));
          }
        })
        .catch(function () { /* transient network error — keep trying */ });
    }, POLL_INTERVAL_MS * 3);
  });
})();
