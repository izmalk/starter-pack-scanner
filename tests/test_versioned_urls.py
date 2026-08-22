"""Tests for versioned-URL rewriting in site.py — offline unit tests."""

from __future__ import annotations

from starter_pack_scanner.site import _unversioned_prefix, rewrite_versioned


class TestUnversionedPrefix:
    def test_numeric_version(self):
        assert _unversioned_prefix("https://example.com/docs/4/") == "https://example.com/docs/"

    def test_dotted_version(self):
        assert _unversioned_prefix("https://example.com/docs/1.5/") == "https://example.com/docs/"

    def test_v_prefixed_version(self):
        assert _unversioned_prefix("https://example.com/docs/v2/") == "https://example.com/docs/"

    def test_latest(self):
        assert _unversioned_prefix("https://example.com/docs/latest/") == "https://example.com/docs/"

    def test_stable(self):
        assert _unversioned_prefix("https://example.com/docs/stable/") == "https://example.com/docs/"

    def test_unversioned_base_returns_none(self):
        assert _unversioned_prefix("https://example.com/docs/") is None

    def test_non_version_segment_returns_none(self):
        # "how-to" is not a version segment
        assert _unversioned_prefix("https://example.com/docs/how-to/") is None


class TestRewriteVersioned:
    BASE = "https://example.com/docs/4/"

    def test_unversioned_link_rewritten(self):
        url = "https://example.com/docs/how-to/deploy/index.html.md"
        assert rewrite_versioned(url, self.BASE) == "https://example.com/docs/4/how-to/deploy/index.html.md"

    def test_already_versioned_unchanged(self):
        url = "https://example.com/docs/4/how-to/deploy/"
        assert rewrite_versioned(url, self.BASE) == url

    def test_other_host_unchanged(self):
        url = "https://other.com/docs/how-to/"
        assert rewrite_versioned(url, self.BASE) == url

    def test_unversioned_base_noop(self):
        url = "https://example.com/docs/how-to/"
        assert rewrite_versioned(url, "https://example.com/docs/") == url

    def test_root_page_rewritten(self):
        url = "https://example.com/docs/index.html.md"
        assert rewrite_versioned(url, self.BASE) == "https://example.com/docs/4/index.html.md"
