"""Unit tests for repo-level checks against local fixture repos — offline."""

from __future__ import annotations

from pathlib import Path

from starter_pack_scanner.checks import (
    ALL_CHECKS,
    CheckResult,
    DocsLocationCheck,
    ReadmeDocsLinkCheck,
    ReadmeRtdBadgeCheck,
    VersionCheck,
)
from tests.conftest import make_repo


def run_check(check, repo_root: Path, docs_dir: Path | None):
    return check.run(repo_root, docs_dir)


class TestCheckRegistry:
    def test_all_checks_have_metadata(self):
        for cls in ALL_CHECKS:
            check = cls() if cls is not DocsLocationCheck else cls()
            assert check.id, f"{cls} missing id"
            assert check.name, f"{cls} missing name"
            assert check.description, f"{cls} missing description"

    def test_unique_ids(self):
        ids = [cls().id for cls in ALL_CHECKS]
        assert len(ids) == len(set(ids))


class TestDocsLocationCheck:
    def test_standard_docs_dir(self, tmp_path):
        repo = make_repo(tmp_path, docs_dir="docs")
        result = run_check(DocsLocationCheck(), repo, repo / "docs")
        assert result.passed

    def test_nonstandard_docs_dir(self, tmp_path):
        repo = make_repo(tmp_path, docs_dir="documentation")
        result = run_check(DocsLocationCheck(), repo, repo / "documentation")
        assert not result.passed
        assert "documentation" in result.message

    def test_no_docs_dir(self, tmp_path):
        repo = make_repo(tmp_path, docs_dir=None)
        result = run_check(DocsLocationCheck(), repo, None)
        assert not result.passed


class TestVersionCheck:
    def test_version_file_found(self, tmp_path, monkeypatch):
        repo = make_repo(tmp_path, version="2.0")
        monkeypatch.setattr(VersionCheck, "_fetch_latest_version", lambda self: "2.0")
        result = run_check(VersionCheck(), repo, repo / "docs")
        assert result.passed
        assert "2.0" in result.message

    def test_outdated_version(self, tmp_path, monkeypatch):
        repo = make_repo(tmp_path, version="1.0")
        monkeypatch.setattr(VersionCheck, "_fetch_latest_version", lambda self: "2.0")
        result = run_check(VersionCheck(), repo, repo / "docs")
        assert not result.passed
        assert "outdated" in result.message

    def test_no_version_file(self, tmp_path):
        repo = make_repo(tmp_path, version=None)
        result = run_check(VersionCheck(), repo, repo / "docs")
        assert not result.passed
        assert "version file" in result.message.lower()


class TestReadmeChecks:
    def test_docs_link_found(self, tmp_path):
        repo = make_repo(tmp_path)
        result = run_check(ReadmeDocsLinkCheck(), repo, repo / "docs")
        assert result.passed

    def test_docs_link_missing(self, tmp_path):
        repo = make_repo(tmp_path, readme="# Just a title\nNothing else.\n")
        result = run_check(ReadmeDocsLinkCheck(), repo, repo / "docs")
        assert not result.passed

    def test_rtd_badge_found(self, tmp_path):
        repo = make_repo(tmp_path)
        result = run_check(ReadmeRtdBadgeCheck(), repo, repo / "docs")
        assert result.passed

    def test_rtd_badge_missing(self, tmp_path):
        repo = make_repo(tmp_path, readme="# Title\nDocs: https://canonical.com/x\n")
        result = run_check(ReadmeRtdBadgeCheck(), repo, repo / "docs")
        assert not result.passed

    def test_no_readme(self, tmp_path):
        repo = make_repo(tmp_path, readme=None)
        (repo / "README.md").unlink()
        result = run_check(ReadmeDocsLinkCheck(), repo, repo / "docs")
        assert not result.passed
        assert "README" in result.message


class TestCheckResult:
    def test_str_pass(self):
        r = CheckResult(check_id="x", check_name="X", passed=True, message="fine")
        assert "PASS" in str(r)
        assert "fine" in str(r)

    def test_str_fail_with_details(self):
        r = CheckResult(
            check_id="x", check_name="X", passed=False, message="bad", details=["d1", "d2"]
        )
        s = str(r)
        assert "FAIL" in s
        assert "d1" in s and "d2" in s
