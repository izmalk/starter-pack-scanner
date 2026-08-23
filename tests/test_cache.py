"""Tests for the on-disk cache — uses a temp XDG_CACHE_HOME, fully offline."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from starter_pack_scanner import cache
from starter_pack_scanner.checks import CheckResult
from starter_pack_scanner.scanner import ScanReport


def make_report(repo: str = "https://example.com/repo", **kwargs) -> ScanReport:
    defaults = dict(
        branch=None,
        docs_url=None,
        scanned_at=datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc),
        docs_dir="docs",
        results=[
            CheckResult(check_id="a", check_name="A", passed=True, message="ok"),
            CheckResult(check_id="b", check_name="B", passed=False, message="no"),
        ],
        error=None,
    )
    defaults.update(kwargs)
    return ScanReport(repo_url=repo, **defaults)


class TestCacheKey:
    def test_same_config_same_key(self):
        k1 = cache.cache_key("https://example.com/repo")
        k2 = cache.cache_key("https://example.com/repo")
        assert k1 == k2

    def test_trailing_slash_ignored(self):
        assert cache.cache_key("https://example.com/repo/") == cache.cache_key(
            "https://example.com/repo"
        )

    def test_different_branch_different_key(self):
        assert cache.cache_key("https://example.com/repo") != cache.cache_key(
            "https://example.com/repo", branch="main"
        )

    def test_different_docs_url_different_key(self):
        assert cache.cache_key("https://example.com/repo") != cache.cache_key(
            "https://example.com/repo", docs_url="https://docs.example.com"
        )

    def test_different_checks_different_key(self):
        assert cache.cache_key("https://example.com/repo") != cache.cache_key(
            "https://example.com/repo", include_checks={"docs-dir"}
        )


class TestCacheOperations:
    def test_miss_on_empty_cache(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        assert cache.get("nonexistent") is None

    def test_put_get_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        report = make_report()
        key = cache.cache_key(report.repo_url)
        cache.put(key, report)

        loaded = cache.get(key)
        assert loaded is not None
        assert loaded.repo_url == report.repo_url
        assert loaded.scanned_at == report.scanned_at
        assert loaded.passed == 1
        assert loaded.failed == 1

    def test_clear_single_entry(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        key = cache.cache_key("https://example.com/repo")
        cache.put(key, make_report())
        assert cache.clear(key) == 1
        assert cache.get(key) is None
        assert cache.clear(key) == 0

    def test_clear_all(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        for i in range(3):
            cache.put(cache.cache_key(f"https://example.com/repo{i}"), make_report())
        assert cache.clear() == 3
        assert cache.get(cache.cache_key("https://example.com/repo0")) is None

    def test_corrupt_entry_is_miss(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        key = cache.cache_key("https://example.com/repo")
        cache.put(key, make_report())
        # Corrupt the stored JSON
        (cache.cache_dir() / f"{key}.json").write_text("{not json")
        assert cache.get(key) is None

    def test_incompatible_entry_is_miss(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        key = cache.cache_key("https://example.com/repo")
        (cache.cache_dir() / f"{key}.json").write_text('{"unexpected": true}')
        assert cache.get(key) is None


class TestCacheExpiry:
    def test_fresh_entry_is_served(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        key = cache.cache_key("https://example.com/repo")
        cache.put(key, make_report(scanned_at=datetime.now(timezone.utc)))
        assert cache.get(key) is not None

    def test_stale_entry_is_miss_and_removed(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        key = cache.cache_key("https://example.com/repo")
        old = datetime.now(timezone.utc) - cache.MAX_AGE - timedelta(seconds=1)
        cache.put(key, make_report(scanned_at=old))
        assert cache.get(key) is None
        # The stale file must be deleted, not just ignored.
        assert not (cache.cache_dir() / f"{key}.json").exists()

    def test_entry_just_under_max_age_is_served(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        key = cache.cache_key("https://example.com/repo")
        # 1s inside the limit, to avoid a microsecond race between put and get.
        edge = datetime.now(timezone.utc) - cache.MAX_AGE + timedelta(seconds=1)
        cache.put(key, make_report(scanned_at=edge))
        assert cache.get(key) is not None

    def test_naive_timestamp_treated_as_utc(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        key = cache.cache_key("https://example.com/repo")
        old_naive = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=8)
        cache.put(key, make_report(scanned_at=old_naive))
        assert cache.get(key) is None
