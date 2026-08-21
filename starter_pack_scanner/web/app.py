"""Local web GUI for the starter pack scanner (FastAPI + Jinja2 + HTMX).

Run with ``starter-pack-scanner-web`` (installed with the ``web`` extra) or:

    python -m starter_pack_scanner.web.app

The server binds to 127.0.0.1 only — it is intended for local use and is
not protected by any authentication.
"""

from __future__ import annotations

import threading
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from starter_pack_scanner import cache
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


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    """Render the scan form."""
    return _TEMPLATES.TemplateResponse(request=request, name="index.html")


@app.post("/scan", response_class=HTMLResponse)
def run_scan(
    request: Request,
    repo_url: str = Form(default=""),
    docs_url: str = Form(default=""),
    branch: str = Form(default=""),
    refresh: str = Form(default=""),
) -> HTMLResponse:
    """Run a scan (or serve a cached report) and return the results partial."""
    repo_url = repo_url.strip()
    docs_url = docs_url.strip() or None
    branch = branch.strip() or None
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

    key = cache.cache_key(repo_url=repo_url, branch=branch, docs_url=docs_url)

    if not force_refresh:
        cached = cache.get(key)
        if cached is not None:
            return render(report=cached, cached=True)

    # Block until a scan slot is free; sync endpoint → FastAPI threadpool,
    # so waiting here does not stall the event loop.
    with _SCAN_SLOTS:
        report = scan(repo_url=repo_url, branch=branch, docs_url=docs_url)
        cache.put(key, report)

    return render(report=report, cached=False)


def main() -> None:
    """Entry point: run the local server."""
    import uvicorn

    print(f"Starter Pack Scanner web GUI: http://{_HOST}:{_PORT}")
    print("Press Ctrl+C to stop.")
    uvicorn.run(app, host=_HOST, port=_PORT, log_level="warning")


if __name__ == "__main__":
    main()
