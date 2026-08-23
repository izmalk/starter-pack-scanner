"""URL-migration validation checks.

These checks verify that a documentation set has completed the migration
from Read the Docs hosting to Canonical domains (canonical.com / ubuntu.com),
following the RTD-Proxy migration guide:
https://documentation.ubuntu.com/rtd-proxy/how-to/migrate/

Two kinds of checks:

- **Repository checks** inspect the cloned repository (conf.py settings).
- **Live-site checks** inspect the published documentation (requires the
  site context; skipped in offline mode).
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from starter_pack_scanner import http, site
from starter_pack_scanner.base import BaseCheck, CheckResult, no_pages, site_unavailable
from starter_pack_scanner.site import SiteContext

# Migration check group identifier (used by CLI/GUI to select the group).
MIGRATION_GROUP = "migration"

# URL path prefixes with content-cache exceptions; see
# docs/how-to/migrate.rst in canonical/RTD-Proxy.
_CACHE_EXCEPTIONS = (
    "canonical.com/dqlite", "canonical.com/microk8s", "canonical.com/microstack",
    "ubuntu.com/community", "ubuntu.com/ceph", "ubuntu.com/openstack",
    "ubuntu.com/security", "ubuntu.com/kubernetes", "ubuntu.com/certification",
    "ubuntu.com/charmed-k8s", "ubuntu.com/robotics", "ubuntu.com/api",
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _conf_assignment(conf_text: str, key: str) -> str | None:
    """Extract a simple string assignment from conf.py text."""
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=\s*[rf]*(['\"])(.*?)\1\s*$", re.MULTILINE)
    match = pattern.search(conf_text)
    return match.group(2) if match else None


def _conf_list_contains(conf_text: str, key: str, needle: str) -> bool | None:
    """Check whether a list assignment in conf.py contains *needle*.

    Returns None when the key is not found as a list assignment.
    """
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=\s*\[(.*?)\]", re.MULTILINE | re.DOTALL)
    match = pattern.search(conf_text)
    if not match:
        return None
    return needle in match.group(1)


@dataclass
class _Conf:
    """Small wrapper around conf.py text to reduce repetition across checks."""

    text: str

    @property
    def available(self) -> bool:
        return bool(self.text)

    def value(self, key: str) -> str | None:
        """A plain (non-f-string) assignment value, or None."""
        return _conf_assignment(self.text, key)

    def fstring(self, key: str) -> str | None:
        """The literal text of an f-string assignment (braces included), or None."""
        match = re.search(rf"{re.escape(key)}\s*=\s*f['\"]([^'\"]+)", self.text)
        return match.group(1) if match else None

    def is_fstring(self, key: str) -> bool:
        return bool(re.search(rf"^\s*{re.escape(key)}\s*=\s*f['\"]", self.text, re.MULTILINE))

    def value_or_fstring(self, key: str) -> str | None:
        return self.value(key) or self.fstring(key)

    def list_contains(self, key: str, needle: str) -> bool | None:
        return _conf_list_contains(self.text, key, needle)

    def list_values(self, key: str) -> list[str] | None:
        pattern = re.compile(rf"^\s*{re.escape(key)}\s*=\s*\[(.*?)\]", re.MULTILINE | re.DOTALL)
        match = pattern.search(self.text)
        if not match:
            return None
        return re.findall(r"""['"]([^'"]+)['"]""", match.group(1))


def _load_conf(docs_dir: Path | None) -> _Conf:
    """Return a _Conf wrapper for the docs' conf.py (empty text if missing)."""
    if docs_dir is None:
        return _Conf("")
    conf_path = docs_dir / "conf.py"
    if not conf_path.is_file():
        return _Conf("")
    try:
        return _Conf(conf_path.read_text(errors="replace"))
    except OSError:
        return _Conf("")


def _no_docs_dir(check: BaseCheck) -> CheckResult:
    return CheckResult(
        check_id=check.id,
        check_name=check.name,
        passed=False,
        message="No docs directory found; cannot run this check.",
    )


def _no_conf(check: BaseCheck) -> CheckResult:
    return CheckResult(
        check_id=check.id,
        check_name=check.name,
        passed=False,
        message="No conf.py found in the docs directory.",
    )


_OLD_URL_ASSIGNMENT_RE = re.compile(
    r"""^[+-]\s*(?:html_baseurl|ogp_site_url)\s*=.*?"""
    r"""(https?://[^\s"'()]*(?:readthedocs-hosted\.com|readthedocs\.io|documentation\.ubuntu\.com)[^\s"'()]*)""",
    re.MULTILINE,
)


def _derive_old_url(repo_root: Path, docs_dir: Path | None) -> str | None:
    """Best-effort: find a historical RTD/documentation.ubuntu.com URL for
    this docs set by scanning the git history of conf.py.

    Only considers ``html_baseurl``/``ogp_site_url`` assignment lines (not
    arbitrary comments or unrelated tool doc links elsewhere in the diff),
    and picks the most frequently occurring candidate.
    """
    if docs_dir is None:
        return None
    conf_path = docs_dir / "conf.py"
    try:
        rel = conf_path.relative_to(repo_root)
    except ValueError:
        return None
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "log", "-n", "50", "-p", "--", str(rel)],
            capture_output=True, text=True, timeout=15, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    matches = _OLD_URL_ASSIGNMENT_RE.findall(result.stdout)
    if not matches:
        return None
    from collections import Counter

    return Counter(matches).most_common(1)[0][0]


_ADDONS_DATA_RE = re.compile(
    r'<script[^>]+id=["\']readthedocs-addons-data["\'][^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)


def _parse_addons_data(html_text: str) -> dict | None:
    """Parse the RTD addons JSON payload embedded in a page, if present."""
    import json

    match = _ADDONS_DATA_RE.search(html_text)
    if not match:
        return None
    try:
        data = json.loads(match.group(1))
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


# ---------------------------------------------------------------------------
# Repository checks (conf.py)
# ---------------------------------------------------------------------------


class SlugCheck(BaseCheck):
    id = "migration-slug"
    name = "Migration: Slug"
    description = "Checks that conf.py defines a slug matching the docs URL path (e.g. 'example/docs')."
    recommendation = (
        "Set `slug` in `conf.py` to the URL path after the domain, up to the docs "
        "root only — no leading/trailing `/`, no scheme, no language (`en`) or "
        "version segment. It must match the HAProxy frontend path, e.g. "
        "slug = \"data/kafka/docs\" for canonical.com/data/kafka/docs/4/."
    )
    group = MIGRATION_GROUP

    def run(self, repo_root: Path, docs_dir: Path | None, site_ctx: SiteContext | None = None) -> CheckResult:
        if docs_dir is None:
            return _no_docs_dir(self)
        conf = _load_conf(docs_dir)
        if not conf.available:
            return _no_conf(self)
        slug = conf.value("slug")
        if not slug:
            return CheckResult(
                check_id=self.id, check_name=self.name, passed=False,
                message="conf.py does not define a slug.",
                details=["The slug must be the URL path of the docs, e.g. slug = \"example/docs\"."],
            )

        problems: list[str] = []
        if slug.startswith("/") or slug.endswith("/"):
            problems.append("slug must not have a leading or trailing '/'.")
        if "://" in slug:
            problems.append("slug must be a URL path only, not a full URL.")
        segments = [s for s in slug.split("/") if s]
        if segments and (segments[-1].lower() == "en" or site.looks_like_version_segment(segments[-1])):
            problems.append(
                f"slug ends with a language/version segment ('{segments[-1]}'); "
                "it should be the root path only, with no language or version."
            )
        if site_ctx is not None and site_ctx.available and site_ctx.base_url:
            expected = site.expected_slug_from_url(site_ctx.base_url)
            if expected and slug.strip("/") != expected:
                problems.append(
                    f"slug is '{slug}' but the published URL implies '{expected}'."
                )

        if problems:
            return CheckResult(
                check_id=self.id, check_name=self.name, passed=False,
                message="slug does not match the expected shape.",
                details=problems + [f"slug: {slug}"],
            )
        return CheckResult(
            check_id=self.id, check_name=self.name, passed=True,
            message=f"Slug is set to '{slug}'.",
        )


class BaseUrlCheck(BaseCheck):
    id = "migration-baseurl"
    name = "Migration: Base URL"
    description = "Checks that html_baseurl/ogp_site_url are production Canonical URLs with a trailing slash."
    recommendation = (
        "In `conf.py`: "
        "1. Point `html_baseurl` and `ogp_site_url` at the production domain "
        "(canonical.com/ubuntu.com), never readthedocs-hosted.com. "
        "2. End both with a trailing slash. "
        "3. For versioned docs, include the version segment "
        "(f-string over READTHEDOCS_VERSION, e.g. "
        "https://canonical.com/<slug>/<version>/)."
    )
    group = MIGRATION_GROUP

    def _check_value(self, name: str, value: str, is_fstring: bool) -> list[str]:
        problems = []
        if any(rtd in value for rtd in site.RTD_HOSTS):
            problems.append(f"{name} still points at a Read the Docs / RTD-proxy host: {value}")
        else:
            # Compare the parsed host against the major-domains set (shared
            # with the general checks and extendable via --allow-domain),
            # not a hardcoded substring list.
            host = urlparse(value).netloc.split(":")[0]
            if not host or not site.is_major_domain(value):
                problems.append(f"{name} does not point to a production Canonical domain: {value}")
        if is_fstring:
            if not value.endswith("/"):
                problems.append(f"{name} must end with a trailing slash (after the version segment).")
        elif not value.endswith("/"):
            problems.append(f"{name} must end with a trailing slash.")
        return problems

    def run(self, repo_root: Path, docs_dir: Path | None, site_ctx: SiteContext | None = None) -> CheckResult:
        if docs_dir is None:
            return _no_docs_dir(self)
        conf = _load_conf(docs_dir)
        if not conf.available:
            return _no_conf(self)

        baseurl = conf.value("html_baseurl")
        baseurl_is_f = conf.value("html_baseurl") is None and conf.is_fstring("html_baseurl")
        if baseurl is None:
            baseurl = conf.fstring("html_baseurl")

        ogp = conf.value("ogp_site_url")
        ogp_is_f = conf.value("ogp_site_url") is None and conf.is_fstring("ogp_site_url")
        if ogp is None:
            ogp = conf.fstring("ogp_site_url")

        details = [f"html_baseurl: {baseurl}", f"ogp_site_url: {ogp}"]

        if not baseurl and not ogp:
            return CheckResult(
                check_id=self.id, check_name=self.name, passed=False,
                message="conf.py does not define html_baseurl or ogp_site_url.",
                details=details,
            )

        problems: list[str] = []
        if baseurl:
            problems += self._check_value("html_baseurl", baseurl, baseurl_is_f)
        if ogp:
            problems += self._check_value("ogp_site_url", ogp, ogp_is_f)

        # Versioned docs must interpolate the version into the base URL
        # (migrate.rst: f-string over READTHEDOCS_VERSION; some projects
        # substitute a {placeholder} via html_context instead — both vary
        # with the version, which is what matters). A versioned site whose
        # conf.py hardcodes an unversioned base emits broken links in
        # llms.txt/sitemap.xml — the exact Kafka bug.
        if site_ctx is not None and site_ctx.available and site_ctx.base_url:
            versioned = site.unversioned_prefix(site_ctx.base_url) is not None
            if versioned:
                for name, value, is_f in (
                    ("html_baseurl", baseurl, baseurl_is_f),
                    ("ogp_site_url", ogp, ogp_is_f),
                ):
                    if not value:
                        continue
                    has_placeholder = bool(re.search(r"\{[^}]+\}", value))
                    has_literal_version = site.unversioned_prefix(value.rstrip("/") + "/") is not None
                    if not is_f and not has_placeholder and not has_literal_version:
                        problems.append(
                            f"{name} is a plain URL but the docs site is versioned "
                            f"({site_ctx.base_url}); build it as an f-string over "
                            "READTHEDOCS_VERSION (or a {version} placeholder) so "
                            "emitted links carry the version segment."
                        )

        if problems:
            return CheckResult(
                check_id=self.id, check_name=self.name, passed=False,
                message="html_baseurl/ogp_site_url do not match the migration guide.",
                details=problems + details,
            )
        return CheckResult(
            check_id=self.id, check_name=self.name, passed=True,
            message="Base URLs point to a production Canonical domain.",
            details=details,
        )


class SitemapConfigCheck(BaseCheck):
    id = "migration-sitemap-config"
    name = "Migration: Sitemap Config"
    description = "Checks sitemap_url_scheme and sitemap_filename settings in conf.py."
    recommendation = (
        "Set both in `conf.py`: "
        "1. sitemap_url_scheme = \"{link}\" "
        "2. sitemap_filename = \"doc-sitemap.xml\" (the guide's convention; "
        "the plain sphinx-sitemap default `sitemap.xml` also meets the "
        "production requirements, but a different name does not)."
    )
    group = MIGRATION_GROUP

    def run(self, repo_root: Path, docs_dir: Path | None, site_ctx: SiteContext | None = None) -> CheckResult:
        if docs_dir is None:
            return _no_docs_dir(self)
        conf = _load_conf(docs_dir)
        if not conf.available:
            return _no_conf(self)

        scheme = conf.value("sitemap_url_scheme")
        filename = conf.value("sitemap_filename")

        problems = []
        notes = []
        if scheme != "{link}":
            problems.append(f"sitemap_url_scheme is '{scheme}' (expected '{{{{link}}}}').")
        if filename is None:
            notes.append(
                "sitemap_filename is not set; the sphinx-sitemap default "
                "(sitemap.xml) still meets the production requirements, but the "
                "migration guide recommends doc-sitemap.xml."
            )
        elif filename not in ("doc-sitemap.xml", "sitemap.xml"):
            problems.append(
                f"sitemap_filename is '{filename}' (expected 'doc-sitemap.xml' or 'sitemap.xml')."
            )

        if problems:
            return CheckResult(
                check_id=self.id, check_name=self.name, passed=False,
                message="Sitemap configuration does not match the migration guide.",
                details=problems + notes,
            )
        details = [f"sitemap_url_scheme: {scheme}", f"sitemap_filename: {filename}"] + notes
        if notes:
            return CheckResult(
                check_id=self.id, check_name=self.name, passed=True,
                message="Sitemap configuration meets the production requirements (with a note).",
                details=details,
            )
        return CheckResult(
            check_id=self.id, check_name=self.name, passed=True,
            message="Sitemap configuration matches the migration guide.",
            details=details,
        )


class OverwriteLinksCheck(BaseCheck):
    id = "migration-overwrite-links"
    name = "Migration: overwrite_links.js"
    description = "Checks that a link-rewriting script is registered and configured correctly."
    recommendation = (
        "Customise `scripts/url-overwrite.js` from canonical/RTD-Proxy, save as "
        "`_static/js/overwrite_links.js`, register in `html_js_files`. Set "
        "`rtd_address` to the `*.readthedocs-hosted.com` host and `new_address` to "
        "the new path — no protocol, no trailing slash. For tag versioning use the "
        "RTD custom-script addon instead (and remove the file from the repo)."
    )
    group = MIGRATION_GROUP

    # Match the guide's canonical variable names as well as sensible
    # variants teams commonly rename them to (e.g. camelCase, 'old*').
    _RTD_ADDR_RE = re.compile(
        r"""(?:rtd_address|old_address|oldDomain|old_domain)\s*=\s*['"]([^'"]+)['"]"""
    )
    _NEW_ADDR_RE = re.compile(
        r"""(?:new_address|newDomain|new_domain)\s*=\s*['"]([^'"]+)['"]"""
    )
    # Any html_js_files entry whose name suggests a link-overwrite script,
    # regardless of the exact filename/case/underscore convention.
    _SCRIPT_NAME_RE = re.compile(r"overwrite.?links?\.js$", re.IGNORECASE)

    def _find_script_entry(self, conf: _Conf) -> str | None:
        for entry in conf.list_values("html_js_files") or []:
            if self._SCRIPT_NAME_RE.search(entry):
                return entry
        return None

    def _find_script_file(self, docs_dir: Path, entry: str | None) -> Path | None:
        """Locate the script file: by its html_js_files entry (relative to
        html_static_path, default '_static'), or by scanning _static/ for a
        plausibly-named file if not registered."""
        if entry:
            candidate = docs_dir / "_static" / entry
            if candidate.is_file():
                return candidate
        static_dir = docs_dir / "_static"
        if static_dir.is_dir():
            for path in static_dir.rglob("*.js"):
                if self._SCRIPT_NAME_RE.search(path.name):
                    return path
        return None

    def _validate_script(self, script_text: str) -> list[str]:
        """Validate the link-overwrite script content per the migration guide."""
        problems: list[str] = []
        rtd_match = self._RTD_ADDR_RE.search(script_text)
        new_match = self._NEW_ADDR_RE.search(script_text)
        if not rtd_match or not new_match:
            problems.append(
                "Could not find the old-domain/new-domain variable assignments in the script."
            )
            return problems

        rtd_address, new_address = rtd_match.group(1), new_match.group(1)
        if "://" in rtd_address:
            problems.append(f"The old-domain value must not include a protocol: '{rtd_address}'.")
        if "documentation.ubuntu.com" in rtd_address:
            problems.append(
                "The old-domain value must not be a documentation.ubuntu.com URL; "
                "it must be the *.readthedocs-hosted.com URL."
            )
        elif "readthedocs-hosted.com" not in rtd_address and "readthedocs.io" not in rtd_address:
            problems.append(f"The old-domain value does not look like a readthedocs-hosted.com host: '{rtd_address}'.")

        if "://" in new_address:
            problems.append(f"The new-domain value must not include a protocol: '{new_address}'.")
        if new_address.endswith("/"):
            problems.append(f"The new-domain value must not have a trailing slash: '{new_address}'.")
        return problems

    def run(self, repo_root: Path, docs_dir: Path | None, site_ctx: SiteContext | None = None) -> CheckResult:
        if docs_dir is None:
            return _no_docs_dir(self)
        conf = _load_conf(docs_dir)
        if not conf.available:
            return _no_conf(self)

        entry = self._find_script_entry(conf)
        script_path = self._find_script_file(docs_dir, entry)
        script_exists = script_path is not None

        if entry:
            details = [f"html_js_files entry: {entry}", f"Script file present: {script_exists}"]
            if script_exists:
                try:
                    problems = self._validate_script(script_path.read_text(errors="replace"))
                except OSError:
                    problems = []
                if problems:
                    return CheckResult(
                        check_id=self.id, check_name=self.name, passed=False,
                        message="The link-overwrite script is registered but misconfigured.",
                        details=problems,
                    )
            return CheckResult(
                check_id=self.id, check_name=self.name, passed=True,
                message="The link-overwrite script is registered in html_js_files and correctly configured.",
                details=details,
            )
        if script_exists:
            problems = []
            try:
                problems = self._validate_script(script_path.read_text(errors="replace"))
            except OSError:
                pass
            message = (
                f"A link-overwrite script exists ({script_path.relative_to(docs_dir)}) but is not "
                "registered in html_js_files (may be registered via RTD custom script addon)."
            )
            if problems:
                message += " Content issues found (only relevant if this file is actually used):"
            return CheckResult(
                check_id=self.id, check_name=self.name, passed=True,
                message=message,
                details=problems,
            )
        return CheckResult(
            check_id=self.id, check_name=self.name, passed=False,
            message="No link-overwrite script is registered in html_js_files or found in _static/.",
            details=[
                "The migration guide requires overwrite_links.js in html_js_files,",
                "or applied via the RTD custom script addon (for tag versioning).",
            ],
        )


# ---------------------------------------------------------------------------
# Live-site checks
# ---------------------------------------------------------------------------


class SitemapLiveCheck(BaseCheck):
    id = "migration-sitemap-live"
    name = "Migration: Live Sitemap"
    description = "Checks that a sitemap exists at /sitemap.xml or /doc-sitemap.xml with production URLs."
    recommendation = (
        "Sitemap URLs are built from `html_baseurl` + `sitemap_url_scheme`. A "
        "missing or duplicated version segment in `html_baseurl` is the usual "
        "cause — fix it in `conf.py` and rebuild. If the sitemap is missing "
        "entirely, check it's enabled in the Read the Docs project settings."
    )
    group = MIGRATION_GROUP
    requires_site = True

    def run(self, repo_root: Path, docs_dir: Path | None, site_ctx: SiteContext | None = None) -> CheckResult:
        if site_ctx is None or not site_ctx.available:
            return site_unavailable(self, site_ctx)
        base = site_ctx.base_url or ""
        base_host = urlparse(base).netloc

        for name in ("doc-sitemap.xml", "sitemap.xml"):
            url = base.rstrip("/") + "/" + name
            resp, error = http.get(url)
            if resp is not None and resp.status_code < 400 and resp.text.strip():
                locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", resp.text)
                staging = [u for u in locs if site.is_staging(u)]
                if staging:
                    return CheckResult(
                        check_id=self.id, check_name=self.name, passed=False,
                        message=f"{name} contains staging URLs.",
                        details=staging[:5],
                    )
                rtd = [u for u in locs if site.is_rtd_host(u)]
                if rtd:
                    return CheckResult(
                        check_id=self.id, check_name=self.name, passed=False,
                        message=f"{name} contains Read the Docs / old documentation URLs.",
                        details=rtd[:5],
                    )
                wrong_host = [u for u in locs if urlparse(u).netloc and urlparse(u).netloc != base_host]
                if wrong_host:
                    return CheckResult(
                        check_id=self.id, check_name=self.name, passed=False,
                        message=(
                            f"{name} contains URLs on a different host than the resolved "
                            f"production base ({base_host}); check html_baseurl and "
                            "sitemap_url_scheme for a missing/duplicated version segment."
                        ),
                        details=wrong_host[:5],
                    )
                return CheckResult(
                    check_id=self.id, check_name=self.name, passed=True,
                    message=f"{name} is available with {len(locs)} production URL(s).",
                    details=[url],
                )
        return CheckResult(
            check_id=self.id, check_name=self.name, passed=False,
            message="No sitemap found at /sitemap.xml or /doc-sitemap.xml.",
            details=[base],
        )


class CanonicalUrlCheck(BaseCheck):
    id = "migration-canonical-url"
    name = "Migration: Canonical URL"
    description = "Checks that pages have a canonical URL in <head> matching the production docs URL."
    recommendation = (
        "Canonical URLs come from `html_baseurl` in `conf.py`. If they point at "
        "staging or an RTD host, fix `html_baseurl` to the production URL "
        "(with trailing slash and version segment) and rebuild. `overwrite_links.js` "
        "also rewrites them client-side — check its `new_address` value."
    )
    group = MIGRATION_GROUP
    requires_site = True

    _CANONICAL_RE = re.compile(
        r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)["\']|'
        r'<link[^>]+href=["\']([^"\']+)["\'][^>]+rel=["\']canonical["\']'
    )

    def run(self, repo_root: Path, docs_dir: Path | None, site_ctx: SiteContext | None = None) -> CheckResult:
        if site_ctx is None or not site_ctx.available:
            return site_unavailable(self, site_ctx)
        if not site_ctx.pages:
            return no_pages(self, site_ctx)

        base_host = urlparse(site_ctx.base_url or "").netloc
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
            match = self._CANONICAL_RE.search(resp.text)
            href = (match.group(1) or match.group(2)) if match else None
            if href is None:
                missing += 1
                details.append(f"NO canonical URL: {page_url}")
            elif site.is_staging(href):
                missing += 1
                details.append(f"CANONICAL URL IS STAGING: {href}")
            elif site.is_rtd_host(href):
                missing += 1
                details.append(f"CANONICAL URL IS STILL RTD/OLD HOST: {href}")
            elif urlparse(href).netloc != base_host:
                missing += 1
                details.append(f"CANONICAL URL HOST MISMATCH (expected {base_host}): {href}")
            else:
                details.append(f"OK: {href}")

        if missing:
            return CheckResult(
                check_id=self.id, check_name=self.name, passed=False,
                message=f"{missing} of {len(site_ctx.pages)} sampled pages have a missing or incorrect canonical URL.",
                details=details,
            )
        return CheckResult(
            check_id=self.id, check_name=self.name, passed=True,
            message=f"All {len(site_ctx.pages)} sampled pages have a correct canonical URL.",
            details=details,
        )


class NotFoundCheck(BaseCheck):
    id = "migration-404"
    name = "Migration: 404 Page"
    description = "Checks that invalid pages and an invalid version both return a real HTTP 404 (not soft 200)."
    recommendation = (
        "A soft 404 (HTTP 200 for a missing page) is an SEO problem. The HAProxy "
        "config needs `http-response set-status 404 if ...` — see the 'Backend' "
        "section of the migration guide. A wrong `slug` in `conf.py` is the usual "
        "root cause; ask @docproxysupport on Mattermost for config changes."
    )
    group = MIGRATION_GROUP
    requires_site = True

    def _check_url(self, url: str) -> tuple[bool, str]:
        resp, error = http.get(url)
        if resp is None:
            return False, f"Could not request {url}: {error}"
        if resp.status_code == 404:
            return True, f"OK (404): {url}"
        return False, f"HTTP {resp.status_code} instead of 404 (soft 404): {url}"

    def run(self, repo_root: Path, docs_dir: Path | None, site_ctx: SiteContext | None = None) -> CheckResult:
        if site_ctx is None or not site_ctx.available:
            return site_unavailable(self, site_ctx)
        base = (site_ctx.base_url or "").rstrip("/")

        checks = [base + "/invalid-page-should-404/"]
        # Also probe an invalid *version* segment, if the base URL looks versioned.
        unversioned = site.unversioned_prefix(site_ctx.base_url or "")
        if unversioned:
            checks.append(unversioned.rstrip("/") + "/nonexistent-version-should-404/")

        details: list[str] = []
        ok = True
        for url in checks:
            passed, message = self._check_url(url)
            ok = ok and passed
            details.append(message)

        return CheckResult(
            check_id=self.id, check_name=self.name, passed=ok,
            message="Invalid pages return a proper HTTP 404." if ok
                    else "One or more invalid paths returned a soft 404 (HTTP 200/other, not 404).",
            details=details,
        )


class AnalyticsCheck(BaseCheck):
    id = "migration-analytics"
    name = "Migration: Analytics"
    description = "Checks that the cookie consent banner and GTM script are present on pages."
    recommendation = (
        "Add the GTM snippet (`GTM-KNX3CJC` is the Canonical docs container) and the "
        "cookie consent banner to the page templates — the Sphinx Stack ships "
        "defaults in `_templates/header.html` and `html_css_files` "
        "(`cookie-banner.css`). See the migration guide's Analytics section."
    )
    group = MIGRATION_GROUP
    requires_site = True

    # The GTM snippet builds the gtm.js?id=... URL by string concatenation, so
    # match the container ID directly rather than the literal query string
    # (which never appears verbatim in the rendered/minified script).
    _GTM_RE = re.compile(r"['\"]?(GTM-[A-Z0-9]{4,})['\"]?")
    _EXPECTED_GTM_ID = "GTM-KNX3CJC"
    _COOKIE_MARKERS = ("cookie-policy", "cookie-banner", "cookie-consent", "cookie_banner")

    def run(self, repo_root: Path, docs_dir: Path | None, site_ctx: SiteContext | None = None) -> CheckResult:
        if site_ctx is None or not site_ctx.available:
            return site_unavailable(self, site_ctx)
        if not site_ctx.pages:
            return no_pages(self, site_ctx)

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
            gtm_match = self._GTM_RE.search(resp.text)
            has_cookie = any(marker in resp.text.lower() for marker in self._COOKIE_MARKERS)
            if gtm_match and has_cookie:
                note = ""
                if gtm_match.group(1) != self._EXPECTED_GTM_ID:
                    note = f" (note: GTM ID differs from the guide's {self._EXPECTED_GTM_ID})"
                details.append(f"OK ({gtm_match.group(1)}){note}: {page_url}")
            else:
                missing += 1
                missing_bits = []
                if not gtm_match:
                    missing_bits.append("GTM script")
                if not has_cookie:
                    missing_bits.append("cookie banner")
                details.append(f"MISSING {', '.join(missing_bits)}: {page_url}")

        if missing:
            return CheckResult(
                check_id=self.id, check_name=self.name, passed=False,
                message=f"{missing} of {len(site_ctx.pages)} sampled pages lack analytics setup.",
                details=details,
            )
        return CheckResult(
            check_id=self.id, check_name=self.name, passed=True,
            message=f"All {len(site_ctx.pages)} sampled pages have GTM and a cookie banner.",
            details=details,
        )


class FlyoutPdfCheck(BaseCheck):
    id = "migration-flyout-pdf"
    name = "Migration: Flyout & PDF Links"
    description = "Checks that RTD flyout/addons data and PDF download links point at production, not RTD hosts."
    recommendation = (
        "Flyout/PDF links still point at the RTD host. Check `overwrite_links.js` "
        "is loaded and its `rtd_address`/`new_address` match the actual old/new "
        "hosts. Multiple overwrite scripts (repo + RTD custom-script addon) can "
        "conflict — keep only one. See the guide's 'URL rewriting' section."
    )
    group = MIGRATION_GROUP
    requires_site = True

    _PDF_HREF_RE = re.compile(r'href=["\']([^"\']+\.pdf)["\']', re.IGNORECASE)

    def run(self, repo_root: Path, docs_dir: Path | None, site_ctx: SiteContext | None = None) -> CheckResult:
        if site_ctx is None or not site_ctx.available:
            return site_unavailable(self, site_ctx)
        if not site_ctx.pages:
            return no_pages(self, site_ctx)

        details: list[str] = []
        problems = 0
        checked_addons = False
        for url in site_ctx.pages:
            page_url = site.to_page_url(url)
            resp, error = http.get(page_url)
            if resp is None or resp.status_code >= 400:
                continue
            addons = _parse_addons_data(resp.text)
            if addons is not None:
                checked_addons = True
                addons_text = str(addons)
                if any(rtd in addons_text for rtd in site.RTD_HOSTS):
                    problems += 1
                    details.append(f"Addons/flyout data references an RTD host: {page_url}")
                else:
                    details.append(f"OK (addons data clean): {page_url}")
            for pdf_href in self._PDF_HREF_RE.findall(resp.text):
                if site.is_rtd_host(pdf_href) or site.is_staging(pdf_href):
                    problems += 1
                    details.append(f"PDF link points at a non-production host: {pdf_href}")

        if not checked_addons and not details:
            return CheckResult(
                check_id=self.id, check_name=self.name, passed=True,
                message="No RTD addons data or PDF links found on sampled pages (nothing to flag).",
                details=["This check can only verify what is present in the fetched HTML."],
            )
        if problems:
            return CheckResult(
                check_id=self.id, check_name=self.name, passed=False,
                message=f"{problems} flyout/PDF reference(s) still point at a non-production host.",
                details=details,
            )
        return CheckResult(
            check_id=self.id, check_name=self.name, passed=True,
            message="Flyout/addons data and PDF links point at production hosts.",
            details=details,
        )


class FlyoutVersionsCheck(BaseCheck):
    id = "migration-flyout-versions"
    name = "Migration: Flyout Versions"
    description = "Checks that flyout version names look sensible (no leftover 'migrate'/'test' artefacts)."
    recommendation = (
        "Clean up leftover migration versions in the Read the Docs dashboard: "
        "delete or hide `migrate-*`/`test`/`tmp` versions, and remove the temporary "
        "`/latest` redirects that were set up during migration. See the guide's "
        "troubleshooting page ('<version> already exists')."
    )
    group = MIGRATION_GROUP
    requires_site = True

    _ARTEFACT_RE = re.compile(r"(migrate|migration|^test$|^tmp$|^temp$)", re.IGNORECASE)

    def run(self, repo_root: Path, docs_dir: Path | None, site_ctx: SiteContext | None = None) -> CheckResult:
        if site_ctx is None or not site_ctx.available:
            return site_unavailable(self, site_ctx)
        if not site_ctx.pages:
            return no_pages(self, site_ctx)

        versions: set[str] = set()
        for url in site_ctx.pages:
            page_url = site.to_page_url(url)
            resp, error = http.get(page_url)
            if resp is None or resp.status_code >= 400:
                continue
            addons = _parse_addons_data(resp.text)
            if not addons:
                continue
            versions_data = addons.get("versions", {}) if isinstance(addons, dict) else {}
            active = versions_data.get("active", []) if isinstance(versions_data, dict) else []
            for v in active:
                slug = v.get("slug") if isinstance(v, dict) else None
                if slug:
                    versions.add(slug)

        if not versions:
            return CheckResult(
                check_id=self.id, check_name=self.name, passed=True,
                message="No RTD addons version data found on sampled pages; cannot verify version names.",
                details=["This check relies on the RTD addons script being present on the page."],
            )

        artefacts = sorted(v for v in versions if self._ARTEFACT_RE.search(v))
        if artefacts:
            return CheckResult(
                check_id=self.id, check_name=self.name, passed=False,
                message="Flyout exposes version(s) that look like migration artefacts.",
                details=artefacts,
            )
        return CheckResult(
            check_id=self.id, check_name=self.name, passed=True,
            message=f"Flyout versions look sensible: {', '.join(sorted(versions))}.",
        )


class OldUrlRedirectCheck(BaseCheck):
    id = "migration-old-url-redirect"
    name = "Migration: Old URL Redirect"
    description = "Checks that the old Read the Docs / documentation.ubuntu.com URL redirects to the new one."
    recommendation = (
        "Add a redirect from the old URL in the Read the Docs dashboard: for "
        "documentation.ubuntu.com sources use the Ubuntu Documentation Library "
        "project (`/example*` → `https://canonical.com/example/docs/:splat`); for "
        "readthedocs-hosted.com sources set it on the old project itself."
    )
    group = MIGRATION_GROUP
    requires_site = True

    def __init__(self, old_url: str | None = None):
        self.old_url = old_url

    def run(self, repo_root: Path, docs_dir: Path | None, site_ctx: SiteContext | None = None) -> CheckResult:
        if site_ctx is None or not site_ctx.available:
            return site_unavailable(self, site_ctx)

        old_url = self.old_url or _derive_old_url(repo_root, docs_dir)
        if not old_url:
            return CheckResult(
                check_id=self.id, check_name=self.name, passed=True,
                message="Could not determine the old documentation URL; skipping (pass --old-url to check this).",
                details=["Searched conf.py git history for an RTD/documentation.ubuntu.com URL."],
            )

        resp, error = http.get(old_url)
        if resp is None:
            return CheckResult(
                check_id=self.id, check_name=self.name, passed=False,
                message=f"Could not request the old URL: {error}",
                details=[old_url],
            )

        final_host = urlparse(resp.url).netloc
        base_host = urlparse(site_ctx.base_url or "").netloc
        if resp.status_code < 400 and final_host == base_host:
            return CheckResult(
                check_id=self.id, check_name=self.name, passed=True,
                message="The old documentation URL redirects to the new production URL.",
                details=[f"{old_url} -> {resp.url}"],
            )
        return CheckResult(
            check_id=self.id, check_name=self.name, passed=False,
            message=f"The old URL does not redirect to the new production host (ended up at {resp.url}, HTTP {resp.status_code}).",
            details=[old_url],
        )


class SitemapIndexCheck(BaseCheck):
    id = "migration-sitemap-index"
    name = "Migration: Sitemap Index Registration"
    description = "Checks that the docs sitemap is registered in the canonical.com/ubuntu.com sitemap index."
    recommendation = (
        "Submit a PR adding a `<sitemap>` entry to the site-wide index: "
        "github.com/canonical/canonical.com (templates/sitemap-index.xml) or "
        "github.com/canonical/ubuntu.com (templates/sitemap_index.xml). See the "
        "migration guide's 'Sitemap index records' section for the exact format."
    )
    group = MIGRATION_GROUP
    requires_site = True

    def run(self, repo_root: Path, docs_dir: Path | None, site_ctx: SiteContext | None = None) -> CheckResult:
        if site_ctx is None or not site_ctx.available:
            return site_unavailable(self, site_ctx)
        base = site_ctx.base_url or ""
        host = urlparse(base).netloc.split(":")[0]

        if site.host_matches_domain(host, "canonical.com"):
            root = "https://canonical.com"
        elif site.host_matches_domain(host, "ubuntu.com"):
            root = "https://ubuntu.com"
        else:
            return CheckResult(
                check_id=self.id, check_name=self.name, passed=True,
                message=f"Docs are not on canonical.com/ubuntu.com ({host}); sitemap-index check does not apply.",
            )

        # The served site-wide index is at /sitemap.xml (a <sitemapindex>
        # listing every product's sitemap); the guide's repo template files
        # are named sitemap-index.xml / sitemap_index.xml, which are not the
        # actual served path. Try /sitemap.xml first, then those as fallback.
        candidates = [f"{root}/sitemap.xml", f"{root}/sitemap-index.xml", f"{root}/sitemap_index.xml"]
        resp = None
        index_url = candidates[0]
        last_error = None
        for candidate in candidates:
            resp, last_error = http.get(candidate)
            if resp is not None and resp.status_code < 400:
                index_url = candidate
                break
        if resp is None or resp.status_code >= 400:
            status = f"HTTP {resp.status_code}" if resp is not None else last_error
            return CheckResult(
                check_id=self.id, check_name=self.name, passed=False,
                message=f"Could not fetch the site-wide sitemap index ({status}).",
                details=candidates,
            )

        # Match by the unversioned docs path rather than the exact resolved
        # (versioned) base URL: sites often register their sitemap under a
        # different version alias (e.g. 'latest') than the one this scan
        # resolved to (e.g. '4'), which is not itself a problem.
        unversioned = site.unversioned_prefix(base) or base
        base_path = urlparse(unversioned).path.strip("/")
        registered = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", resp.text)
        found = [u for u in registered if base_path and base_path in u and u.endswith("sitemap.xml")]
        if found:
            return CheckResult(
                check_id=self.id, check_name=self.name, passed=True,
                message="This documentation's sitemap is registered in the site-wide sitemap index.",
                details=[index_url] + found,
            )
        return CheckResult(
            check_id=self.id, check_name=self.name, passed=False,
            message="This documentation's sitemap was not found in the site-wide sitemap index.",
            details=[
                index_url,
                "Submit a PR adding a <sitemap> entry — see docs/how-to/migrate.rst 'Sitemap index records'.",
            ],
        )


class UrlShapeCheck(BaseCheck):
    id = "migration-url-shape"
    name = "Migration: Supported URL Shape"
    description = "Checks that the docs URL follows the supported <product>/docs placement under the marketing page."
    recommendation = (
        "Docs should live under the product's marketing page: "
        "`canonical.com/<product>/docs` or `ubuntu.com/<eco>/<product>/docs`. "
        "See the supported-URLs reference in the RTD-Proxy docs. Paths on the "
        "content-cache exception list (dqlite, microk8s, ...) need extra "
        "coordination — contact @docproxysupport on Mattermost."
    )
    group = MIGRATION_GROUP
    requires_site = True

    def run(self, repo_root: Path, docs_dir: Path | None, site_ctx: SiteContext | None = None) -> CheckResult:
        if site_ctx is None or not site_ctx.available:
            return site_unavailable(self, site_ctx)
        base = site_ctx.base_url or ""
        parsed = urlparse(base)
        host = parsed.netloc.split(":")[0]
        segments = [s for s in parsed.path.split("/") if s]

        if not (site.host_matches_domain(host, "canonical.com") or site.host_matches_domain(host, "ubuntu.com")):
            return CheckResult(
                check_id=self.id, check_name=self.name, passed=False,
                message=f"Documentation is not published on canonical.com or ubuntu.com ({host}).",
            )

        while segments and (
            site.is_language_segment(segments[-1]) or site.looks_like_version_segment(segments[-1])
        ):
            segments.pop()

        if not segments or segments[-1] != "docs":
            return CheckResult(
                check_id=self.id, check_name=self.name, passed=False,
                message="URL path does not end in a '/docs' segment as required by the supported-URLs reference.",
                details=[base],
            )

        path_lower = f"{host}/{'/'.join(segments)}".lower()
        exceptions = [e for e in _CACHE_EXCEPTIONS if path_lower.startswith(e)]
        if exceptions:
            return CheckResult(
                check_id=self.id, check_name=self.name, passed=True,
                message=(
                    "URL shape is correct, but this path has a known content-cache "
                    "exception — contact @docproxysupport if not already arranged."
                ),
                details=[base],
            )
        return CheckResult(
            check_id=self.id, check_name=self.name, passed=True,
            message="URL follows the supported <product>/docs placement.",
            details=[base],
        )


class RtdLeakageCheck(BaseCheck):
    id = "migration-no-rtd-leakage"
    name = "Migration: No RTD Leakage"
    description = "Checks that sampled pages contain no links to this docs set's old RTD/documentation.ubuntu.com location or staging hosts."
    recommendation = (
        "Links still point at the old host. Check `overwrite_links.js` is in "
        "`html_js_files` with correct `rtd_address`/`new_address`, and grep the "
        "sources for hardcoded RTD URLs (`grep -r readthedocs docs/`). Links to "
        "OTHER products' docs on documentation.ubuntu.com / readthedocs-hosted.com "
        "(e.g. intersphinx targets) are expected and fine."
    )
    group = MIGRATION_GROUP
    requires_site = True

    _HREF_SRC_RE = re.compile(r'(?:href|src)=["\']([^"\']+)["\']', re.IGNORECASE)
    _RTD_ADDR_IN_JS_RE = re.compile(
        r"""(?:rtd_address|old_address|oldDomain|old_domain)\s*=\s*['"]([^'"]+)['"]"""
    )

    @staticmethod
    def _own_old_specs(
        repo_root: Path, docs_dir: Path | None, site_ctx: SiteContext
    ) -> list[tuple[str | None, str | None]]:
        """(host, first_path_segment) specs identifying THIS docs set's old
        location. A link is only a leak when it points at this product's own
        old home — documentation.ubuntu.com and readthedocs-hosted.com also
        host every OTHER product's docs, and cross-product links (intersphinx,
        related guides) are legitimate. Sources, most specific first:

        1. ``rtd_address`` in overwrite_links.js → (old_host, None): any path
           on the product's dedicated old RTD host.
        2. The old URL from conf.py git history → (old_host, first_segment).
        3. The product segment of the current docs path → (None, product):
           that first path segment on any RTD host.
        """
        specs: list[tuple[str | None, str | None]] = []

        # 1. rtd_address from the overwrite script (dedicated old host).
        if docs_dir is not None:
            for js in docs_dir.rglob("*.js"):
                if "overwrite" not in js.name.lower():
                    continue
                try:
                    text = js.read_text(errors="replace")
                except OSError:
                    continue
                match = RtdLeakageCheck._RTD_ADDR_IN_JS_RE.search(text)
                if match:
                    host = urlparse("https://" + match.group(1).strip("/ ")).netloc
                    if host:
                        specs.append((host, None))

        # 2. Old URL from conf.py git history (host + first path segment).
        old_url = _derive_old_url(repo_root, docs_dir)
        if old_url:
            parsed = urlparse(old_url)
            first_segment = parsed.path.strip("/").split("/")[0] if parsed.path.strip("/") else None
            if parsed.netloc:
                specs.append((parsed.netloc, first_segment or None))

        # 3. Product segment of the current docs path: canonical.com/data/
        # kafka/docs/ → the product is 'kafka', so documentation.ubuntu.com/
        # kafka/... would be this set's old location.
        base_path = urlparse(site_ctx.base_url or "").path.strip("/")
        if base_path:
            segments = base_path.split("/")
            if segments and segments[-1] == "docs":
                segments = segments[:-1]
            if segments:
                specs.append((None, segments[-1]))

        return specs

    @staticmethod
    def _is_own_leak(href: str, specs: list[tuple[str | None, str | None]]) -> bool:
        """True when *href* points at this docs set's old location."""
        if site.is_staging(href):
            return True  # staging links are always a leak
        if not site.is_rtd_host(href):
            return False
        if not specs:
            # Cannot attribute the old location — fall back to flagging any
            # RTD-host link (previous behaviour).
            return True
        parsed = urlparse(href)
        href_host = parsed.netloc
        href_first = parsed.path.strip("/").split("/")[0] if parsed.path.strip("/") else ""
        for host, segment in specs:
            if host is not None:
                host_ok = href_host == host or href_host.endswith("." + host)
                if not host_ok:
                    continue
                if segment is None or href_first == segment:
                    return True
            else:
                # Any RTD host with the product's first path segment.
                if segment and href_first == segment:
                    return True
        return False

    def run(self, repo_root: Path, docs_dir: Path | None, site_ctx: SiteContext | None = None) -> CheckResult:
        if site_ctx is None or not site_ctx.available:
            return site_unavailable(self, site_ctx)
        if not site_ctx.pages:
            return no_pages(self, site_ctx)

        specs = self._own_old_specs(repo_root, docs_dir, site_ctx)

        details: list[str] = []
        leaks = 0
        for url in site_ctx.pages:
            page_url = site.to_page_url(url)
            resp, error = http.get(page_url)
            if resp is None or resp.status_code >= 400:
                status = f"HTTP {resp.status_code}" if resp is not None else error
                details.append(f"UNREACHABLE ({status}): {page_url}")
                continue
            found = set()
            for href in self._HREF_SRC_RE.findall(resp.text):
                if self._is_own_leak(href, specs):
                    found.add(href)
            if found:
                leaks += len(found)
                details.append(f"LEAK on {page_url}: " + ", ".join(sorted(found)[:5]))
            else:
                details.append(f"OK (clean): {page_url}")

        if leaks:
            return CheckResult(
                check_id=self.id, check_name=self.name, passed=False,
                message=f"Found {leaks} link(s) to this docs set's old RTD/staging location across sampled pages.",
                details=details,
            )
        return CheckResult(
            check_id=self.id, check_name=self.name, passed=True,
            message="No links to this docs set's old RTD/staging location found on sampled pages.",
            details=details,
        )


class StaticPathCheck(BaseCheck):
    id = "migration-static-path"
    name = "Migration: Static Path"
    description = "Checks that html_static_path includes '_static', as required for overwrite_links.js discovery."
    recommendation = (
        "Set html_static_path = [\"_static\"] in `conf.py` (append to the list if "
        "it already has other entries). The migration guide requires it so "
        "`overwrite_links.js` and other static assets are discoverable at build time."
    )
    group = MIGRATION_GROUP

    def run(self, repo_root: Path, docs_dir: Path | None, site_ctx: SiteContext | None = None) -> CheckResult:
        if docs_dir is None:
            return _no_docs_dir(self)
        conf = _load_conf(docs_dir)
        if not conf.available:
            return _no_conf(self)

        values = conf.list_values("html_static_path")
        if values is None:
            return CheckResult(
                check_id=self.id, check_name=self.name, passed=False,
                message="conf.py does not define html_static_path as a list.",
            )
        if "_static" in values:
            return CheckResult(
                check_id=self.id, check_name=self.name, passed=True,
                message="html_static_path includes '_static'.",
                details=values,
            )
        return CheckResult(
            check_id=self.id, check_name=self.name, passed=False,
            message="html_static_path does not include '_static'.",
            details=values,
        )
