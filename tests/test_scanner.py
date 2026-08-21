"""Tests for the scan pipeline against local git fixtures — fully offline.

The clone path is exercised with local `file://` repositories (created by
the conftest fixtures); live-site checks run against a stubbed HTTP layer.
No requests ever leave the machine.
"""

from __future__ import annotations

from starter_pack_scanner.checks import CheckResult
from starter_pack_scanner.scanner import ScanReport, scan
from tests.conftest import StubResponse


class TestScanLocalRepo:
    def test_scan_returns_report(self, local_repo):
        report = scan(local_repo, offline=True)
        assert isinstance(report, ScanReport)
        assert report.error is None
        assert report.docs_dir == "docs"
        assert report.scanned_at is not None
        assert len(report.results) > 0

    def test_offline_skips_site_checks(self, local_repo):
        report = scan(local_repo, offline=True)
        assert all(not r.message.startswith("Could not resolve") for r in report.results)
        # The four repo-only checks must be present
        ids = {r.check_id for r in report.results}
        assert {"docs-dir", "version", "readme-docs-link", "readme-rtd-badge"} <= ids

    def test_passing_repo(self, local_repo):
        report = scan(local_repo, offline=True)
        by_id = {r.check_id: r for r in report.results}
        assert by_id["docs-dir"].passed
        assert by_id["readme-docs-link"].passed
        assert by_id["readme-rtd-badge"].passed

    def test_include_checks(self, local_repo):
        report = scan(local_repo, offline=True, include_checks={"docs-dir"})
        assert [r.check_id for r in report.results] == ["docs-dir"]

    def test_exclude_checks(self, local_repo):
        report = scan(local_repo, offline=True, exclude_checks={"docs-dir", "version"})
        ids = {r.check_id for r in report.results}
        assert "docs-dir" not in ids
        assert "version" not in ids

    def test_report_counts(self, local_repo):
        report = scan(local_repo, offline=True)
        assert report.passed + report.failed == len(report.results)
        assert report.passed == sum(1 for r in report.results if r.passed)


class TestScanErrors:
    def test_invalid_url_sets_error(self):
        report = scan("file:///etc/passwd")
        assert report.error is not None
        assert "scheme" in report.error.lower()
        assert report.results == []

    def test_clone_failure_sets_error(self):
        # Valid https URL that cannot be cloned (repo does not exist).
        report = scan("https://github.com/canonical/definitely-not-a-real-repo-xyz")
        assert report.error is not None
        assert "clone" in report.error.lower()
        assert report.results == []


class TestScanSerialization:
    def test_roundtrip(self, local_repo):
        report = scan(local_repo, offline=True)
        data = report.to_dict()
        restored = ScanReport.from_dict(data)
        assert restored.repo_url == report.repo_url
        assert restored.scanned_at == report.scanned_at
        assert restored.docs_dir == report.docs_dir
        assert len(restored.results) == len(report.results)
        assert restored.passed == report.passed

    def test_check_result_roundtrip(self):
        r = CheckResult(
            check_id="x", check_name="X", passed=False, message="m", details=["a", "b"]
        )
        restored = CheckResult.from_dict(r.to_dict())
        assert restored == r


class TestScanWithStubbedSite:
    """Live-site checks against the stub HTTP layer (no real network)."""

    def _configure(self, stub: StubHttp) -> None:
        base = "https://canonical.com/example/docs/"
        stub.mapping = {
            base: StubResponse(status_code=200, url=base),
            "llms.txt": StubResponse(
                status_code=200,
                url=base + "llms.txt",
                text=(
                    "# Example docs\n\n"
                    f"- [Page A]({base}page-a/index.html.md)\n"
                    f"- [Page B]({base}page-b/index.html.md)\n"
                    f"- [Full]({base}llms-full.txt)\n"
                ),
            ),
            "llms-full.txt": StubResponse(status_code=200, text="# full index\n"),
            "page-a/index.html.md": StubResponse(status_code=200, text="# Page A\n"),
            "page-b/index.html.md": StubResponse(status_code=200, text="# Page B\n"),
            "page-a/": StubResponse(
                status_code=200,
                text='<html><head><meta name="description" content="Page A">'
                '<link rel="canonical" href="llms.txt"></head><body></body></html>',
            ),
            "page-b/": StubResponse(
                status_code=200,
                text='<html><head><meta name="description" content="Page B">'
                '<link rel="canonical" href="llms.txt"></head><body></body></html>',
            ),
        }

    def test_site_checks_run(self, local_repo, stub_http):
        self._configure(stub_http)
        report = scan(local_repo)
        assert report.error is None
        ids = {r.check_id for r in report.results}
        assert "llms-txt" in ids
        by_id = {r.check_id: r for r in report.results}
        assert by_id["llms-txt"].passed
        assert by_id["docs-domain"].passed  # canonical.com is a major domain

    def test_no_network_requests_when_offline(self, local_repo, stub_http):
        scan(local_repo, offline=True)
        assert stub_http.requests == []
