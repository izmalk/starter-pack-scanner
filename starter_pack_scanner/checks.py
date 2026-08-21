"""Scanner checks: base class, result dataclass, and all check implementations."""

from __future__ import annotations

import abc
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import requests

from starter_pack_scanner import http, site
from starter_pack_scanner.site import SiteContext


# ---------------------------------------------------------------------------
# Color helpers
# ---------------------------------------------------------------------------


def _use_color() -> bool:
    return (
        sys.stdout.isatty()
        and os.environ.get("NO_COLOR") is None
        and os.environ.get("TERM") != "dumb"
    )


_GREEN = "\033[32m"
_RED = "\033[31m"
_BOLD = "\033[1m"
_RESET = "\033[0m"


def _c(text: str, *codes: str) -> str:
    """Wrap text in ANSI codes if the terminal supports color."""
    if not _use_color():
        return text
    return "".join(codes) + text + _RESET


# ---------------------------------------------------------------------------
# Check infrastructure
# ---------------------------------------------------------------------------


@dataclass
class CheckResult:
    """Result of a single check."""

    check_id: str
    check_name: str
    passed: bool
    message: str
    details: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Plain-dict form, JSON-serialisable (used by the cache and web UI)."""
        return {
            "check_id": self.check_id,
            "check_name": self.check_name,
            "passed": self.passed,
            "message": self.message,
            "details": list(self.details),
        }

    @classmethod
    def from_dict(cls, data: dict) -> CheckResult:
        return cls(
            check_id=data["check_id"],
            check_name=data["check_name"],
            passed=data["passed"],
            message=data["message"],
            details=list(data.get("details", [])),
        )

    def __str__(self) -> str:
        if self.passed:
            status = _c("PASS", _GREEN, _BOLD)
        else:
            status = _c("FAIL", _RED, _BOLD)
        lines = [f"[{status}] {self.check_name}: {self.message}"]
        for detail in self.details:
            lines.append(f"       {detail}")
        return "\n".join(lines)


class BaseCheck(abc.ABC):
    """Abstract base class for starter pack checks.

    To create a new check, define a class that inherits from BaseCheck with
    class attributes ``id``, ``name``, ``description`` and implement ``run``.
    Then add the class to ``ALL_CHECKS`` at the bottom of this file.
    """

    id: str
    name: str
    description: str

    # Set to True on checks that need the published-site context; the
    # scanner then builds a SiteContext (network access) before running.
    requires_site: bool = False

    @abc.abstractmethod
    def run(
        self, repo_root: Path, docs_dir: Path | None, site_ctx: SiteContext | None = None
    ) -> CheckResult:
        """Run the check against a cloned repository."""


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_README_NAMES = ["README.md", "README.rst", "README.txt", "README"]


def _find_readme(repo_root: Path) -> Path | None:
    """Return the first README file found at repo root."""
    existing = {p.name.lower(): p for p in repo_root.iterdir() if p.is_file()}
    for name in _README_NAMES:
        found = existing.get(name.lower())
        if found:
            return found
    return None


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


class DocsLocationCheck(BaseCheck):
    id = "docs-dir"
    name = "Docs Directory"
    description = "Checks whether the documentation is in the standard docs/ directory of the repository."

    def run(self, repo_root: Path, docs_dir: Path | None, site_ctx: SiteContext | None = None) -> CheckResult:
        if docs_dir is None:
            return CheckResult(
                check_id=self.id,
                check_name=self.name,
                passed=False,
                message="No starter-pack documentation directory found in the repository.",
            )

        relative = docs_dir.relative_to(repo_root)
        if str(relative) == "docs":
            return CheckResult(
                check_id=self.id,
                check_name=self.name,
                passed=True,
                message="Documentation is in the standard docs/ directory.",
            )

        return CheckResult(
            check_id=self.id,
            check_name=self.name,
            passed=False,
            message=f"Documentation found at {relative}/ instead of the standard docs/ directory.",
        )


class VersionCheck(BaseCheck):
    id = "version"
    name = "Starter Pack Version"
    description = "Checks whether the starter pack version is the latest available."

    _LATEST_VERSION_URL = (
        "https://raw.githubusercontent.com/canonical/sphinx-stack/"
        "main/docs/_dev/version"
    )

    # Possible local paths for the version file (new location first).
    _VERSION_PATHS = ["_dev/version", ".sphinx/version"]

    def _fetch_latest_version(self) -> str | None:
        try:
            resp = requests.get(self._LATEST_VERSION_URL, timeout=10)
            resp.raise_for_status()
            return resp.text.strip()
        except requests.RequestException:
            return None

    def _find_version_file(self, docs_dir: Path) -> Path | None:
        for relative in self._VERSION_PATHS:
            candidate = docs_dir / relative
            if candidate.is_file():
                return candidate
        return None

    def run(self, repo_root: Path, docs_dir: Path | None, site_ctx: SiteContext | None = None) -> CheckResult:
        if docs_dir is None:
            return CheckResult(
                check_id=self.id,
                check_name=self.name,
                passed=False,
                message="No docs directory found; cannot check version.",
            )

        version_file = self._find_version_file(docs_dir)
        if version_file is None:
            return CheckResult(
                check_id=self.id,
                check_name=self.name,
                passed=False,
                message="No version file found — the starter pack may be very old (pre-1.0).",
                details=[f"Looked for: {', '.join(self._VERSION_PATHS)} under {docs_dir.relative_to(repo_root)}/"],
            )

        local_version = version_file.read_text().strip()
        if not local_version:
            return CheckResult(
                check_id=self.id,
                check_name=self.name,
                passed=False,
                message=f"The version file ({version_file.relative_to(repo_root)}) is empty.",
            )

        latest_version = self._fetch_latest_version()
        if latest_version is None:
            return CheckResult(
                check_id=self.id,
                check_name=self.name,
                passed=True,
                message=f"Local version is {local_version} (could not fetch latest version to compare).",
            )

        if local_version == latest_version:
            return CheckResult(
                check_id=self.id,
                check_name=self.name,
                passed=True,
                message=f"Starter pack is up to date (version {local_version}).",
            )

        return CheckResult(
            check_id=self.id,
            check_name=self.name,
            passed=False,
            message=f"Starter pack version {local_version} is outdated (latest: {latest_version}).",
        )


class ReadmeDocsLinkCheck(BaseCheck):
    id = "readme-docs-link"
    name = "README Docs Link"
    description = "Checks whether the repository README contains a link to the documentation."

    _DOCS_URL_PATTERNS = [
        re.compile(r"https?://[^\s\)\"'>]+\.readthedocs\.io\b", re.IGNORECASE),
        re.compile(r"https?://[^\s\)\"'>]+readthedocs-hosted\.com\b", re.IGNORECASE),
        re.compile(r"https?://[^\s\)\"'>]+/docs?\b", re.IGNORECASE),
        re.compile(r"https?://docs\.[^\s\)\"'>]+", re.IGNORECASE),
    ]

    def run(self, repo_root: Path, docs_dir: Path | None, site_ctx: SiteContext | None = None) -> CheckResult:
        readme = _find_readme(repo_root)
        if readme is None:
            return CheckResult(
                check_id=self.id,
                check_name=self.name,
                passed=False,
                message="No README file found in the repository root.",
            )

        try:
            content = readme.read_text(errors="replace")
        except OSError:
            return CheckResult(
                check_id=self.id,
                check_name=self.name,
                passed=False,
                message=f"Could not read {readme.name}.",
            )

        found_urls: list[str] = []
        for pattern in self._DOCS_URL_PATTERNS:
            found_urls.extend(pattern.findall(content))

        if found_urls:
            seen: set[str] = set()
            unique: list[str] = []
            for u in found_urls:
                if u not in seen:
                    seen.add(u)
                    unique.append(u)
            return CheckResult(
                check_id=self.id,
                check_name=self.name,
                passed=True,
                message=f"Found {len(unique)} documentation link(s) in {readme.name}.",
                details=[u for u in unique[:5]],
            )

        return CheckResult(
            check_id=self.id,
            check_name=self.name,
            passed=False,
            message=f"No documentation links found in {readme.name}.",
        )


class ReadmeRtdBadgeCheck(BaseCheck):
    id = "readme-rtd-badge"
    name = "README RTD Badge"
    description = "Checks whether the repository README contains a Read the Docs badge."

    _RTD_BADGE_PATTERNS = [
        re.compile(r"readthedocs\.org/projects/[^/]+/badge", re.IGNORECASE),
        re.compile(r"img\.shields\.io/readthedocs/", re.IGNORECASE),
        re.compile(r"badge.*readthedocs|readthedocs.*badge", re.IGNORECASE),
    ]

    def run(self, repo_root: Path, docs_dir: Path | None, site_ctx: SiteContext | None = None) -> CheckResult:
        readme = _find_readme(repo_root)
        if readme is None:
            return CheckResult(
                check_id=self.id,
                check_name=self.name,
                passed=False,
                message="No README file found in the repository root.",
            )

        try:
            content = readme.read_text(errors="replace")
        except OSError:
            return CheckResult(
                check_id=self.id,
                check_name=self.name,
                passed=False,
                message=f"Could not read {readme.name}.",
            )

        for pattern in self._RTD_BADGE_PATTERNS:
            if pattern.search(content):
                return CheckResult(
                    check_id=self.id,
                    check_name=self.name,
                    passed=True,
                    message=f"Read the Docs badge found in {readme.name}.",
                )

        return CheckResult(
            check_id=self.id,
            check_name=self.name,
            passed=False,
            message=f"No Read the Docs badge found in {readme.name}.",
        )


# ---------------------------------------------------------------------------
# SEO / AIO checks (live-site)
# ---------------------------------------------------------------------------


def _site_unavailable_result(check: BaseCheck, site_ctx: SiteContext | None) -> CheckResult:
    """Standard failure result when the published-site context is missing."""
    if site_ctx is None or not site_ctx.available:
        details = list(site_ctx.errors) if site_ctx else []
        return CheckResult(
            check_id=check.id,
            check_name=check.name,
            passed=False,
            message="Could not resolve the published documentation URL; cannot run this check.",
            details=details or ["Pass --docs-url to specify the published documentation base URL."],
        )
    raise AssertionError("site context is available")  # pragma: no cover


def _no_pages_result(check: BaseCheck, site_ctx: SiteContext) -> CheckResult:
    return CheckResult(
        check_id=check.id,
        check_name=check.name,
        passed=False,
        message="No documentation pages could be sampled (llms.txt and sitemap.xml unavailable or empty).",
        details=site_ctx.errors,
    )


class LlmsTxtCheck(BaseCheck):
    id = "llms-txt"
    name = "llms.txt Available"
    description = "Checks that the published documentation serves an llms.txt index for AI agents."
    requires_site = True

    def run(self, repo_root: Path, docs_dir: Path | None, site_ctx: SiteContext | None = None) -> CheckResult:
        if site_ctx is None or not site_ctx.available:
            return _site_unavailable_result(self, site_ctx)

        if site_ctx.llms_txt_text is None:
            status = next(
                (e for e in site_ctx.errors if "llms.txt" in e),
                f"fetched from {site_ctx.llms_txt_url}",
            )
            return CheckResult(
                check_id=self.id,
                check_name=self.name,
                passed=False,
                message=f"llms.txt is not available at {site_ctx.llms_txt_url}.",
                details=[status],
            )

        links = site.parse_llms_txt(site_ctx.llms_txt_text)
        if not links:
            return CheckResult(
                check_id=self.id,
                check_name=self.name,
                passed=False,
                message=f"llms.txt at {site_ctx.llms_txt_url} contains no links.",
            )

        return CheckResult(
            check_id=self.id,
            check_name=self.name,
            passed=True,
            message=f"llms.txt is available and lists {len(links)} link(s).",
            details=[site_ctx.llms_txt_url],
        )


class LlmsTxtLinksCheck(BaseCheck):
    id = "llms-txt-links"
    name = "llms.txt Links"
    description = "Checks that a sample of links from llms.txt resolves to live pages."
    requires_site = True

    def run(self, repo_root: Path, docs_dir: Path | None, site_ctx: SiteContext | None = None) -> CheckResult:
        if site_ctx is None or not site_ctx.available:
            return _site_unavailable_result(self, site_ctx)
        if not site_ctx.pages:
            return _no_pages_result(self, site_ctx)

        details: list[str] = []
        broken = 0
        for url in site_ctx.pages:
            resp, error = http.get(url)
            if resp is not None and resp.status_code < 400:
                details.append(f"OK ({resp.status_code}): {url}")
            else:
                broken += 1
                status = f"HTTP {resp.status_code}" if resp is not None else error
                details.append(f"BROKEN ({status}): {url}")

        if broken:
            return CheckResult(
                check_id=self.id,
                check_name=self.name,
                passed=False,
                message=f"{broken} of {len(site_ctx.pages)} sampled llms.txt links are broken.",
                details=details,
            )
        return CheckResult(
            check_id=self.id,
            check_name=self.name,
            passed=True,
            message=f"All {len(site_ctx.pages)} sampled llms.txt links resolve.",
            details=details,
        )


class LlmsFullTxtCheck(BaseCheck):
    id = "llms-full-txt"
    name = "llms-full.txt Link"
    description = "Checks that llms.txt links to llms-full.txt and that the link is not broken."
    requires_site = True

    _FULL_RE = re.compile(r"\[[^\]]*\]\((\S*llms-full\.txt)\)")

    def run(self, repo_root: Path, docs_dir: Path | None, site_ctx: SiteContext | None = None) -> CheckResult:
        if site_ctx is None or not site_ctx.available:
            return _site_unavailable_result(self, site_ctx)
        if site_ctx.llms_txt_text is None:
            return CheckResult(
                check_id=self.id,
                check_name=self.name,
                passed=False,
                message="llms.txt is not available; cannot check for an llms-full.txt link.",
                details=site_ctx.errors,
            )

        match = self._FULL_RE.search(site_ctx.llms_txt_text)
        if not match:
            return CheckResult(
                check_id=self.id,
                check_name=self.name,
                passed=False,
                message="llms.txt does not contain a link to llms-full.txt.",
                details=[site_ctx.llms_txt_url],
            )

        full_url = match.group(1)
        resp, error = http.get(full_url)
        if resp is None or resp.status_code >= 400:
            status = f"HTTP {resp.status_code}" if resp is not None else error
            return CheckResult(
                check_id=self.id,
                check_name=self.name,
                passed=False,
                message=f"The llms-full.txt link in llms.txt is broken ({status}).",
                details=[full_url],
            )
        if not resp.text.strip():
            return CheckResult(
                check_id=self.id,
                check_name=self.name,
                passed=False,
                message="llms-full.txt is reachable but empty.",
                details=[full_url],
            )
        return CheckResult(
            check_id=self.id,
            check_name=self.name,
            passed=True,
            message="llms.txt links to llms-full.txt and the link resolves.",
            details=[full_url],
        )


class PageMetadataCheck(BaseCheck):
    id = "page-metadata"
    name = "Page Metadata"
    description = "Checks that sampled pages have a non-empty meta description."
    requires_site = True

    _META_DESC_RE = re.compile(
        r"<meta[^>]+name=[\"']description[\"'][^>]+content=[\"']([^\"']*)[\"']", re.IGNORECASE
    )
    _META_DESC_RE2 = re.compile(
        r"<meta[^>]+content=[\"']([^\"']*)[\"'][^>]+name=[\"']description[\"']", re.IGNORECASE
    )

    def run(self, repo_root: Path, docs_dir: Path | None, site_ctx: SiteContext | None = None) -> CheckResult:
        if site_ctx is None or not site_ctx.available:
            return _site_unavailable_result(self, site_ctx)
        if not site_ctx.pages:
            return _no_pages_result(self, site_ctx)

        details: list[str] = []
        missing = 0
        for url in site_ctx.pages:
            page_url = site.to_page_url(url)
            resp, error = http.get(page_url)
            if resp is None or resp.status_code >= 400:
                missing += 1
                status = f"HTTP {resp.status_code}" if resp is not None else error
                details.append(f"UNREACHABLE ({status}): {page_url}")
                continue
            match = self._META_DESC_RE.search(resp.text) or self._META_DESC_RE2.search(resp.text)
            if match and match.group(1).strip():
                details.append(f"OK: {page_url}")
            else:
                missing += 1
                details.append(f"MISSING meta description: {page_url}")

        if missing:
            return CheckResult(
                check_id=self.id,
                check_name=self.name,
                passed=False,
                message=f"{missing} of {len(site_ctx.pages)} sampled pages lack a meta description.",
                details=details,
            )
        return CheckResult(
            check_id=self.id,
            check_name=self.name,
            passed=True,
            message=f"All {len(site_ctx.pages)} sampled pages have a meta description.",
            details=details,
        )


class DocsDomainCheck(BaseCheck):
    id = "docs-domain"
    name = "Major Documentation Domain"
    description = "Checks that the documentation is published on a major company domain (e.g. canonical.com, ubuntu.com)."
    requires_site = True

    def __init__(self, extra_domains: set[str] | None = None):
        self.extra_domains = extra_domains or set()

    def run(self, repo_root: Path, docs_dir: Path | None, site_ctx: SiteContext | None = None) -> CheckResult:
        if site_ctx is None or not site_ctx.available:
            return _site_unavailable_result(self, site_ctx)

        if site.is_major_domain(site_ctx.base_url, self.extra_domains):
            return CheckResult(
                check_id=self.id,
                check_name=self.name,
                passed=True,
                message=f"Documentation is published on a major domain: {site_ctx.base_url}",
            )
        return CheckResult(
            check_id=self.id,
            check_name=self.name,
            passed=False,
            message=f"Documentation is not published on a major company domain: {site_ctx.base_url}",
            details=[
                "Major domains: " + ", ".join(sorted(site.MAJOR_DOMAINS | self.extra_domains)),
                "Extend the list with --allow-domain.",
            ],
        )


class PageMarkdownCheck(BaseCheck):
    id = "page-markdown"
    name = "Markdown for AI"
    description = "Checks that sampled pages serve a Markdown version for AI (page URL + index.html.md)."
    requires_site = True

    def run(self, repo_root: Path, docs_dir: Path | None, site_ctx: SiteContext | None = None) -> CheckResult:
        if site_ctx is None or not site_ctx.available:
            return _site_unavailable_result(self, site_ctx)
        if not site_ctx.pages:
            return _no_pages_result(self, site_ctx)

        details: list[str] = []
        missing = 0
        for url in site_ctx.pages:
            md_url = site.to_markdown_url(site.to_page_url(url))
            resp, error = http.get(md_url)
            if resp is None or resp.status_code >= 400:
                missing += 1
                status = f"HTTP {resp.status_code}" if resp is not None else error
                details.append(f"NO MARKDOWN ({status}): {md_url}")
                continue
            body = resp.text.lstrip().lower()
            if body.startswith("<!doctype") or body.startswith("<html"):
                missing += 1
                details.append(f"NOT MARKDOWN (HTML served): {md_url}")
            else:
                details.append(f"OK: {md_url}")

        if missing:
            return CheckResult(
                check_id=self.id,
                check_name=self.name,
                passed=False,
                message=f"{missing} of {len(site_ctx.pages)} sampled pages have no Markdown version.",
                details=details,
            )
        return CheckResult(
            check_id=self.id,
            check_name=self.name,
            passed=True,
            message=f"All {len(site_ctx.pages)} sampled pages serve a Markdown version.",
            details=details,
        )


class PageAgentDirectiveCheck(BaseCheck):
    id = "page-agent-directive"
    name = "Hidden AI Directive"
    description = "Checks that sampled pages contain a visually-hidden AI discovery directive (llms.txt pointer)."
    requires_site = True

    # Explicit markers used by the Canonical AIO setup.
    _MARKERS = ("data-agent-directive", "u-hide-agent-directive")
    # Generic visually-hidden CSS signals.
    _HIDDEN_SIGNALS = (
        "clip-path: inset(50%)",
        "clip: rect(0 0 0 0)",
        "sr-only",
        "visually-hidden",
        "screen-reader",
    )

    def run(self, repo_root: Path, docs_dir: Path | None, site_ctx: SiteContext | None = None) -> CheckResult:
        if site_ctx is None or not site_ctx.available:
            return _site_unavailable_result(self, site_ctx)
        if not site_ctx.pages:
            return _no_pages_result(self, site_ctx)

        details: list[str] = []
        missing = 0
        for url in site_ctx.pages:
            page_url = site.to_page_url(url)
            resp, error = http.get(page_url)
            if resp is None or resp.status_code >= 400:
                missing += 1
                status = f"HTTP {resp.status_code}" if resp is not None else error
                details.append(f"UNREACHABLE ({status}): {page_url}")
                continue
            html_text = resp.text
            signal = next((m for m in self._MARKERS if m in html_text), None)
            if signal is None:
                # Fallback: an element mentioning llms.txt that also carries a
                # visually-hidden CSS signal nearby.
                if "llms.txt" in html_text and any(s in html_text for s in self._HIDDEN_SIGNALS):
                    signal = "llms.txt reference + visually-hidden CSS"
            if signal:
                details.append(f"OK ({signal}): {page_url}")
            else:
                missing += 1
                details.append(f"NO AI DIRECTIVE: {page_url}")

        if missing:
            return CheckResult(
                check_id=self.id,
                check_name=self.name,
                passed=False,
                message=f"{missing} of {len(site_ctx.pages)} sampled pages lack a hidden AI directive.",
                details=details,
            )
        return CheckResult(
            check_id=self.id,
            check_name=self.name,
            passed=True,
            message=f"All {len(site_ctx.pages)} sampled pages contain a hidden AI directive.",
            details=details,
        )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

ALL_CHECKS = [
    DocsLocationCheck,
    VersionCheck,
    ReadmeDocsLinkCheck,
    ReadmeRtdBadgeCheck,
    LlmsTxtCheck,
    LlmsTxtLinksCheck,
    LlmsFullTxtCheck,
    PageMetadataCheck,
    DocsDomainCheck,
    PageMarkdownCheck,
    PageAgentDirectiveCheck,
]
