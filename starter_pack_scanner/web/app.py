"""Local web GUI for the starter pack scanner (FastAPI + Jinja2 + HTMX).

Run with ``starter-pack-scanner-web`` or:

    python -m starter_pack_scanner.web.app

The web GUI dependencies are part of the default install; for a CLI-only
install use ``pip install -e '.[cli]'``.

The server binds to 127.0.0.1 only — it is intended for local use and is
not protected by any authentication.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from starter_pack_scanner import cache
from starter_pack_scanner.batch import (
    EXAMPLE_BATCH_YAML,
    BatchEntry,
    BatchFileError,
    load_batch,
    run_batch,
)
from starter_pack_scanner.scanner import scan, validate_repo_url

_WEB_DIR = Path(__file__).parent
_TEMPLATES = Jinja2Templates(directory=str(_WEB_DIR / "templates"))

# Cap the number of concurrent scans: each scan runs a git clone and
# several HTTP requests, so a small limit keeps the machine responsive.
_SCAN_SLOTS = threading.Semaphore(2)

_HOST = "127.0.0.1"
_PORT = 8765

app = FastAPI(title="Starter Pack Scanner", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(_WEB_DIR / "static")), name="static")


# ---------------------------------------------------------------------------
# Background scan jobs (for the HTMX progress modal)
# ---------------------------------------------------------------------------


@dataclass
class _Job:
    """One background scan and its progress state."""

    percent: int = 0
    step: str = "Starting…"
    done: bool = False
    # Rendered results HTML (or an error message) once done.
    html: str = ""
    error: str | None = None


_JOBS: dict[str, _Job] = {}
_JOBS_LOCK = threading.Lock()
_JOBS_MAX = 20  # drop oldest when exceeded (abandoned polls must not leak)


def _new_job() -> str:
    with _JOBS_LOCK:
        if len(_JOBS) >= _JOBS_MAX:
            oldest = next(iter(_JOBS))
            del _JOBS[oldest]
        job_id = uuid.uuid4().hex[:12]
        _JOBS[job_id] = _Job()
        return job_id


def _job_update(job_id: str, percent: int, step: str) -> None:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if job is not None:
            job.percent = percent
            job.step = step


def _job_finish(job_id: str, html: str, error: str | None = None) -> None:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if job is not None:
            job.percent = 100
            job.step = "Done"
            job.done = True
            job.html = html
            job.error = error


def _job_pop(job_id: str) -> _Job | None:
    with _JOBS_LOCK:
        return _JOBS.pop(job_id, None)


def _is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request", "").lower() == "true"


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    """Render the scan form."""
    return _TEMPLATES.TemplateResponse(
        request=request, name="index.html", context={"example_batch": EXAMPLE_BATCH_YAML}
    )


@app.post("/scan", response_class=HTMLResponse)
def run_scan(
    request: Request,
    repo_url: str = Form(default=""),
    docs_url: str = Form(default=""),
    branch: str = Form(default=""),
    refresh: str = Form(default=""),
    check_group: str = Form(default=""),
    rtd_project: str = Form(default=""),
) -> HTMLResponse:
    """Run a scan (or serve a cached report) and return the results partial.

    HTMX requests get an async job + progress modal; plain (non-HTMX) posts
    run synchronously and return the final report directly.
    """
    repo_url = repo_url.strip()
    docs_url = docs_url.strip() or None
    branch = branch.strip() or None
    check_group = check_group.strip() or None
    rtd_project = rtd_project.strip() or None
    force_refresh = refresh.strip().lower() in {"1", "true", "on"}

    def render(error: str | None = None, **context) -> HTMLResponse:
        return _TEMPLATES.TemplateResponse(
            request=request,
            name="_results.html",
            context={"repo_url": repo_url, "docs_url": docs_url, "branch": branch, "error": error, **context},
        )

    if not repo_url:
        return render(error="Please enter a repository URL.")

    url_error = validate_repo_url(repo_url)
    if url_error:
        return render(error=url_error)

    if docs_url is not None:
        docs_error = validate_repo_url(docs_url)
        if docs_error:
            return render(error=f"Invalid docs URL: {docs_error}")

    # Fold the check group into the cache key via its include set, so
    # group-filtered scans don't collide with full scans.
    include_ids = None
    if check_group:
        from starter_pack_scanner.checks import checks_by_group

        include_ids = {c().id for c in checks_by_group(check_group)}

    key = cache.cache_key(
        repo_url=repo_url, branch=branch, docs_url=docs_url,
        include_checks=include_ids, rtd_project=rtd_project,
    )

    if not force_refresh:
        cached = cache.get(key)
        if cached is not None:
            return render(report=cached, cached=True)

    def run_and_render() -> str:
        """Run the scan and return the rendered results partial as HTML."""
        with _SCAN_SLOTS:
            report = scan(
                repo_url=repo_url,
                branch=branch,
                docs_url=docs_url,
                check_group=check_group,
                rtd_project=rtd_project,
                progress=lambda pct, step: _job_update(job_id, pct, step),
            )
            cache.put(key, report)
        return _TEMPLATES.get_template("_results.html").render(
            {
                "repo_url": repo_url,
                "docs_url": docs_url,
                "branch": branch,
                "error": None,
                "report": report,
                "cached": False,
            }
        )

    if not _is_htmx(request):
        # Synchronous path (tests, curl): run inline and return the report.
        with _SCAN_SLOTS:
            report = scan(
                repo_url=repo_url, branch=branch, docs_url=docs_url,
                check_group=check_group, rtd_project=rtd_project,
            )
            cache.put(key, report)
        return render(report=report, cached=False)

    # HTMX path: start a background job and return the progress modal.
    job_id = _new_job()

    def worker() -> None:
        try:
            html = run_and_render()
            _job_finish(job_id, html)
        except Exception as exc:  # pragma: no cover — defensive
            _job_finish(job_id, "", error=f"Scan failed: {exc}")

    threading.Thread(target=worker, daemon=True).start()
    return _TEMPLATES.TemplateResponse(
        request=request,
        name="_progress.html",
        context={"job_id": job_id, "title": "Scanning"},
    )


def _single_entry_yaml(entry: BatchEntry) -> str:
    """Serialise one batch entry back to YAML (for the per-tab Re-scan button)."""
    import yaml

    mapping: dict = {"repo": entry.repo}
    if entry.branch:
        mapping["branch"] = entry.branch
    if entry.docs_url:
        mapping["docs_url"] = entry.docs_url
    if entry.check_group:
        mapping["check_group"] = entry.check_group
    if entry.offline:
        mapping["offline"] = True
    if entry.exclude_checks:
        mapping["exclude_checks"] = sorted(entry.exclude_checks)
    if entry.include_checks:
        mapping["include_checks"] = sorted(entry.include_checks)
    if entry.rtd_project:
        mapping["rtd_project"] = entry.rtd_project
    return yaml.safe_dump({"repos": [mapping]}, sort_keys=False)


@app.post("/batch", response_class=HTMLResponse)
def run_batch_scan(
    request: Request,
    batch_yaml: str = Form(default=""),
    refresh: str = Form(default=""),
) -> HTMLResponse:
    """Run a batch scan from pasted YAML and return the batch results partial.

    HTMX requests get an async job + progress modal; plain posts run
    synchronously.
    """
    force_refresh = refresh.strip().lower() in {"1", "true", "on"}

    def render(error: str | None = None, **context) -> HTMLResponse:
        return _TEMPLATES.TemplateResponse(
            request=request,
            name="_batch_results.html",
            context={
                "error": error,
                "batch_yaml": batch_yaml,
                "single_entry_yaml": _single_entry_yaml,
                **context,
            },
        )

    # An empty field means "run the example" (shown as the placeholder).
    if not batch_yaml.strip():
        batch_yaml = EXAMPLE_BATCH_YAML

    # Parse the YAML locally so we can report syntax errors precisely.
    try:
        data = yaml.safe_load(batch_yaml)
    except yaml.YAMLError as exc:
        return render(error=f"Invalid YAML: {exc}")

    # Write to a temp file to reuse the full validation from load_batch.
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False) as f:
        f.write(batch_yaml)
        tmp = Path(f.name)
    try:
        try:
            entries = load_batch(tmp)
        except BatchFileError as exc:
            return render(error=str(exc))
    finally:
        tmp.unlink(missing_ok=True)

    def run_and_render() -> str:
        """Run the batch and return the rendered results partial as HTML."""
        with _SCAN_SLOTS:
            results = run_batch(
                entries,
                refresh=force_refresh,
                progress=lambda pct, step: _job_update(job_id, pct, step),
            )
        return _TEMPLATES.get_template("_batch_results.html").render(
            {
                "error": None,
                "batch_yaml": batch_yaml,
                "single_entry_yaml": _single_entry_yaml,
                "results": results,
            }
        )

    if not _is_htmx(request):
        # Synchronous path (tests, curl).
        with _SCAN_SLOTS:
            results = run_batch(entries, refresh=force_refresh)
        return render(results=results)

    # HTMX path: background job + progress modal.
    job_id = _new_job()

    def worker() -> None:
        try:
            html = run_and_render()
            _job_finish(job_id, html)
        except Exception as exc:  # pragma: no cover — defensive
            _job_finish(job_id, "", error=f"Batch scan failed: {exc}")

    threading.Thread(target=worker, daemon=True).start()
    return _TEMPLATES.TemplateResponse(
        request=request,
        name="_progress.html",
        context={"job_id": job_id, "title": "Batch scanning"},
    )


@app.get("/progress/{job_id}", response_class=HTMLResponse)
def progress(request: Request, job_id: str) -> HTMLResponse:
    """Poll endpoint for the progress modal.

    While the job runs: return the updated bar/percent/step partial (HTMX
    re-polls it). When done: return the final results HTML wrapped in a
    completion marker — the modal script swaps it into the owning results
    container and
    closes the modal.
    """
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
    if job is None:
        return HTMLResponse(
            '<div id="progress-done" data-status="gone">'
            "Scan job not found or already collected.</div>"
        )
    if not job.done:
        return _TEMPLATES.TemplateResponse(
            request=request,
            name="_progress_bar.html",
            context={"job_id": job_id, "percent": job.percent, "step": job.step},
        )
    # Done: hand back the results and remove the job so the dict stays small.
    _job_pop(job_id)
    if job.error:
        return HTMLResponse(
            f'<div id="progress-done" data-status="error">{job.error}</div>'
        )
    return HTMLResponse(
        f'<div id="progress-done" data-status="ok">{job.html}</div>'
    )


def main() -> None:
    """Entry point: run the local server."""
    import uvicorn

    print(f"Starter Pack Scanner web GUI: http://{_HOST}:{_PORT}")
    print("Press Ctrl+C to stop.")
    uvicorn.run(app, host=_HOST, port=_PORT, log_level="warning")


if __name__ == "__main__":
    main()
