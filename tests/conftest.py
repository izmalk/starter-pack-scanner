"""Shared test fixtures: local git repos and a stub HTTP layer.

Everything here is offline — no network access, no GitHub requests.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        env={
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_SYSTEM": "/dev/null",
            "HOME": str(cwd),
            "PATH": "/usr/bin:/bin:/usr/local/bin",
        },
    )


def make_repo(
    root: Path,
    *,
    name: str = "repo",
    docs_dir: str | None = "docs",
    starter_pack: bool = True,
    version: str | None = "2.0",
    readme: str | None = None,
    conf_baseurl: str | None = "https://canonical.com/example/docs/",
) -> Path:
    """Create a local git repository that looks like a starter-pack repo.

    Returns the path to the repository (a subdirectory of *root*).
    """
    repo = root / name
    repo.mkdir(parents=True)

    if docs_dir:
        docs = repo / docs_dir
        docs.mkdir(parents=True, exist_ok=True)
        if starter_pack:
            (docs / ".sphinx").mkdir()
        if version is not None:
            dev = docs / "_dev"
            dev.mkdir()
            (dev / "version").write_text(version)
        conf_lines = ["project = 'Example'\n"]
        if conf_baseurl:
            conf_lines.append(f"html_baseurl = '{conf_baseurl}'\n")
        (docs / "conf.py").write_text("".join(conf_lines))

    if readme is None:
        readme = (
            "# Example\n\n"
            "Docs: https://canonical.com/example/docs/\n\n"
            "[![Docs](https://readthedocs.org/projects/example/badge/?version=latest)]"
            "(https://example.readthedocs.io/)\n"
        )
    # noqa: E501 — fixture content above
    (repo / "README.md").write_text(readme)

    _git("init", "-q", "-b", "main", cwd=repo)
    _git("add", "-A", cwd=repo)
    _git("commit", "-q", "-m", "init", cwd=repo)
    return repo


@dataclass
class StubResponse:
    """Minimal stand-in for requests.Response."""

    status_code: int = 200
    text: str = ""
    url: str = ""


class StubHttp:
    """Replaces starter_pack_scanner.http.get with canned responses.

    Responses are matched by substring of the URL. When several keys match,
    the one that matches closest to the end of the URL wins — so a base-URL
    entry does not shadow more specific entries like ".../llms.txt".
    Otherwise a 404 is served.
    """

    def __init__(self, mapping: dict[str, StubResponse] | None = None):
        self.mapping = mapping or {}
        self.requests: list[str] = []

    def get(self, url: str, *, allow_redirects: bool = True):
        self.requests.append(url)
        matches = [(url.rfind(key), key) for key in self.mapping if key in url]
        if matches:
            # Highest position (closest to the end) wins; ties broken by
            # longer key.
            _, key = max(matches, key=lambda m: (m[0], len(m[1])))
            return self.mapping[key], None
        return StubResponse(status_code=404, url=url), None


@pytest.fixture()
def stub_http(monkeypatch):
    """Install a stub HTTP layer; tests configure responses on it."""
    stub = StubHttp()
    import starter_pack_scanner.http as http_mod

    monkeypatch.setattr(http_mod, "get", stub.get)

    # checks.py and site.py do `from starter_pack_scanner import http`
    # and call http.get — patch the shared module attribute so both see it.
    import starter_pack_scanner.checks as checks_mod
    import starter_pack_scanner.site as site_mod

    monkeypatch.setattr(checks_mod.http, "get", stub.get, raising=False)
    monkeypatch.setattr(site_mod.http, "get", stub.get, raising=False)
    return stub


@pytest.fixture()
def repo_factory(tmp_path):
    """Factory for local starter-pack git repositories."""
    return lambda **kwargs: make_repo(tmp_path, **kwargs)


@pytest.fixture()
def local_repo(monkeypatch, repo_factory):
    """A local starter-pack repo whose file:// URL passes validation.

    Validation is patched to allow exactly this fixture's URL; everything
    else still goes through the real validator.
    """
    repo = repo_factory()
    url = f"file://{repo}"

    import starter_pack_scanner.scanner as scanner_mod

    original_validate = scanner_mod.validate_repo_url

    def fake_validate(u: str) -> str | None:
        if u == url:
            return None
        return original_validate(u)

    monkeypatch.setattr(scanner_mod, "validate_repo_url", fake_validate)
    return url


@pytest.fixture()
def client(local_repo, stub_http):
    """FastAPI TestClient for the web GUI (offline; scans use local fixtures)."""
    pytest.importorskip("fastapi.testclient")
    from fastapi.testclient import TestClient

    from starter_pack_scanner.web.app import app

    with TestClient(app) as c:
        yield c
