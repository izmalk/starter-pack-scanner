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
from starter_pack_scanner.base import BaseCheck, CheckResult
from starter_pack_scanner.migration_checks import (
    AnalyticsCheck,
    BaseUrlCheck,
    CanonicalUrlCheck,
    FlyoutPdfCheck,
    FlyoutVersionsCheck,
    NotFoundCheck,
    OldUrlRedirectCheck,
    OverwriteLinksCheck,
    RtdLeakageCheck,
    SitemapConfigCheck,
    SitemapIndexCheck,
    SitemapLiveCheck,
    SlugCheck,
    StaticPathCheck,
    UrlShapeCheck,
)
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
    recommendation = (
        "Move the documentation into a top-level `docs/` directory — the Sphinx Stack "
        "convention that tooling and CI workflows assume. Update `.readthedocs.yaml` "
        "(`sphinx.configuration`) to point at the new `docs/conf.py` path."
    )

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
    recommendation = (
        "Update the Sphinx Stack: run `make update` from the `docs/` directory (or "
        "`python _dev/update_sp.py`), then commit the refreshed `_dev/` files. "
        "See https://github.com/canonical/sphinx-stack for the changelog."
    )

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
    description = "Checks whether the repository README contains a link to the product's documentation."
    recommendation = (
        "Add a link to the published documentation in the repository README, e.g. "
        "`Documentation: https://canonical.com/<product>/docs/`. Use the URL from "
        "`html_baseurl` in `conf.py` so the link matches the live site."
    )

    _URL_RE = re.compile(r"https?://[^\s\)\"'>]+", re.IGNORECASE)

    # Fallback patterns (used only when the product's docs URL is unknown):
    # links that look like documentation hosting.
    _GENERIC_DOCS_PATTERNS = [
        re.compile(r"https?://[^\s\)\"'>]+\.readthedocs\.io\b", re.IGNORECASE),
        re.compile(r"https?://[^\s\)\"'>]+readthedocs-hosted\.com\b", re.IGNORECASE),
        re.compile(r"https?://[^\s\)\"'>]+/docs?\b", re.IGNORECASE),
        re.compile(r"https?://docs\.[^\s\)\"'>]+", re.IGNORECASE),
    ]

    @staticmethod
    def _expected_docs_urls(docs_dir: Path | None, site_ctx: SiteContext | None) -> list[str]:
        """Collect the product's own docs URLs: the resolved live-site base
        URL (includes any --docs-url override) and the conf.py values."""
        expected: list[str] = []
        if site_ctx is not None and site_ctx.base_url:
            expected.append(site_ctx.base_url)
        if docs_dir is not None:
            conf = docs_dir / "conf.py"
            if conf.is_file():
                conf_text = conf.read_text(errors="replace")
                for key in ("html_baseurl", "ogp_site_url"):
                    value = site._conf_value(conf_text, key)
                    if value:
                        expected.append(value)
        return expected

    @staticmethod
    def _match_prefix(url: str, expected: str) -> bool:
        """True when *url* points at (or inside) the *expected* docs URL,
        ignoring an RTD-style version segment."""
        prefix = site._unversioned_prefix(expected) or expected
        url = url.rstrip("/")
        prefix = prefix.rstrip("/")
        return url == prefix or url.startswith(prefix + "/")

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

        # Deduplicate all URLs found in the README, preserving order.
        seen: set[str] = set()
        urls: list[str] = []
        for u in self._URL_RE.findall(content):
            if u not in seen:
                seen.add(u)
                urls.append(u)

        expected = self._expected_docs_urls(docs_dir, site_ctx)
        if expected:
            matching = [
                u for u in urls
                if any(self._match_prefix(u, e) for e in expected)
            ]
            if matching:
                return CheckResult(
                    check_id=self.id,
                    check_name=self.name,
                    passed=True,
                    message=f"Found {len(matching)} link(s) to the product documentation in {readme.name}.",
                    details=matching[:5],
                )
            return CheckResult(
                check_id=self.id,
                check_name=self.name,
                passed=False,
                message=f"No link to the product documentation found in {readme.name}.",
                details=[f"Expected a link to: {e}" for e in expected[:3]],
            )

        # Fallback: the product's docs URL is unknown — accept generic
        # documentation-looking links.
        generic = [u for u in urls if any(p.match(u) for p in self._GENERIC_DOCS_PATTERNS)]
        if generic:
            return CheckResult(
                check_id=self.id,
                check_name=self.name,
                passed=True,
                message=f"Found {len(generic)} documentation link(s) in {readme.name}.",
                details=generic[:5],
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
    recommendation = (
        "Add a build-status badge to the README, e.g. "
        "`[![Docs](https://readthedocs.org/projects/<project>/badge/?version=latest)]` "
        "linked to the documentation URL."
    )

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
    recommendation = (
        "Add `sphinx_llm.txt` to `extensions` in `conf.py` so the build emits `llms.txt` "
        "at the docs root. Set `llms_txt_description` for the intro block. "
        "See https://github.com/canonical/sphinx-llm"
    )
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
    recommendation = (
        "llms.txt links must match the published URL structure. On versioned docs, "
        "build `html_baseurl` with the version segment "
        "(f-string over READTHEDOCS_VERSION, e.g. "
        "https://canonical.com/<slug>/<version>/), "
        "including the trailing slash — otherwise every emitted link 404s."
    )
    requires_site = True

    def run(self, repo_root: Path, docs_dir: Path | None, site_ctx: SiteContext | None = None) -> CheckResult:
        if site_ctx is None or not site_ctx.available:
            return _site_unavailable_result(self, site_ctx)
        if not site_ctx.pages:
            return _no_pages_result(self, site_ctx)

        # Probe the links exactly as published in llms.txt / sitemap.xml —
        # NOT the version-rewritten URLs. On versioned docs sites whose
        # llms.txt lists unversioned links, the published links 404 even
        # though the rewritten pages resolve; that is a real defect this
        # check must report.
        if site_ctx.raw_pages:
            pairs = list(zip(site_ctx.raw_pages, site_ctx.pages))
        else:
            # Manually-built context without raw_pages: probe as-is.
            pairs = [(u, u) for u in site_ctx.pages]

        details: list[str] = []
        broken = 0
        # Broken links whose rewritten (versioned) counterpart resolves —
        # direct evidence that the published link lacks the version segment.
        version_evidence = 0
        for raw, fixed in pairs:
            resp, error = http.get(raw)
            if resp is not None and resp.status_code < 400:
                details.append(f"OK ({resp.status_code}): {raw}")
                continue
            broken += 1
            status = f"HTTP {resp.status_code}" if resp is not None else error
            line = f"BROKEN ({status}): {raw}"
            if fixed != raw:
                # The link was unversioned on a versioned site. Confirm the
                # page actually exists at the versioned URL before blaming
                # the missing version segment — otherwise the page may just
                # be gone, and the note would misattribute the failure.
                resp2, _error2 = http.get(fixed)
                if resp2 is not None and resp2.status_code < 400:
                    version_evidence += 1
                    line += f" — but resolves at {fixed} (published link lacks the version segment)"
            details.append(line)

        if broken:
            # Only claim the version-segment cause when at least one broken
            # link was proven to exist at its versioned URL.
            if version_evidence:
                details.append(
                    "Note: the docs site is versioned and the sampled llms.txt/sitemap.xml "
                    "links lack the version segment, so they 404 as published. Build "
                    "html_baseurl with the version segment (READTHEDOCS_VERSION) so the "
                    "emitted links include it."
                )
            return CheckResult(
                check_id=self.id,
                check_name=self.name,
                passed=False,
                message=f"{broken} of {len(pairs)} sampled llms.txt links are broken.",
                details=details,
            )
        return CheckResult(
            check_id=self.id,
            check_name=self.name,
            passed=True,
            message=f"All {len(pairs)} sampled llms.txt links resolve.",
            details=details,
        )


class LlmsFullTxtCheck(BaseCheck):
    id = "llms-full-txt"
    name = "llms-full.txt Link"
    description = "Checks that llms.txt links to llms-full.txt and that the link is not broken."
    recommendation = (
        "`sphinx_llm.txt` generates `llms-full.txt` alongside `llms.txt`; the link "
        "breaks when `html_baseurl` lacks the version segment or trailing slash. "
        "Fix `html_baseurl` in `conf.py` and rebuild — both files are emitted together."
    )
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
    recommendation = (
        "Add a description to each page via MyST front matter "
        "(myst.html_meta.description in the page's YAML front matter). "
        "Keep it under ~160 chars; it feeds search snippets and the "
        "og:description preview."
    )
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
    recommendation = (
        "Publish on a Canonical domain (canonical.com, ubuntu.com, juju.is, ...) "
        "following the RTD-Proxy migration guide: "
        "https://documentation.ubuntu.com/rtd-proxy/how-to/migrate/ "
        "If the domain is correct but new, extend the allow-list with `--allow-domain`."
    )
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
    recommendation = (
        "Add `sphinx_llm.txt` to `extensions` in `conf.py` — it pulls in "
        "`sphinx-markdown-builder`, which emits `<page>/index.html.md` for every "
        "page. Verify the files exist in the build output (`_build/`) after a rebuild."
    )
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
    recommendation = (
        "Add a visually-hidden `<div data-agent-directive>` pointing at `llms.txt` "
        "to `_templates/header.html`, hidden via the clip-rect technique in CSS "
        "(not `display: none`, which risks being treated as cloaked content). "
        "See the Agent-Friendly Docs spec: https://agentdocsspec.com/spec/"
    )
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
    # URL-migration validation group (RTD -> Canonical domains)
    SlugCheck,
    BaseUrlCheck,
    SitemapConfigCheck,
    OverwriteLinksCheck,
    StaticPathCheck,
    SitemapLiveCheck,
    CanonicalUrlCheck,
    NotFoundCheck,
    AnalyticsCheck,
    FlyoutPdfCheck,
    FlyoutVersionsCheck,
    OldUrlRedirectCheck,
    SitemapIndexCheck,
    UrlShapeCheck,
    RtdLeakageCheck,
]


def checks_by_group(group: str) -> list[type[BaseCheck]]:
    """Return all check classes belonging to *group*."""
    return [cls for cls in ALL_CHECKS if getattr(cls, "group", None) == group]
