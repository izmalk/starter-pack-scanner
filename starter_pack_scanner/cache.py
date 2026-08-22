"""On-disk cache for scan reports, shared by the CLI and the web GUI.

Each cached report is stored as one JSON file under the cache directory
(``~/.cache/starter-pack-scanner`` by default, honouring ``XDG_CACHE_HOME``).
There is no TTL: entries are refreshed explicitly via ``--no-cache`` /
the "Re-scan" button, or wiped with ``--clear-cache``.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from pathlib import Path

from starter_pack_scanner.scanner import ScanReport

_LOCK = threading.Lock()


def cache_dir() -> Path:
    """Return (and create) the cache directory."""
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    path = Path(base) / "starter-pack-scanner"
    path.mkdir(parents=True, exist_ok=True)
    return path


def cache_key(
    repo_url: str,
    branch: str | None = None,
    docs_url: str | None = None,
    include_checks: set[str] | None = None,
    exclude_checks: set[str] | None = None,
    offline: bool = False,
    seed: int | None = None,
    old_url: str | None = None,
) -> str:
    """Deterministic key for a scan configuration (SHA-256 hex digest)."""
    parts = (
        repo_url.strip().rstrip("/"),
        branch or "",
        (docs_url or "").strip().rstrip("/"),
        ",".join(sorted(include_checks)) if include_checks else "",
        ",".join(sorted(exclude_checks)) if exclude_checks else "",
        "offline" if offline else "online",
        str(seed) if seed is not None else "",
        (old_url or "").strip().rstrip("/"),
    )
    return hashlib.sha256("\x00".join(parts).encode()).hexdigest()


def get(key: str) -> ScanReport | None:
    """Return the cached report for *key*, or None if not cached."""
    path = cache_dir() / f"{key}.json"
    with _LOCK:
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            return None
    try:
        return ScanReport.from_dict(data)
    except (KeyError, TypeError, ValueError):
        # Corrupt or incompatible cache entry — treat as a miss.
        return None


def put(key: str, report: ScanReport) -> None:
    """Store *report* under *key* atomically."""
    payload = json.dumps(report.to_dict(), indent=2)
    directory = cache_dir()
    with _LOCK:
        # Write to a temp file in the same directory, then rename, so a
        # concurrent reader never sees a half-written entry.
        fd, tmp_name = tempfile.mkstemp(dir=directory, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(payload)
            os.replace(tmp_name, directory / f"{key}.json")
        except OSError:
            Path(tmp_name).unlink(missing_ok=True)
            raise


def clear(key: str | None = None) -> int:
    """Delete one entry (or all entries if *key* is None). Returns the count removed."""
    directory = cache_dir()
    removed = 0
    with _LOCK:
        if key is not None:
            path = directory / f"{key}.json"
            if path.exists():
                path.unlink(missing_ok=True)
                removed = 1
            return removed
        for path in directory.glob("*.json"):
            path.unlink(missing_ok=True)
            removed += 1
    return removed
