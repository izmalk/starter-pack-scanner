"""HTTP client with retries for live-site checks."""

from __future__ import annotations

import time

import requests

_USER_AGENT = "starter-pack-scanner/0.1 (+https://github.com/canonical/starter-pack-scanner)"
_TIMEOUT = 15  # seconds
_ATTEMPTS = 3
_PAUSE = 2  # seconds between attempts

_session = requests.Session()
_session.headers.update({"User-Agent": _USER_AGENT})


def get(url: str, *, allow_redirects: bool = True, headers: dict | None = None) -> tuple[requests.Response | None, str | None]:
    """GET *url* with retries.

    Retries on connection errors and 5xx responses, pausing between attempts.
    Returns a ``(response, error)`` tuple; exactly one element is None.

    *headers* (optional) are merged into the session's default headers for
    this request only (used e.g. for the optional RTD API ``Authorization``
    token — see ``rtd.py``).
    """
    last_error: str | None = None
    for attempt in range(1, _ATTEMPTS + 1):
        try:
            resp = _session.get(
                url, timeout=_TIMEOUT, allow_redirects=allow_redirects, headers=headers
            )
            if resp.status_code >= 500 and attempt < _ATTEMPTS:
                last_error = f"HTTP {resp.status_code}"
                time.sleep(_PAUSE)
                continue
            return resp, None
        except requests.RequestException as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < _ATTEMPTS:
                time.sleep(_PAUSE)
    return None, last_error
