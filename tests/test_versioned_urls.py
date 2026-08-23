"""Tests for versioned-URL rewriting in site.py — offline unit tests."""

from __future__ import annotations

import pytest

from starter_pack_scanner.site import (
    _unversioned_prefix,
    expected_slug_from_url,
    is_language_segment,
    looks_like_version_segment,
    rewrite_versioned,
)


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

    @pytest.mark.parametrize(
        "segment",
        [
            "default",   # LXD publishes at /lxd/docs/default/
            "current",
            "main",      # branch-name versions are legitimate
            "dev",
            "edge",
            "24.04",     # Ubuntu-style release
            "3.6-lts",   # version with qualifier
            "2.0.0-rc1",
            "1.5.x",
        ],
    )
    def test_non_numeric_version_segments(self, segment):
        # RTD derives the URL segment from the version NAME (alias or
        # branch/tag), so the set is open — not just numbers/latest/stable.
        assert _unversioned_prefix(f"https://example.com/docs/{segment}/") == "https://example.com/docs/"
        assert looks_like_version_segment(segment)

    def test_unversioned_base_returns_none(self):
        assert _unversioned_prefix("https://example.com/docs/") is None

    def test_non_version_segment_returns_none(self):
        # "how-to" is not a version segment
        assert _unversioned_prefix("https://example.com/docs/how-to/") is None

    def test_case_insensitive(self):
        assert _unversioned_prefix("https://example.com/docs/LATEST/") == "https://example.com/docs/"


class TestLanguageSegments:
    @pytest.mark.parametrize("lang", ["en", "en-gb", "en-us", "EN"])
    def test_language_segments(self, lang):
        assert is_language_segment(lang)

    def test_non_language(self):
        assert not is_language_segment("fr")
        assert not is_language_segment("docs")

    def test_slug_drops_language_and_version(self):
        # /en/latest/ after the docs root must not leak into the slug
        # (host example.com, path /docs/en/latest/ → slug 'docs').
        assert expected_slug_from_url("https://example.com/docs/en/latest/") == "docs"

    def test_slug_lxd_default(self):
        # LXD shape: version segment is 'default', not numeric.
        assert expected_slug_from_url("https://canonical.com/lxd/docs/default/") == "lxd/docs"

    def test_slug_kafka_numeric(self):
        assert expected_slug_from_url("https://canonical.com/data/kafka/docs/4/") == "data/kafka/docs"


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


class TestRewriteVersionedNonNumeric:
    """Rewriting must work for non-numeric version segments (LXD shape)."""

    def test_default_segment(self):
        base = "https://canonical.com/lxd/docs/default/"
        url = "https://canonical.com/lxd/docs/how-to/cluster/index.html.md"
        assert rewrite_versioned(url, base) == "https://canonical.com/lxd/docs/default/how-to/cluster/index.html.md"

    def test_already_versioned_unchanged(self):
        base = "https://canonical.com/lxd/docs/default/"
        url = "https://canonical.com/lxd/docs/default/how-to/cluster/"
        assert rewrite_versioned(url, base) == url
