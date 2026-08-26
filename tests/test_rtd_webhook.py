"""Tests for the RtdWebhookCheck decision ladder — fully offline.

Each test exercises one rung of the check's decision ladder, using
``make_repo()`` (real local git history) and ``stub_http`` (canned RTD/GitHub
API responses).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from starter_pack_scanner.checks import RtdWebhookCheck
from starter_pack_scanner.site import SiteContext
from tests.conftest import StubResponse, make_repo


def _git(*args: str, cwd: Path) -> str:
    """Run a git command in *cwd* and return stdout (stripped)."""
    result = subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
        env={
            "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.com",
            "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null",
            "HOME": str(cwd), "PATH": "/usr/bin:/bin:/usr/local/bin",
        },
    )
    return result.stdout.strip()


def _docs_commit_sha(repo: Path) -> str:
    """Return the SHA of the last commit touching docs/."""
    return _git("log", "-n", "1", "--format=%H", "--", "docs", cwd=repo)


def _head_sha(repo: Path) -> str:
    return _git("log", "-n", "1", "--format=%H", cwd=repo)


def _make_repo_with_remote(tmp_path: Path) -> Path:
    """Create a repo whose origin remote is a GitHub URL (for parse_github_repo)."""
    repo = make_repo(tmp_path, conf_baseurl="https://canonical.com/example/docs/")
    _git("remote", "add", "origin", "https://github.com/canonical/example-operator.git", cwd=repo)
    return repo


def _site_ctx_with_meta(slug: str = "canonical-example-charm") -> SiteContext:
    """A minimal SiteContext whose sampled page carries the RTD meta tag."""
    return SiteContext(
        base_url="https://canonical.com/example/docs/",
        pages=["https://canonical.com/example/docs/"],
    )


def _meta_page_html(slug: str) -> str:
    return f'<meta name="readthedocs-project-slug" content="{slug}" />'


def _build_json(build_id: int, success: bool, state_code: str = "finished",
                commit: str | None = None, created: str = "2026-08-24T07:47:42Z",
                error: str = "") -> str:
    import json
    return json.dumps({
        "count": 1,
        "results": [{
            "id": build_id,
            "commit": commit or "abc",
            "created": created,
            "finished": "2026-08-24T07:48:16Z",
            "duration": 34,
            "state": {"code": state_code, "name": state_code.capitalize()},
            "success": success,
            "error": error,
            "urls": {"build": f"https://app.readthedocs.com/projects/x/builds/{build_id}/"},
        }],
    })


def _status_json(state: str = "success", desc: str = "Read the Docs build succeeded!",
                 slug: str = "canonical-example-charm") -> str:
    import json
    return json.dumps({
        "state": state,
        "statuses": [{
            "context": f"docs/readthedocs.com:{slug}",
            "state": state,
            "description": desc,
            "target_url": f"https://{slug}--1.com.readthedocs.build/1/",
        }],
    })


# ---------------------------------------------------------------------------
# Decision ladder
# ---------------------------------------------------------------------------


class TestRtdWebhookCannotVerify:
    """Rungs that pass with a "cannot verify" note — never a false FAIL."""

    def test_no_slug_discovered(self, tmp_path, stub_http):
        """No explicit slug, no site_ctx, no GitHub status → cannot verify."""
        repo = _make_repo_with_remote(tmp_path)
        # No RTD API responses stubbed; GitHub status returns 404.
        stub_http.mapping = {
            "commits/": StubResponse(status_code=404, text="{}"),
        }
        check = RtdWebhookCheck()
        result = check.run(repo, repo / "docs", site_ctx=None)
        assert result.passed
        assert "Cannot verify" in result.message

    def test_explicit_slug_no_git_history(self, tmp_path, stub_http):
        """Explicit slug but no docs dir → cannot verify (no commit)."""
        repo = make_repo(tmp_path, docs_dir=None)
        check = RtdWebhookCheck("canonical-kafka-charm")
        result = check.run(repo, None, site_ctx=None)
        assert result.passed
        assert "Cannot verify" in result.message

    def test_rtd_api_unreachable_no_github_status(self, tmp_path, stub_http):
        """RTD API 404 and GitHub 404 → cannot verify."""
        repo = _make_repo_with_remote(tmp_path)
        sha = _docs_commit_sha(repo)
        stub_http.mapping = {
            "builds/?commit=": StubResponse(status_code=404, text="{}"),
            "builds/?limit=1": StubResponse(status_code=404, text="{}"),
            "commits/": StubResponse(status_code=404, text="{}"),
        }
        check = RtdWebhookCheck("canonical-kafka-charm")
        result = check.run(repo, repo / "docs", site_ctx=None)
        assert result.passed
        assert "Cannot verify" in result.message


class TestRtdWebhookPass:
    """Rungs that PASS."""

    def test_build_for_docs_commit_succeeded(self, tmp_path, stub_http):
        """Build for the docs commit with success:true → PASS."""
        repo = _make_repo_with_remote(tmp_path)
        sha = _docs_commit_sha(repo)
        stub_http.mapping = {
            f"commit={sha}": StubResponse(
                status_code=200, text=_build_json(4351453, True, commit=sha),
            ),
        }
        check = RtdWebhookCheck("canonical-kafka-charm")
        result = check.run(repo, repo / "docs", site_ctx=None)
        assert result.passed
        assert "build #4351453 succeeded" in result.message.lower()

    def test_build_in_progress(self, tmp_path, stub_http):
        """Build for the commit, state != finished → PASS (in progress)."""
        repo = _make_repo_with_remote(tmp_path)
        sha = _docs_commit_sha(repo)
        stub_http.mapping = {
            f"commit={sha}": StubResponse(
                status_code=200, text=_build_json(100, None, state_code="building", commit=sha),
            ),
        }
        check = RtdWebhookCheck("canonical-kafka-charm")
        result = check.run(repo, repo / "docs", site_ctx=None)
        assert result.passed
        assert "in progress" in result.message.lower()

    def test_no_exact_build_but_newest_is_newer(self, tmp_path, stub_http):
        """No build for the commit, but newest build is newer → PASS."""
        repo = _make_repo_with_remote(tmp_path)
        sha = _docs_commit_sha(repo)
        # The docs commit is old; the newest build is newer.
        stub_http.mapping = {
            f"commit={sha}": StubResponse(
                status_code=200, text='{"count": 0, "results": []}',
            ),
            "builds/?limit=1": StubResponse(
                status_code=200,
                text=_build_json(99, True, created="2099-01-01T00:00:00Z"),
            ),
        }
        check = RtdWebhookCheck("canonical-kafka-charm")
        result = check.run(repo, repo / "docs", site_ctx=None)
        assert result.passed
        assert "newer than the docs commit" in result.message.lower()

    def test_github_status_present_rtd_unreachable(self, tmp_path, stub_http):
        """RTD API unreachable but GitHub status present → PASS."""
        repo = _make_repo_with_remote(tmp_path)
        sha = _docs_commit_sha(repo)
        stub_http.mapping = {
            f"commit={sha}": StubResponse(status_code=404, text="{}"),
            "builds/?limit=1": StubResponse(status_code=404, text="{}"),
            f"commits/{sha}/status": StubResponse(
                status_code=200, text=_status_json(state="success"),
            ),
        }
        check = RtdWebhookCheck("canonical-kafka-charm")
        result = check.run(repo, repo / "docs", site_ctx=None)
        assert result.passed
        assert "GitHub status" in result.message

    def test_slug_discovered_from_page_meta(self, tmp_path, stub_http):
        """Slug auto-discovered from the published page's <meta> tag."""
        repo = _make_repo_with_remote(tmp_path)
        sha = _docs_commit_sha(repo)
        stub_http.mapping = {
            "canonical.com/example/docs/": StubResponse(
                status_code=200, text=_meta_page_html("discovered-slug"),
            ),
            f"commit={sha}": StubResponse(
                status_code=200, text=_build_json(1, True, commit=sha),
            ),
        }
        site_ctx = _site_ctx_with_meta()
        check = RtdWebhookCheck()  # no explicit slug
        result = check.run(repo, repo / "docs", site_ctx=site_ctx)
        assert result.passed
        assert "discovered-slug" in result.details[0]

    def test_slug_discovered_from_github_status(self, tmp_path, stub_http):
        """Slug auto-discovered from the GitHub commit-status context."""
        repo = _make_repo_with_remote(tmp_path)
        sha = _docs_commit_sha(repo)
        stub_http.mapping = {
            f"commits/{sha}/status": StubResponse(
                status_code=200, text=_status_json(slug="gh-discovered-slug"),
            ),
            f"commit={sha}": StubResponse(
                status_code=200, text=_build_json(1, True, commit=sha),
            ),
        }
        check = RtdWebhookCheck()  # no explicit slug, no site_ctx
        result = check.run(repo, repo / "docs", site_ctx=None)
        assert result.passed
        assert "gh-discovered-slug" in result.details[0]


class TestRtdWebhookFail:
    """Rungs that FAIL."""

    def test_build_for_commit_failed(self, tmp_path, stub_http):
        """Build exists for the commit but success:false → FAIL."""
        repo = _make_repo_with_remote(tmp_path)
        sha = _docs_commit_sha(repo)
        stub_http.mapping = {
            f"commit={sha}": StubResponse(
                status_code=200,
                text=_build_json(500, False, commit=sha, error="Sphinx failed"),
            ),
        }
        check = RtdWebhookCheck("canonical-kafka-charm")
        result = check.run(repo, repo / "docs", site_ctx=None)
        assert not result.passed
        assert "build #500 failed" in result.message.lower()
        assert "Sphinx failed" in result.message

    def test_no_build_newest_older_than_commit(self, tmp_path, stub_http):
        """No build for commit, newest build older than docs commit → FAIL."""
        repo = _make_repo_with_remote(tmp_path)
        sha = _docs_commit_sha(repo)
        stub_http.mapping = {
            f"commit={sha}": StubResponse(
                status_code=200, text='{"count": 0, "results": []}',
            ),
            "builds/?limit=1": StubResponse(
                status_code=200,
                text=_build_json(1, True, created="2020-01-01T00:00:00Z"),
            ),
        }
        check = RtdWebhookCheck("canonical-kafka-charm")
        result = check.run(repo, repo / "docs", site_ctx=None)
        assert not result.passed
        assert "did not fire" in result.message.lower()

    def test_zero_builds_no_github_status(self, tmp_path, stub_http):
        """Project has zero builds and no GitHub status → FAIL."""
        repo = _make_repo_with_remote(tmp_path)
        sha = _docs_commit_sha(repo)
        stub_http.mapping = {
            f"commit={sha}": StubResponse(
                status_code=200, text='{"count": 0, "results": []}',
            ),
            "builds/?limit=1": StubResponse(
                status_code=200, text='{"count": 0, "results": []}',
            ),
            f"commits/{sha}/status": StubResponse(
                status_code=200,
                text='{"state": "pending", "statuses": [{"context": "ci/travis"}]}',
            ),
        }
        check = RtdWebhookCheck("canonical-kafka-charm")
        result = check.run(repo, repo / "docs", site_ctx=None)
        assert not result.passed
        assert "no builds" in result.message.lower()


# ---------------------------------------------------------------------------
# Registry / metadata
# ---------------------------------------------------------------------------


class TestRtdWebhookRegistry:
    def test_registered_in_all_checks(self):
        from starter_pack_scanner.checks import ALL_CHECKS
        assert RtdWebhookCheck in ALL_CHECKS

    def test_has_recommendation(self):
        check = RtdWebhookCheck()
        assert check.recommendation
        assert len(check.recommendation) <= 500

    def test_requires_site(self):
        assert RtdWebhookCheck.requires_site is True

    def test_id_and_name(self):
        check = RtdWebhookCheck()
        assert check.id == "rtd-webhook"
        assert check.name == "RTD Webhook"