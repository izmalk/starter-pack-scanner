"""Read the Docs platform client: project/build lookups and slug discovery.

All functions are pure and offline-testable: they never raise on network or
parse failures — they return ``None`` / empty values instead. Network access
goes through :mod:`starter_pack_scanner.http` (retries, shared session).

The RTD API v3 is publicly readable for *public* projects without a token
(anonymous rate limit: 5 req/min). When the ``READTHEDOCS_TOKEN`` env var is
set, it is sent as ``Authorization: Token <t>``, lifting the rate limit to
60 req/min.
"""

from __future__ import annotations

import json
import os
import re
from urllib.parse import urlparse

from starter_pack_scanner import http

# Read the Docs Business (Canonical) first, then Community as a fallback.
RTD_API_HOSTS = ("https://app.readthedocs.com", "https://app.readthedocs.org")

# GitHub commit-status contexts RTD writes back when the webhook integration
# is wired. The slug follows the last colon:
#   docs/readthedocs.com:canonical-kafka-charm
#   docs/readthedocs.org:pip
_RTD_STATUS_CONTEXT_RE = re.compile(
    r"^docs/readthedocs\.(?:com|org):(.+)$", re.IGNORECASE
)

# <meta name="readthedocs-project-slug" content="canonical-kafka-charm" />
_META_PROJECT_SLUG_RE = re.compile(
    r'<meta\s+name=["\']readthedocs-project-slug["\']\s+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)


def api_token() -> str | None:
    """Return the optional RTD API token from the ``READTHEDOCS_TOKEN`` env var."""
    token = os.environ.get("READTHEDOCS_TOKEN")
    return token.strip() or None if token else None


def _auth_headers() -> dict | None:
    """Build the Authorization header when a token is configured."""
    token = api_token()
    if token is None:
        return None
    return {"Authorization": f"Token {token}"}


def _get_json(url: str) -> dict | list | None:
    """GET *url* and parse a JSON response; return None on any failure.

    Treats 401/403/404/429 as "unavailable" (None), matching the check's
    "cannot verify" rung — these are never a false FAIL.
    """
    resp, error = http.get(url, headers=_auth_headers())
    if resp is None or resp.status_code >= 400:
        return None
    try:
        data = json.loads(resp.text)
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, (dict, list)) else None


def fetch_project(slug: str) -> dict | None:
    """Fetch a project dict from the RTD API v3.

    Tries Business (``.com``) first, then Community (``.org``). Returns the
    parsed project dict, or None when the project is private/missing or the
    API is unreachable.
    """
    for host in RTD_API_HOSTS:
        url = f"{host}/api/v3/projects/{slug}/"
        data = _get_json(url)
        if data is not None:
            return data if isinstance(data, dict) else None
    return None


def fetch_builds(slug: str, commit: str | None = None, limit: int = 5) -> list[dict] | None:
    """Fetch a list of build dicts for *slug*.

    When *commit* is given, filter builds by that commit hash (the RTD API
    supports ``?commit=<sha>``). Returns the ``results`` list, or None on
    failure. An empty list means the project exists but has no matching
    builds.
    """
    params = [f"limit={limit}"]
    if commit:
        params.append(f"commit={commit}")
    query = "&".join(params)

    for host in RTD_API_HOSTS:
        url = f"{host}/api/v3/projects/{slug}/builds/?{query}"
        data = _get_json(url)
        if data is not None and isinstance(data, dict):
            results = data.get("results")
            if isinstance(results, list):
                return results
            # Non-list results → treat as unavailable.
            return None
    return None


def github_commit_status(owner_repo: str, sha: str) -> list[dict] | None:
    """Fetch the combined commit statuses for *sha* from the GitHub API.

    *owner_repo* is ``"owner/repo"`` (e.g. ``"canonical/kafka-operator"``).
    Returns the list of status dicts (the ``statuses`` array), or None on
    failure. Unauthenticated GitHub is rate-limited to 60 req/h/IP.
    """
    url = f"https://api.github.com/repos/{owner_repo}/commits/{sha}/status"
    resp, error = http.get(url)
    if resp is None or resp.status_code >= 400:
        return None
    try:
        data = json.loads(resp.text)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    statuses = data.get("statuses")
    return statuses if isinstance(statuses, list) else None


def slug_from_status_context(context: str) -> str | None:
    """Extract the RTD project slug from a GitHub status context string.

    RTD writes contexts like ``docs/readthedocs.com:canonical-kafka-charm``.
    Returns None when *context* is not an RTD status context.
    """
    match = _RTD_STATUS_CONTEXT_RE.match(context.strip())
    return match.group(1) if match else None


def slug_from_html(html_text: str) -> str | None:
    """Extract the RTD project slug from a published page's ``<meta>`` tag.

    RTD injects ``<meta name="readthedocs-project-slug" content="<slug>">``
    into every page built with the addons script. Returns None when absent.
    """
    match = _META_PROJECT_SLUG_RE.search(html_text)
    return match.group(1) if match else None


def parse_github_repo(remote_url: str) -> str | None:
    """Parse a Git remote URL into ``"owner/repo"`` for GitHub remotes.

    Handles https, ssh, and ``.git``-suffixed forms. Returns None for
    non-GitHub remotes (GitLab, Bitbucket, local paths, etc.).
    """
    url = remote_url.strip()
    if not url:
        return None

    # SSH form: git@github.com:owner/repo(.git)
    ssh_match = re.match(r"git@github\.com:([^/]+)/([^/]+?)(?:\.git)?$", url)
    if ssh_match:
        return f"{ssh_match.group(1)}/{ssh_match.group(2)}"

    # HTTPS form: https://github.com/owner/repo(.git)
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host not in {"github.com", "www.github.com"}:
        return None
    path = parsed.path.strip("/")
    if not path:
        return None
    parts = path.split("/")
    if len(parts) < 2:
        return None
    repo = parts[1]
    if repo.endswith(".git"):
        repo = repo[:-4]
    return f"{parts[0]}/{repo}"


def rtd_status_from_github(owner_repo: str, sha: str) -> dict | None:
    """Find the RTD commit-status entry for *sha*, if any.

    Returns the first status dict whose ``context`` matches an RTD pattern,
    or None when GitHub is unreachable or no RTD status is present.
    """
    statuses = github_commit_status(owner_repo, sha)
    if statuses is None:
        return None
    for status in statuses:
        if not isinstance(status, dict):
            continue
        context = status.get("context", "")
        if slug_from_status_context(context) is not None:
            return status
    return None