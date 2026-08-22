"""Core scanner logic: clone repo, detect docs, run checks."""

from __future__ import annotations

import ipaddress
import shutil
import socket
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from starter_pack_scanner.checks import ALL_CHECKS, BaseCheck, CheckResult, DocsDomainCheck
from starter_pack_scanner.migration_checks import OldUrlRedirectCheck
from starter_pack_scanner.site import SiteContext, build_site_context

# Hard cap on a single git clone, so a hanging remote cannot wedge a scan.
_CLONE_TIMEOUT = 120  # seconds

# Directories to search for starter-pack indicators, in priority order.
_CANDIDATE_DIRS = ["docs", "."]

# Signals that a directory is a starter-pack docs root (checked in order).
# .sphinx/ is the strongest signal; conf.py alone is generic Sphinx.
_SP_MARKERS = [".sphinx"]
_SPHINX_MARKERS = ["conf.py"]

# Repo-root file that hints at RTD-based docs even when docs dir is elsewhere.
_RTD_CONFIG = ".readthedocs.yaml"


# ---------------------------------------------------------------------------
# Scan report
# ---------------------------------------------------------------------------


@dataclass
class ScanReport:
    """Complete outcome of one scan, ready for display or caching.

    ``error`` is set (and ``results`` empty) when the scan could not run at
    all — e.g. an invalid repository URL or a failed clone. Individual check
    failures are *not* errors: they are recorded as failed CheckResults.
    """

    repo_url: str
    branch: str | None = None
    docs_url: str | None = None
    scanned_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    docs_dir: str | None = None
    results: list[CheckResult] = field(default_factory=list)
    error: str | None = None

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if not r.passed)

    def to_dict(self) -> dict:
        """Plain-dict form, JSON-serialisable (used by the cache and web UI)."""
        return {
            "repo_url": self.repo_url,
            "branch": self.branch,
            "docs_url": self.docs_url,
            "scanned_at": self.scanned_at.isoformat(),
            "docs_dir": self.docs_dir,
            "results": [r.to_dict() for r in self.results],
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ScanReport:
        return cls(
            repo_url=data["repo_url"],
            branch=data.get("branch"),
            docs_url=data.get("docs_url"),
            scanned_at=datetime.fromisoformat(data["scanned_at"]),
            docs_dir=data.get("docs_dir"),
            results=[CheckResult.from_dict(r) for r in data.get("results", [])],
            error=data.get("error"),
        )


# ---------------------------------------------------------------------------
# URL validation (basic SSRF guard for the web UI)
# ---------------------------------------------------------------------------


def _is_local_host(hostname: str) -> bool:
    """True for hostnames that refer to the local machine."""
    return hostname in {"localhost", "localhost.localdomain"} or (
        hostname.endswith(".localhost") if hostname.count(".") else False
    )


def _resolve_all_ips(hostname: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Resolve *hostname* to all its IP addresses (may be empty on failure)."""
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return []
    return [ipaddress.ip_address(info[4][0]) for info in infos]


def _is_safe_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """False for loopback, private, link-local and other special-purpose IPs."""
    return not (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def validate_repo_url(url: str) -> str | None:
    """Validate a user-supplied repository URL.

    Returns an error message for unsafe/invalid URLs, or None if the URL is
    acceptable. Rules:

    - Scheme must be https (http is allowed for localhost only).
    - No embedded credentials (``user:pass@host``).
    - The hostname must not resolve to a private/loopback/link-local address
      (basic SSRF protection for the web UI).
    """
    parsed = urlparse(url)

    if parsed.scheme not in {"https", "http"}:
        return f"Unsupported URL scheme {parsed.scheme!r} — use an https:// repository URL."
    if not parsed.hostname:
        return "The URL does not contain a hostname."
    if parsed.username or parsed.password:
        return "URLs with embedded credentials are not allowed."

    if parsed.scheme == "http" and not _is_local_host(parsed.hostname):
        return "http:// URLs are only allowed for localhost."

    if not _is_local_host(parsed.hostname):
        for ip in _resolve_all_ips(parsed.hostname):
            if not _is_safe_ip(ip):
                return (
                    f"The hostname {parsed.hostname!r} resolves to a private or "
                    "reserved address, which is not allowed."
                )

    return None


def _is_starter_pack_dir(path: Path) -> bool:
    """Return True if *path* looks like a starter-pack docs root."""
    return any((path / m).exists() for m in _SP_MARKERS)


def _is_sphinx_dir(path: Path) -> bool:
    """Return True if *path* contains a Sphinx conf.py."""
    return (path / "conf.py").is_file()


def _find_docs_dir(repo_root: Path) -> Path | None:
    """Locate the starter-pack docs directory inside a cloned repo.

    Detection strategy (in priority order):
    1. Check ``docs/`` and repo root for a ``.sphinx/`` directory.
    2. Search one level deep for any dir containing ``.sphinx/``.
    3. If a ``.readthedocs.yaml`` exists at the repo root, parse it for
       a custom ``sphinx.configuration`` path pointing to conf.py, and
       derive the docs directory from that.
    4. Fall back to ``docs/`` or repo root if they contain ``conf.py``.
    5. Search one level deep for any dir containing ``conf.py``.
    """
    # --- pass 1: strong signal (.sphinx/) in priority dirs ---
    for candidate in _CANDIDATE_DIRS:
        path = repo_root / candidate
        if _is_starter_pack_dir(path):
            return path

    # --- pass 2: strong signal one level deep ---
    for child in sorted(repo_root.iterdir()):
        if child.is_dir() and not child.name.startswith(".") and _is_starter_pack_dir(child):
            return child

    # --- pass 3: .readthedocs.yaml may point to the docs dir ---
    rtd_path = repo_root / _RTD_CONFIG
    if not rtd_path.exists():
        # Also check the legacy filename without leading dot
        rtd_path = repo_root / "readthedocs.yaml"
    if rtd_path.exists():
        docs_dir = _docs_dir_from_rtd_config(repo_root, rtd_path)
        if docs_dir is not None:
            return docs_dir

    # --- pass 4: weaker signal (conf.py) in priority dirs ---
    for candidate in _CANDIDATE_DIRS:
        path = repo_root / candidate
        if _is_sphinx_dir(path):
            return path

    # --- pass 5: weaker signal one level deep ---
    for child in sorted(repo_root.iterdir()):
        if child.is_dir() and not child.name.startswith(".") and _is_sphinx_dir(child):
            return child

    return None


def _docs_dir_from_rtd_config(repo_root: Path, rtd_path: Path) -> Path | None:
    """Try to extract the docs directory from a .readthedocs.yaml file."""
    try:
        text = rtd_path.read_text()
    except OSError:
        return None

    # Lightweight YAML parsing — look for sphinx.configuration value
    # to avoid adding a PyYAML dependency.
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("configuration:"):
            value = stripped.split(":", 1)[1].strip().strip("\"'")
            if value:
                conf_path = repo_root / value
                if conf_path.exists():
                    return conf_path.parent
                # Even if the file doesn't exist, the parent dir may
                candidate = conf_path.parent
                if candidate.is_dir():
                    return candidate
    return None


def clone_repo(repo_url: str, dest: Path, branch: str | None = None) -> None:
    """Shallow-clone a repository."""
    cmd = ["git", "clone", "--depth", "1"]
    if branch:
        cmd += ["--branch", branch]
    cmd += ["--", repo_url, str(dest)]
    subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=_CLONE_TIMEOUT)


def scan(
    repo_url: str,
    branch: str | None = None,
    exclude_checks: set[str] | None = None,
    include_checks: set[str] | None = None,
    docs_url: str | None = None,
    seed: int | None = None,
    allow_domains: set[str] | None = None,
    offline: bool = False,
    check_group: str | None = None,
    old_url: str | None = None,
) -> ScanReport:
    """Clone a repo and run all enabled checks.

    Args:
        repo_url: Git-cloneable repository URL.
        branch: Optional branch/tag to check out.
        exclude_checks: Set of check IDs to skip.
        include_checks: If set, only run checks whose IDs are in this set.
        docs_url: Override for the published docs base URL (auto-detected
            from conf.py otherwise).
        seed: Seed for the random page sampling (reproducible runs).
        allow_domains: Extra domains accepted by the docs-domain check.
        offline: Skip all checks that require network access to the
            published documentation site.
        check_group: If set, only run checks in this group (e.g. "migration").
        old_url: Pre-migration documentation URL, used by
            migration-old-url-redirect (auto-derived from conf.py git
            history when not given).

    Returns:
        A ScanReport. If the repository could not be cloned, ``report.error``
        is set and ``results`` is empty; scan errors never raise.
    """
    report = ScanReport(repo_url=repo_url, branch=branch, docs_url=docs_url)

    url_error = validate_repo_url(repo_url)
    if url_error:
        report.error = url_error
        return report

    exclude_checks = exclude_checks or set()
    tmp_dir = tempfile.mkdtemp(prefix="sp-scanner-")
    repo_root = Path(tmp_dir) / "repo"

    try:
        try:
            clone_repo(repo_url, repo_root, branch)
        except subprocess.TimeoutExpired:
            report.error = f"git clone timed out after {_CLONE_TIMEOUT} seconds."
            return report
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").strip()
            hint = f": {stderr.splitlines()[-1]}" if stderr else ""
            report.error = f"git clone failed{hint}"
            return report
        except FileNotFoundError:
            report.error = "git executable not found — is git installed and on PATH?"
            return report

        docs_dir = _find_docs_dir(repo_root)
        report.docs_dir = str(docs_dir.relative_to(repo_root)) if docs_dir else None

        # Determine which checks will run, so the site context is only
        # built (network access) when at least one site check is enabled.
        enabled: list[type[BaseCheck]] = []
        for check_cls in ALL_CHECKS:
            check = check_cls()
            if check.id in exclude_checks:
                continue
            if include_checks and check.id not in include_checks:
                continue
            if check_group and getattr(check, "group", None) != check_group:
                continue
            if offline and getattr(check, "requires_site", False):
                continue
            enabled.append(check_cls)

        site_ctx: SiteContext | None = None
        if any(getattr(cls, "requires_site", False) for cls in enabled):
            site_ctx = build_site_context(docs_dir, docs_url_override=docs_url, seed=seed)

        results: list[CheckResult] = []
        for check_cls in enabled:
            if check_cls is DocsDomainCheck:
                check: BaseCheck = check_cls(allow_domains)
            elif check_cls is OldUrlRedirectCheck:
                check = check_cls(old_url)
            else:
                check = check_cls()
            results.append(check.run(repo_root, docs_dir, site_ctx))

        report.results = results
        return report
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
