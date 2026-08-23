"""Published-site context: docs URL resolution, llms.txt parsing, page sampling."""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urljoin, urlparse

from starter_pack_scanner import http

# Number of pages sampled once per scan and shared by all site checks.
SAMPLE_SIZE = 3

# Major Canonical documentation domains (extendable via CLI --allow-domain).
MAJOR_DOMAINS = {
    "canonical.com",
    "ubuntu.com",
    "documentation.ubuntu.com",
    "juju.is",
    "charmhub.io",
    "snapcraft.io",
    "maas.io",
    "microk8s.io",
    "lxd.canonical.com",
    "canonical.example.com",  # starter-pack example domain
}

# Domains explicitly NOT considered a major company domain.
_NON_MAJOR_DOMAINS = {
    "readthedocs.io",
    "readthedocs-hosted.com",
}

_MD_LINK_RE = re.compile(r"\[[^\]]*\]\((\S+?)\)")
_SITEMAP_LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>")

# Files that are site-wide indexes, not individual documentation pages.
_INDEX_FILES = {"llms.txt", "llms-full.txt", "sitemap.xml", "genindex", "search"}

# RTD-style version segments: "4", "1.5", "v2", "latest", "stable".
_VERSION_SEGMENT_RE = re.compile(r"^(v?\d+(\.\d+)*|latest|stable)$", re.IGNORECASE)


def _unversioned_prefix(base_url: str) -> str | None:
    """If *base_url* ends in a version segment, return the unversioned prefix.

    e.g. "https://example.com/docs/4/" → "https://example.com/docs/"
    Returns None when the base URL is not versioned.
    """
    parsed = urlparse(base_url)
    segments = [s for s in parsed.path.split("/") if s]
    if not segments or not _VERSION_SEGMENT_RE.match(segments[-1]):
        return None
    unversioned_path = "/".join(segments[:-1])
    return f"{parsed.scheme}://{parsed.netloc}/{unversioned_path}/"


def unversioned_prefix(base_url: str) -> str | None:
    """Public wrapper around _unversioned_prefix (used by migration checks)."""
    return _unversioned_prefix(base_url)


def rewrite_versioned(url: str, base_url: str) -> str:
    """Insert the version segment into *url* when it points at the
    unversioned base of a versioned docs site.

    Some docs sites (RTD-style versioning) publish at versioned URLs
    (``…/docs/4/page/``) while their llms.txt / sitemap.xml list unversioned
    links (``…/docs/page/``) that return 404. Rewriting them against the
    resolved (versioned) base URL makes the sampled pages reachable.
    """
    prefix = _unversioned_prefix(base_url)
    if prefix and url.startswith(prefix) and not url.startswith(base_url):
        return base_url + url[len(prefix):]
    return url


def _is_index_file(url: str) -> bool:
    """True for site-wide index files that should not be sampled as pages."""
    path = urlparse(url).path.rstrip("/")
    name = path.rsplit("/", 1)[-1]
    return name in _INDEX_FILES


@dataclass
class SiteContext:
    """Everything the live-site checks need, built once per scan."""

    base_url: str | None = None
    llms_txt_url: str | None = None
    llms_txt_text: str | None = None
    pages: list[str] = field(default_factory=list)
    # Sampled URLs exactly as published in llms.txt / sitemap.xml (before
    # any version-segment rewriting). The llms.txt link-integrity check
    # probes these verbatim: if the site is versioned but its published
    # links are not, they 404 and must be reported as broken.
    raw_pages: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def available(self) -> bool:
        return self.base_url is not None


def _conf_value(conf_text: str, key: str) -> str | None:
    """Extract a simple string assignment from conf.py text.

    Handles plain strings and f-strings with only literal parts; returns None
    for values containing interpolations or non-literal expressions.
    """
    # f-string with interpolations — unusable verbatim
    if re.search(rf"^\s*{re.escape(key)}\s*=\s*[rf]*f", conf_text, re.MULTILINE):
        if "{" in conf_text.split(f"{key}", 1)[-1].split("\n", 1)[0]:
            return None
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=\s*[rf]*(['\"])(.*?)\1\s*$", re.MULTILINE)
    match = pattern.search(conf_text)
    if match:
        return match.group(2)
    return None


def _normalise_base(url: str) -> str:
    return url if url.endswith("/") else url + "/"


def resolve_docs_url(
    docs_dir: Path | None,
    override: str | None = None,
) -> tuple[str | None, list[str]]:
    """Resolve the published docs base URL.

    If *override* is given, use it directly. Otherwise parse ``html_baseurl``
    (fallback: ``ogp_site_url``) from conf.py. The candidate URL is then
    fetched following redirects; the final URL after redirect is used.
    """
    diagnostics: list[str] = []
    candidate = override

    if candidate is None and docs_dir is not None:
        conf = docs_dir / "conf.py"
        if conf.is_file():
            text = conf.read_text(errors="replace")
            candidate = _conf_value(text, "html_baseurl") or _conf_value(text, "ogp_site_url")
            if candidate is None:
                diagnostics.append("conf.py defines html_baseurl/ogp_site_url as an f-string; could not extract a literal URL.")
        else:
            diagnostics.append("No conf.py found in the docs directory.")
    elif candidate is None:
        diagnostics.append("No docs directory found; cannot auto-detect the published docs URL.")

    if candidate is None:
        return None, diagnostics

    diagnostics.append(f"Candidate docs URL: {candidate}")
    resp, error = http.get(candidate)
    if resp is None:
        diagnostics.append(f"Could not reach {candidate}: {error}")
        return None, diagnostics
    if resp.status_code >= 400:
        diagnostics.append(f"{candidate} returned HTTP {resp.status_code}.")
        return None, diagnostics

    final = _normalise_base(resp.url)
    if final != _normalise_base(candidate):
        diagnostics.append(f"Redirected to {final}.")
    return final, diagnostics


def parse_llms_txt(text: str) -> list[str]:
    """Extract markdown link targets from llms.txt content."""
    return _MD_LINK_RE.findall(text)


def fetch_sitemap_urls(base_url: str) -> list[str]:
    """Fetch sitemap.xml under *base_url* and return page URLs."""
    url = urljoin(base_url, "sitemap.xml")
    resp, _error = http.get(url)
    if resp is None or resp.status_code >= 400:
        return []
    return _SITEMAP_LOC_RE.findall(resp.text)


def sample_pages(urls: list[str], n: int = SAMPLE_SIZE, seed: int | None = None) -> list[str]:
    """Pick *n* pages from *urls* (random, or first-n when the list is short)."""
    unique = list(dict.fromkeys(urls))
    if len(unique) <= n:
        return unique
    rng = random.Random(seed)
    return sorted(rng.sample(unique, n))


def build_site_context(
    docs_dir: Path | None,
    docs_url_override: str | None = None,
    seed: int | None = None,
) -> SiteContext:
    """Build the shared SiteContext for all live-site checks."""
    ctx = SiteContext()
    base, diagnostics = resolve_docs_url(docs_dir, docs_url_override)
    ctx.errors.extend(diagnostics)
    if base is None:
        return ctx
    ctx.base_url = base

    ctx.llms_txt_url = urljoin(base, "llms.txt")
    resp, error = http.get(ctx.llms_txt_url)
    if resp is not None and resp.status_code < 400:
        ctx.llms_txt_text = resp.text
        links = parse_llms_txt(resp.text)
        # Keep only links pointing back into this docs site.
        internal = [u for u in links if urlparse(u).netloc == urlparse(base).netloc]
        page_urls = internal or links
    else:
        status = f"HTTP {resp.status_code}" if resp is not None else error
        ctx.errors.append(f"Could not fetch llms.txt ({ctx.llms_txt_url}): {status}")
        page_urls = []

    # Index files are not documentation pages; exclude them from sampling.
    page_urls = [u for u in page_urls if not _is_index_file(u)]

    if not page_urls:
        page_urls = [u for u in fetch_sitemap_urls(base) if not _is_index_file(u)]
        if page_urls:
            ctx.errors.append("llms.txt unavailable or empty; sampled pages from sitemap.xml instead.")

    # Sampled URLs exactly as they appear in llms.txt / sitemap.xml
    # (llms.txt entries are Markdown URLs ending in .md).
    ctx.raw_pages = sample_pages(page_urls, seed=seed)

    # Versioned docs sites often list unversioned links in llms.txt /
    # sitemap.xml; rewrite them against the resolved (versioned) base URL
    # so the page-content checks (metadata, markdown, canonical, …) can
    # fetch reachable pages. The link-integrity check (llms-txt-links)
    # uses raw_pages instead — it must detect broken published links.
    ctx.pages = [rewrite_versioned(u, base) for u in ctx.raw_pages]
    return ctx


def to_page_url(url: str) -> str:
    """Normalise a sampled URL to its HTML page form (directory URL).

    ``…/tutorial/index.html.md`` → ``…/tutorial/``
    ``…/tutorial/index.html``    → ``…/tutorial/``
    ``…/tutorial/``              → unchanged
    """
    if url.endswith(".md"):
        url = url[: -len(".md")]
    if url.endswith("index.html"):
        url = url[: -len("index.html")]
    return url


def to_markdown_url(page_url: str) -> str:
    """Build the Markdown-for-AI URL for a page (append index.html.md)."""
    base = page_url if page_url.endswith("/") else page_url + "/"
    return urljoin(base, "index.html.md")


def host_matches_domain(host: str, domain: str) -> bool:
    """True if *host* equals *domain* or is a subdomain of it."""
    host = host.lower().removeprefix("www.")
    domain = domain.lower().removeprefix("www.")
    return host == domain or host.endswith("." + domain)


def is_major_domain(url: str, extra_domains: set[str] | None = None) -> bool:
    """Check whether *url* is hosted on a major company domain."""
    host = urlparse(url).netloc.split(":")[0]
    if not host:
        return False
    for bad in _NON_MAJOR_DOMAINS:
        if host_matches_domain(host, bad):
            return False
    allowed = MAJOR_DOMAINS | (extra_domains or set())
    return any(host_matches_domain(host, d) for d in allowed)


# Hosts that indicate an unmigrated (or staging) documentation set.
RTD_HOSTS = ("readthedocs.io", "readthedocs-hosted.com", "documentation.ubuntu.com")


def is_staging(url: str) -> bool:
    """True if *url* points at a staging environment (staging.* host)."""
    host = urlparse(url).netloc.split(":")[0].lower()
    return host.startswith("staging.") or host.startswith("www.staging.")


def is_rtd_host(url: str) -> bool:
    """True if *url* points at a Read the Docs / old documentation host."""
    host = urlparse(url).netloc.split(":")[0].lower()
    return any(host_matches_domain(host, d) for d in RTD_HOSTS)


def expected_slug_from_url(base_url: str) -> str:
    """Derive the expected conf.py slug from a docs base URL.

    The slug is the URL path after the domain, up to the root of the
    documentation, excluding language and version segments — e.g.
    ``https://canonical.com/data/kafka/docs/4/`` → ``data/kafka/docs``.
    """
    parsed = urlparse(base_url)
    segments = [s for s in parsed.path.split("/") if s]
    # Drop trailing language segment ('en') and version segment ('4', 'latest').
    while segments and (segments[-1] == "en" or _VERSION_SEGMENT_RE.match(segments[-1])):
        segments.pop()
    return "/".join(segments)


def looks_like_version_segment(segment: str) -> bool:
    """True if *segment* looks like an RTD version/language slug (e.g. '4', 'latest')."""
    return bool(_VERSION_SEGMENT_RE.match(segment))
