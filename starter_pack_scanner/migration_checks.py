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
from pathlib import Path

from starter_pack_scanner import http, site
from starter_pack_scanner.base import BaseCheck, CheckResult
from starter_pack_scanner.site import SiteContext

# Migration check group identifier (used by CLI/GUI to select the group).
MIGRATION_GROUP = "migration"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _read_conf(docs_dir: Path | None) -> str:
    """Return the conf.py contents, or an empty string."""
    if docs_dir is None:
        return ""
    conf = docs_dir / "conf.py"
    if not conf.is_file():
        return ""
    try:
        return conf.read_text(errors="replace")
    except OSError:
        return ""


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


def _no_docs_dir(check: BaseCheck) -> CheckResult:
    return CheckResult(
        check_id=check.id,
        check_name=check.name,
        passed=False,
        message="No docs directory found; cannot run this check.",
    )


# ---------------------------------------------------------------------------
# Repository checks (conf.py)
# ---------------------------------------------------------------------------


class SlugCheck(BaseCheck):
    id = "migration-slug"
    name = "Migration: Slug"
    description = "Checks that conf.py defines a slug matching the docs URL path (e.g. 'example/docs')."
    group = MIGRATION_GROUP

    def run(self, repo_root: Path, docs_dir: Path | None, site_ctx: SiteContext | None = None) -> CheckResult:
        if docs_dir is None:
            return _no_docs_dir(self)
        conf = _read_conf(docs_dir)
        if not conf:
            return CheckResult(
                check_id=self.id, check_name=self.name, passed=False,
                message="No conf.py found in the docs directory.",
            )
        slug = _conf_assignment(conf, "slug")
        if not slug:
            return CheckResult(
                check_id=self.id, check_name=self.name, passed=False,
                message="conf.py does not define a slug.",
                details=["The slug must be the URL path of the docs, e.g. slug = \"example/docs\"."],
            )
        return CheckResult(
            check_id=self.id, check_name=self.name, passed=True,
            message=f"Slug is set to '{slug}'.",
        )


class BaseUrlCheck(BaseCheck):
    id = "migration-baseurl"
    name = "Migration: Base URL"
    description = "Checks that html_baseurl/ogp_site_url point to the production Canonical domain."
    group = MIGRATION_GROUP

    _PRODUCTION_HOSTS = ("canonical.com", "ubuntu.com", "juju.is", "charmhub.io",
                         "snapcraft.io", "maas.io", "microk8s.io", "anbox-cloud.io")

    def run(self, repo_root: Path, docs_dir: Path | None, site_ctx: SiteContext | None = None) -> CheckResult:
        if docs_dir is None:
            return _no_docs_dir(self)
        conf = _read_conf(docs_dir)
        if not conf:
            return CheckResult(
                check_id=self.id, check_name=self.name, passed=False,
                message="No conf.py found in the docs directory.",
            )

        baseurl = _conf_assignment(conf, "html_baseurl")
        ogp = _conf_assignment(conf, "ogp_site_url")

        # f-string form: html_baseurl = f"https://canonical.com/example/docs/{...}"
        if baseurl is None:
            fmatch = re.search(
                r"html_baseurl\s*=\s*f['\"]([^'\"]+)", conf)
            baseurl = fmatch.group(1) if fmatch else None
        if ogp is None:
            fmatch = re.search(r"ogp_site_url\s*=\s*f['\"]([^'\"]+)", conf)
            ogp = fmatch.group(1) if fmatch else None

        details = [f"html_baseurl: {baseurl}", f"ogp_site_url: {ogp}"]

        if not baseurl and not ogp:
            return CheckResult(
                check_id=self.id, check_name=self.name, passed=False,
                message="conf.py does not define html_baseurl or ogp_site_url.",
                details=details,
            )

        bad = []
        for name, value in (("html_baseurl", baseurl), ("ogp_site_url", ogp)):
            if value and not any(host in value for host in self._PRODUCTION_HOSTS):
                bad.append(name)
        if bad:
            return CheckResult(
                check_id=self.id, check_name=self.name, passed=False,
                message=f"{', '.join(bad)} do not point to a production Canonical domain.",
                details=details + ["Expected a canonical.com/ubuntu.com (or similar) URL."],
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
    group = MIGRATION_GROUP

    def run(self, repo_root: Path, docs_dir: Path | None, site_ctx: SiteContext | None = None) -> CheckResult:
        if docs_dir is None:
            return _no_docs_dir(self)
        conf = _read_conf(docs_dir)
        if not conf:
            return CheckResult(
                check_id=self.id, check_name=self.name, passed=False,
                message="No conf.py found in the docs directory.",
            )

        scheme = _conf_assignment(conf, "sitemap_url_scheme")
        filename = _conf_assignment(conf, "sitemap_filename")

        problems = []
        if scheme != "{link}":
            problems.append(f"sitemap_url_scheme is '{scheme}' (expected '{{link}}').")
        if filename != "doc-sitemap.xml":
            problems.append(f"sitemap_filename is '{filename}' (expected 'doc-sitemap.xml').")

        if problems:
            return CheckResult(
                check_id=self.id, check_name=self.name, passed=False,
                message="Sitemap configuration does not match the migration guide.",
                details=problems,
            )
        return CheckResult(
            check_id=self.id, check_name=self.name, passed=True,
            message="Sitemap configuration matches the migration guide.",
        )


class OverwriteLinksCheck(BaseCheck):
    id = "migration-overwrite-links"
    name = "Migration: overwrite_links.js"
    description = "Checks that overwrite_links.js is registered in html_js_files (or handled via RTD custom script)."
    group = MIGRATION_GROUP

    def run(self, repo_root: Path, docs_dir: Path | None, site_ctx: SiteContext | None = None) -> CheckResult:
        if docs_dir is None:
            return _no_docs_dir(self)
        conf = _read_conf(docs_dir)
        if not conf:
            return CheckResult(
                check_id=self.id, check_name=self.name, passed=False,
                message="No conf.py found in the docs directory.",
            )

        in_js_files = _conf_list_contains(conf, "html_js_files", "overwrite_links.js")
        script_exists = (docs_dir / "_static" / "js" / "overwrite_links.js").is_file()

        if in_js_files:
            return CheckResult(
                check_id=self.id, check_name=self.name, passed=True,
                message="overwrite_links.js is registered in html_js_files.",
                details=[f"Script file present: {script_exists}"],
            )
        if script_exists:
            return CheckResult(
                check_id=self.id, check_name=self.name, passed=True,
                message="overwrite_links.js exists in _static/js/ (may be registered via RTD custom script addon).",
            )
        return CheckResult(
            check_id=self.id, check_name=self.name, passed=False,
            message="overwrite_links.js is not registered in html_js_files and not found in _static/js/.",
            details=[
                "The migration guide requires the script in html_js_files,",
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
    group = MIGRATION_GROUP
    requires_site = True

    def run(self, repo_root: Path, docs_dir: Path | None, site_ctx: SiteContext | None = None) -> CheckResult:
        if site_ctx is None or not site_ctx.available:
            return self._unavailable(site_ctx)
        base = site_ctx.base_url or ""

        for name in ("doc-sitemap.xml", "sitemap.xml"):
            url = base.rstrip("/") + "/" + name
            resp, error = http.get(url)
            if resp is not None and resp.status_code < 400 and resp.text.strip():
                locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", resp.text)
                staging = [u for u in locs if "staging" in u]
                if staging:
                    return CheckResult(
                        check_id=self.id, check_name=self.name, passed=False,
                        message=f"{name} contains staging URLs.",
                        details=staging[:5],
                    )
                return CheckResult(
                    check_id=self.id, check_name=self.name, passed=True,
                    message=f"{name} is available with {len(locs)} URL(s), no staging URLs.",
                    details=[url],
                )
        return CheckResult(
            check_id=self.id, check_name=self.name, passed=False,
            message="No sitemap found at /sitemap.xml or /doc-sitemap.xml.",
            details=[base],
        )

    def _unavailable(self, site_ctx: SiteContext | None) -> CheckResult:
        return CheckResult(
            check_id=self.id, check_name=self.name, passed=False,
            message="Could not resolve the published docs URL; cannot run this check.",
            details=list(site_ctx.errors) if site_ctx else [],
        )


class CanonicalUrlCheck(BaseCheck):
    id = "migration-canonical-url"
    name = "Migration: Canonical URL"
    description = "Checks that pages contain a canonical URL in the HTML head pointing to the production domain."
    group = MIGRATION_GROUP
    requires_site = True

    def run(self, repo_root: Path, docs_dir: Path | None, site_ctx: SiteContext | None = None) -> CheckResult:
        if site_ctx is None or not site_ctx.available:
            return self._unavailable(site_ctx)
        if not site_ctx.pages:
            return CheckResult(
                check_id=self.id, check_name=self.name, passed=False,
                message="No pages could be sampled; cannot check canonical URLs.",
                details=site_ctx.errors,
            )

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
            match = re.search(r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)["\']', resp.text)
            if not match:
                match = re.search(r'<link[^>]+href=["\']([^"\']+)["\'][^>]+rel=["\']canonical["\']', resp.text)
            if match:
                details.append(f"OK: {match.group(1)}")
            else:
                missing += 1
                details.append(f"NO canonical URL: {page_url}")

        if missing:
            return CheckResult(
                check_id=self.id, check_name=self.name, passed=False,
                message=f"{missing} of {len(site_ctx.pages)} sampled pages lack a canonical URL.",
                details=details,
            )
        return CheckResult(
            check_id=self.id, check_name=self.name, passed=True,
            message=f"All {len(site_ctx.pages)} sampled pages have a canonical URL.",
            details=details,
        )

    def _unavailable(self, site_ctx: SiteContext | None) -> CheckResult:
        return CheckResult(
            check_id=self.id, check_name=self.name, passed=False,
            message="Could not resolve the published docs URL; cannot run this check.",
            details=list(site_ctx.errors) if site_ctx else [],
        )


class NotFoundCheck(BaseCheck):
    id = "migration-404"
    name = "Migration: 404 Page"
    description = "Checks that an invalid page returns a real HTTP 404 (not a soft 200)."
    group = MIGRATION_GROUP
    requires_site = True

    def run(self, repo_root: Path, docs_dir: Path | None, site_ctx: SiteContext | None = None) -> CheckResult:
        if site_ctx is None or not site_ctx.available:
            return self._unavailable(site_ctx)
        base = site_ctx.base_url or ""
        url = base.rstrip("/") + "/invalid-page-should-404/"

        resp, error = http.get(url)
        if resp is None:
            return CheckResult(
                check_id=self.id, check_name=self.name, passed=False,
                message=f"Could not request the 404 test page: {error}",
                details=[url],
            )
        if resp.status_code == 404:
            return CheckResult(
                check_id=self.id, check_name=self.name, passed=True,
                message="Invalid pages return a proper HTTP 404.",
                details=[url],
            )
        return CheckResult(
            check_id=self.id, check_name=self.name, passed=False,
            message=f"Invalid pages return HTTP {resp.status_code} instead of 404 (soft 404).",
            details=[url],
        )

    def _unavailable(self, site_ctx: SiteContext | None) -> CheckResult:
        return CheckResult(
            check_id=self.id, check_name=self.name, passed=False,
            message="Could not resolve the published docs URL; cannot run this check.",
            details=list(site_ctx.errors) if site_ctx else [],
        )


class AnalyticsCheck(BaseCheck):
    id = "migration-analytics"
    name = "Migration: Analytics"
    description = "Checks that the cookie consent banner and GTM script are present on pages."
    group = MIGRATION_GROUP
    requires_site = True

    _GTM_RE = re.compile(r"gtm\.js\?id=GTM-[A-Z0-9]+")

    def run(self, repo_root: Path, docs_dir: Path | None, site_ctx: SiteContext | None = None) -> CheckResult:
        if site_ctx is None or not site_ctx.available:
            return self._unavailable(site_ctx)
        if not site_ctx.pages:
            return CheckResult(
                check_id=self.id, check_name=self.name, passed=False,
                message="No pages could be sampled; cannot check analytics.",
                details=site_ctx.errors,
            )

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
            has_gtm = bool(self._GTM_RE.search(resp.text))
            has_cookie = "cookie" in resp.text.lower()
            if has_gtm and has_cookie:
                details.append(f"OK: {page_url}")
            else:
                missing += 1
                missing_bits = []
                if not has_gtm:
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
            message=f"All {len(site_ctx.pages)} sampled pages have GTM and cookie banner.",
            details=details,
        )

    def _unavailable(self, site_ctx: SiteContext | None) -> CheckResult:
        return CheckResult(
            check_id=self.id, check_name=self.name, passed=False,
            message="Could not resolve the published docs URL; cannot run this check.",
            details=list(site_ctx.errors) if site_ctx else [],
        )
