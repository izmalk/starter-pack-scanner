"""Tests for the RTD client helpers in starter_pack_scanner.rtd — offline."""

from __future__ import annotations

from tests.conftest import StubHttp, StubResponse


# ---------------------------------------------------------------------------
# slug_from_status_context
# ---------------------------------------------------------------------------


class TestSlugFromStatusContext:
    def test_business_host(self):
        from starter_pack_scanner.rtd import slug_from_status_context
        assert slug_from_status_context("docs/readthedocs.com:canonical-kafka-charm") == "canonical-kafka-charm"

    def test_community_host(self):
        from starter_pack_scanner.rtd import slug_from_status_context
        assert slug_from_status_context("docs/readthedocs.org:pip") == "pip"

    def test_case_insensitive(self):
        from starter_pack_scanner.rtd import slug_from_status_context
        assert slug_from_status_context("Docs/ReadTheDocs.com:My-Project") == "My-Project"

    def test_non_rtd_context(self):
        from starter_pack_scanner.rtd import slug_from_status_context
        assert slug_from_status_context("ci/travis-ci") is None
        assert slug_from_status_context("continuous-integration/jenkins") is None

    def test_empty(self):
        from starter_pack_scanner.rtd import slug_from_status_context
        assert slug_from_status_context("") is None


# ---------------------------------------------------------------------------
# slug_from_html
# ---------------------------------------------------------------------------


class TestSlugFromHtml:
    def test_meta_tag_present(self):
        from starter_pack_scanner.rtd import slug_from_html
        html = (
            '<head><meta name="readthedocs-project-slug" content="canonical-kafka-charm" />'
            '<meta name="readthedocs-version-slug" content="latest" /></head>'
        )
        assert slug_from_html(html) == "canonical-kafka-charm"

    def test_single_quotes(self):
        from starter_pack_scanner.rtd import slug_from_html
        html = "<meta name='readthedocs-project-slug' content='my-project'>"
        assert slug_from_html(html) == "my-project"

    def test_absent(self):
        from starter_pack_scanner.rtd import slug_from_html
        assert slug_from_html("<html><body>no meta here</body></html>") is None


# ---------------------------------------------------------------------------
# parse_github_repo
# ---------------------------------------------------------------------------


class TestParseGithubRepo:
    def test_https(self):
        from starter_pack_scanner.rtd import parse_github_repo
        assert parse_github_repo("https://github.com/canonical/kafka-operator") == "canonical/kafka-operator"

    def test_https_with_git(self):
        from starter_pack_scanner.rtd import parse_github_repo
        assert parse_github_repo("https://github.com/canonical/kafka-operator.git") == "canonical/kafka-operator"

    def test_ssh(self):
        from starter_pack_scanner.rtd import parse_github_repo
        assert parse_github_repo("git@github.com:canonical/kafka-operator.git") == "canonical/kafka-operator"

    def test_ssh_no_git_suffix(self):
        from starter_pack_scanner.rtd import parse_github_repo
        assert parse_github_repo("git@github.com:canonical/kafka-operator") == "canonical/kafka-operator"

    def test_non_github(self):
        from starter_pack_scanner.rtd import parse_github_repo
        assert parse_github_repo("https://gitlab.com/canonical/kafka-operator") is None
        assert parse_github_repo("https://bitbucket.org/canonical/kafka") is None

    def test_empty(self):
        from starter_pack_scanner.rtd import parse_github_repo
        assert parse_github_repo("") is None
        assert parse_github_repo("   ") is None


# ---------------------------------------------------------------------------
# fetch_project / fetch_builds / github_commit_status (via stub_http)
# ---------------------------------------------------------------------------


class TestFetchProject:
    def test_success(self, stub_http):
        from starter_pack_scanner.rtd import fetch_project
        stub_http.mapping = {
            "api/v3/projects/canonical-kafka-charm/": StubResponse(
                status_code=200,
                text='{"slug": "canonical-kafka-charm", "default_branch": "main"}',
            ),
        }
        project = fetch_project("canonical-kafka-charm")
        assert project is not None
        assert project["slug"] == "canonical-kafka-charm"

    def test_404_returns_none(self, stub_http):
        from starter_pack_scanner.rtd import fetch_project
        stub_http.mapping = {
            "api/v3/projects/nonexistent/": StubResponse(status_code=404, text="{}"),
        }
        assert fetch_project("nonexistent") is None

    def test_com_fallback_to_org(self, stub_http):
        from starter_pack_scanner.rtd import fetch_project
        # .com returns 404, .org returns 200.
        stub_http.mapping = {
            "app.readthedocs.com/api/v3/projects/pip/": StubResponse(status_code=404, text="{}"),
            "app.readthedocs.org/api/v3/projects/pip/": StubResponse(
                status_code=200, text='{"slug": "pip"}',
            ),
        }
        project = fetch_project("pip")
        assert project is not None
        assert project["slug"] == "pip"


class TestFetchBuilds:
    def test_with_commit_filter(self, stub_http):
        from starter_pack_scanner.rtd import fetch_builds
        stub_http.mapping = {
            "commit=abc123": StubResponse(
                status_code=200,
                text='{"count": 1, "results": [{"id": 42, "commit": "abc123", "success": true}]}',
            ),
        }
        builds = fetch_builds("my-project", commit="abc123")
        assert builds is not None
        assert len(builds) == 1
        assert builds[0]["id"] == 42

    def test_empty_results(self, stub_http):
        from starter_pack_scanner.rtd import fetch_builds
        stub_http.mapping = {
            "builds/": StubResponse(
                status_code=200, text='{"count": 0, "results": []}',
            ),
        }
        builds = fetch_builds("my-project")
        assert builds == []

    def test_401_returns_none(self, stub_http):
        from starter_pack_scanner.rtd import fetch_builds
        stub_http.mapping = {
            "builds/": StubResponse(status_code=401, text="{}"),
        }
        assert fetch_builds("private-project") is None


class TestGithubCommitStatus:
    def test_success(self, stub_http):
        from starter_pack_scanner.rtd import github_commit_status
        stub_http.mapping = {
            "commits/abc/status": StubResponse(
                status_code=200,
                text='{"state": "success", "statuses": [{"context": "docs/readthedocs.com:my-proj", "state": "success"}]}',
            ),
        }
        statuses = github_commit_status("canonical/kafka-operator", "abc")
        assert statuses is not None
        assert len(statuses) == 1
        assert statuses[0]["context"] == "docs/readthedocs.com:my-proj"

    def test_404_returns_none(self, stub_http):
        from starter_pack_scanner.rtd import github_commit_status
        stub_http.mapping = {
            "commits/abc/status": StubResponse(status_code=404, text="{}"),
        }
        assert github_commit_status("canonical/kafka-operator", "abc") is None


class TestRtdStatusFromGithub:
    def test_finds_rtd_status(self, stub_http):
        from starter_pack_scanner.rtd import rtd_status_from_github
        stub_http.mapping = {
            "commits/abc/status": StubResponse(
                status_code=200,
                text=(
                    '{"state": "success", "statuses": ['
                    '{"context": "ci/travis", "state": "pending"},'
                    '{"context": "docs/readthedocs.com:canonical-kafka-charm", "state": "success",'
                    ' "description": "Read the Docs build succeeded!"}'
                    ']}'
                ),
            ),
        }
        status = rtd_status_from_github("canonical/kafka-operator", "abc")
        assert status is not None
        assert status["context"] == "docs/readthedocs.com:canonical-kafka-charm"
        assert status["description"] == "Read the Docs build succeeded!"

    def test_no_rtd_status(self, stub_http):
        from starter_pack_scanner.rtd import rtd_status_from_github
        stub_http.mapping = {
            "commits/abc/status": StubResponse(
                status_code=200,
                text='{"state": "pending", "statuses": [{"context": "ci/travis", "state": "pending"}]}',
            ),
        }
        assert rtd_status_from_github("canonical/kafka-operator", "abc") is None