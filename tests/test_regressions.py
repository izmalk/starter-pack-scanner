"""Regression tests for bugs found and fixed during development.

Each test guards against a specific defect that previously existed:

1. Versioned-URL rewriting: unversioned llms.txt/sitemap links on
   RTD-style versioned docs sites returned 404 (Kafka docs).
2. README docs-link false positives: generic /docs URLs (juju.is/docs,
   opensearch.org/docs) counted as the product's documentation.
3. Cache-key collisions: check_group was not part of the cache key, so a
   group-filtered scan could be served a cached full scan (CLI, web, batch).
4. FastAPI 422 on empty form fields: Form(...) required on optional fields.
5. f-string URL mangling in _unversioned_prefix.
6. StubHttp shadowing: a base-URL key must not shadow specific paths.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from starter_pack_scanner import cache
from starter_pack_scanner.batch import BatchEntry, run_batch
from starter_pack_scanner.checks import ReadmeDocsLinkCheck, checks_by_group
from starter_pack_scanner.scanner import ScanReport, scan
from starter_pack_scanner.site import SiteContext, _unversioned_prefix, rewrite_versioned
from tests.conftest import StubHttp, StubResponse, make_repo


# ---------------------------------------------------------------------------
# 1. Versioned-URL rewriting (Kafka docs 404 bug)
# ---------------------------------------------------------------------------


class TestVersionedUrlRewriteRegression:
    """The Kafka docs at canonical.com/data/kafka/docs/ redirect to /4/, but
    their llms.txt lists unversioned links that 404. build_site_context must
    rewrite sampled pages against the versioned base."""

    def test_unversioned_llms_link_rewritten(self, stub_http):
        base = "https://canonical.com/data/kafka/docs/4/"
        # llms.txt contains UNVERSIONED links (as the real site does)
        stub_http.mapping = {
            "https://canonical.com/data/kafka/docs/": StubResponse(
                status_code=200, url=base
            ),
            "llms.txt": StubResponse(
                status_code=200,
                text=(
                    "# Kafka docs\n\n"
                    "- [Page A](https://canonical.com/data/kafka/docs/how-to/a/index.html.md)\n"
                    "- [Page B](https://canonical.com/data/kafka/docs/tutorial/b/index.html.md)\n"
                ),
            ),
            "/4/how-to/a/index.html.md": StubResponse(status_code=200, text="# A\n"),
            "/4/tutorial/b/index.html.md": StubResponse(status_code=200, text="# B\n"),
        }
        from starter_pack_scanner.site import build_site_context

        ctx = build_site_context(None, docs_url_override="https://canonical.com/data/kafka/docs/")
        assert ctx.base_url == base
        # Every sampled page must carry the version segment
        for page in ctx.pages:
            assert "/4/" in page, f"page not versioned: {page}"
        # raw_pages keep the unversioned published form
        for raw in ctx.raw_pages:
            assert "/4/" not in raw, f"raw page unexpectedly versioned: {raw}"

    def test_unversioned_sitemap_links_rewritten(self, stub_http):
        base = "https://example.com/docs/2/"
        stub_http.mapping = {
            "https://example.com/docs/": StubResponse(status_code=200, url=base),
            # No llms.txt → falls back to sitemap with unversioned URLs
            "sitemap.xml": StubResponse(
                status_code=200,
                text="<urlset><url><loc>https://example.com/docs/a/</loc></url></urlset>",
            ),
        }
        from starter_pack_scanner.site import build_site_context

        ctx = build_site_context(None, docs_url_override="https://example.com/docs/")
        assert ctx.pages == ["https://example.com/docs/2/a/"]

    def test_scan_site_checks_pass_with_versioned_rewrite(self, local_repo, stub_http):
        """End-to-end: when the docs site is versioned and llms.txt lists
        unversioned links, the page-content checks (page-metadata,
        page-markdown) must still pass via the rewritten URLs — but
        llms-txt-links must FAIL because the published links 404."""
        base = "https://canonical.com/example/docs/4/"
        stub_http.mapping = {
            "https://canonical.com/example/docs/": StubResponse(status_code=200, url=base),
            "llms.txt": StubResponse(
                status_code=200,
                text=(
                    "# docs\n"
                    "- [A](https://canonical.com/example/docs/a/index.html.md)\n"
                ),
            ),
            # Only the VERSIONED URLs resolve; the unversioned published
            # link 404s (as on the real Kafka docs site).
            "docs/a/index.html.md": StubResponse(status_code=404),
            "/4/a/index.html.md": StubResponse(status_code=200, text="# A\n"),
            "/4/a/": StubResponse(
                status_code=200,
                text='<html><head><meta name="description" content="A">'
                '<link rel="canonical" href="' + base + 'a/"></head>'
                '<body><div class="cookie"></div></body></html>',
            ),
        }
        report = scan(local_repo, docs_url="https://canonical.com/example/docs/")
        by_id = {r.check_id: r for r in report.results}
        # Published (unversioned) links are broken → must be reported.
        links = by_id["llms-txt-links"]
        assert not links.passed
        assert any("version segment" in d for d in links.details)
        # Page-content checks use the rewritten (versioned) URLs → pass.
        assert by_id["page-metadata"].passed
        assert by_id["page-markdown"].passed

    def test_llms_txt_links_pass_when_published_links_versioned(self, local_repo, stub_http):
        """When llms.txt publishes correctly versioned links, llms-txt-links
        passes (no false positive from the raw-page probing)."""
        base = "https://canonical.com/example/docs/4/"
        stub_http.mapping = {
            "https://canonical.com/example/docs/": StubResponse(status_code=200, url=base),
            "llms.txt": StubResponse(
                status_code=200,
                text=(
                    "# docs\n"
                    "- [A](https://canonical.com/example/docs/4/a/index.html.md)\n"
                ),
            ),
            "/4/a/index.html.md": StubResponse(status_code=200, text="# A\n"),
            "/4/a/": StubResponse(
                status_code=200,
                text='<html><head><meta name="description" content="A">'
                '<link rel="canonical" href="' + base + 'a/"></head>'
                '<body><div class="cookie"></div></body></html>',
            ),
        }
        report = scan(local_repo, docs_url="https://canonical.com/example/docs/")
        by_id = {r.check_id: r for r in report.results}
        assert by_id["llms-txt-links"].passed
        assert by_id["page-metadata"].passed
        assert by_id["page-markdown"].passed

    def test_version_note_not_fired_for_dead_page(self, local_repo, stub_http):
        """A page deleted from a versioned site: the unversioned link 404s,
        but its rewritten (versioned) URL 404s too. The check must fail, but
        must NOT claim the cause is a missing version segment."""
        base = "https://canonical.com/example/docs/4/"
        stub_http.mapping = {
            "https://canonical.com/example/docs/": StubResponse(status_code=200, url=base),
            "llms.txt": StubResponse(
                status_code=200,
                text=(
                    "# docs\n"
                    "- [A](https://canonical.com/example/docs/a/index.html.md)\n"
                ),
            ),
            # Both the unversioned AND the versioned URL 404 — page is gone.
            "docs/a/index.html.md": StubResponse(status_code=404),
            "/4/a/index.html.md": StubResponse(status_code=404),
        }
        report = scan(local_repo, docs_url="https://canonical.com/example/docs/")
        by_id = {r.check_id: r for r in report.results}
        links = by_id["llms-txt-links"]
        assert not links.passed
        assert not any("version segment" in d for d in links.details)

    def test_version_note_not_fired_when_unversioned_link_redirects(self, local_repo, stub_http):
        """A versioned site whose unversioned links redirect to the versioned
        pages (server-side redirect): the raw link resolves, so the check
        passes and no version note is emitted."""
        base = "https://canonical.com/example/docs/4/"
        stub_http.mapping = {
            "https://canonical.com/example/docs/": StubResponse(status_code=200, url=base),
            "llms.txt": StubResponse(
                status_code=200,
                text=(
                    "# docs\n"
                    "- [A](https://canonical.com/example/docs/a/index.html.md)\n"
                ),
            ),
            # Unversioned link redirects (200) to the versioned page.
            "docs/a/index.html.md": StubResponse(status_code=200, url=base + "a/index.html.md"),
            "/4/a/index.html.md": StubResponse(status_code=200, text="# A\n"),
            "/4/a/": StubResponse(
                status_code=200,
                text='<html><head><meta name="description" content="A">'
                '<link rel="canonical" href="' + base + 'a/"></head>'
                '<body><div class="cookie"></div></body></html>',
            ),
        }
        report = scan(local_repo, docs_url="https://canonical.com/example/docs/")
        by_id = {r.check_id: r for r in report.results}
        links = by_id["llms-txt-links"]
        # The published link resolves (via redirect) → check passes.
        assert links.passed
        assert not any("version segment" in d for d in links.details)


class TestReadmeDocsLinkRegression:
    """Generic docs URLs from OTHER products must not satisfy the check."""

    def test_other_products_docs_do_not_count(self, tmp_path):
        repo = make_repo(
            tmp_path,
            readme=(
                "# Product\n\n"
                "See https://juju.is/docs and https://opensearch.org/docs "
                "for general documentation.\n"
            ),
        )
        result = ReadmeDocsLinkCheck().run(repo, repo / "docs")
        assert not result.passed
        assert "product documentation" in result.message

    def test_product_link_inside_versioned_path_counts(self, tmp_path):
        from starter_pack_scanner.site import SiteContext

        repo = make_repo(
            tmp_path,
            readme="# Product\n\nTutorial: https://canonical.com/example/docs/4/tutorial/\n",
        )
        ctx = SiteContext(base_url="https://canonical.com/example/docs/4/")
        result = ReadmeDocsLinkCheck().run(repo, repo / "docs", ctx)
        assert result.passed

    def test_trailing_slash_mismatch_tolerated(self, tmp_path):
        from starter_pack_scanner.site import SiteContext

        # README link without trailing slash, expected base with one.
        repo = make_repo(
            tmp_path,
            readme="# Product\n\nDocs: https://canonical.com/example/docs\n",
        )
        ctx = SiteContext(base_url="https://canonical.com/example/docs/")
        result = ReadmeDocsLinkCheck().run(repo, repo / "docs", ctx)
        assert result.passed


# ---------------------------------------------------------------------------
# 3. Cache-key collisions with check_group
# ---------------------------------------------------------------------------


class TestCacheKeyGroupCollisionRegression:
    """A group-filtered scan must never be served a cached full scan
    (and vice versa). This bug existed in the CLI, the web app, AND
    run_batch — all three must fold the group into the key."""

    def test_batch_cache_distinguishes_group(self, tmp_path, monkeypatch, local_repo):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        full = BatchEntry(repo=local_repo, offline=True)
        grouped = BatchEntry(repo=local_repo, offline=True, check_group="migration")

        # Full scan first, then group scan — must NOT reuse the full report.
        full_report = run_batch([full])[0][1]
        group_report = run_batch([grouped])[0][1]
        assert len(full_report.results) > len(group_report.results)
        group_ids = {r.check_id for r in group_report.results}
        assert all(i.startswith("migration-") for i in group_ids)

    def test_batch_group_then_full(self, tmp_path, monkeypatch, local_repo):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        grouped = BatchEntry(repo=local_repo, offline=True, check_group="migration")
        full = BatchEntry(repo=local_repo, offline=True)

        group_report = run_batch([grouped])[0][1]
        full_report = run_batch([full])[0][1]
        assert len(full_report.results) > len(group_report.results)

    def test_scan_group_vs_full_different_results(self, local_repo):
        full = scan(local_repo, offline=True)
        grouped = scan(local_repo, offline=True, check_group="migration")
        assert len(full.results) != len(grouped.results)


# ---------------------------------------------------------------------------
# 4. FastAPI 422 on empty form fields
# ---------------------------------------------------------------------------


class TestFormEmptyFieldRegression:
    """Empty form fields must render friendly errors, not FastAPI 422s."""

    def test_empty_repo_url_is_friendly_error(self, client):
        resp = client.post("/scan", data={"repo_url": ""})
        assert resp.status_code == 200
        assert "Scan failed" in resp.text
        assert "enter a repository URL" in resp.text

    def test_empty_batch_yaml_runs_example(self, client, monkeypatch):
        monkeypatch.setattr(
            "starter_pack_scanner.web.app.EXAMPLE_BATCH_YAML",
            "repos:\n  - file:///etc/passwd\n",
        )
        resp = client.post("/batch", data={"batch_yaml": ""})
        assert resp.status_code == 200
        assert "Batch scan report" in resp.text


# ---------------------------------------------------------------------------
# 5. _unversioned_prefix URL construction
# ---------------------------------------------------------------------------


class TestUnversionedPrefixConstructionRegression:
    """An earlier version built the prefix with a broken f-string that
    produced 'https://example.com/d/a/t/a///...' — assert well-formed output."""

    @pytest.mark.parametrize(
        "base,expected",
        [
            ("https://example.com/docs/4/", "https://example.com/docs/"),
            ("https://canonical.com/data/kafka/docs/4/", "https://canonical.com/data/kafka/docs/"),
            ("https://example.com/docs/latest/", "https://example.com/docs/"),
            ("https://example.com/docs/1.5/", "https://example.com/docs/"),
        ],
    )
    def test_prefix_well_formed(self, base, expected):
        prefix = _unversioned_prefix(base)
        assert prefix == expected
        # No mangled segments (the old bug produced single-char segments)
        assert "//" not in prefix.replace("https://", "").replace("http://", "")
        assert "/d/" not in prefix

    def test_rewrite_produces_valid_url(self):
        url = rewrite_versioned(
            "https://example.com/docs/a/index.html.md", "https://example.com/docs/4/"
        )
        assert url == "https://example.com/docs/4/a/index.html.md"


# ---------------------------------------------------------------------------
# 6. StubHttp key shadowing (test infrastructure regression)
# ---------------------------------------------------------------------------


class TestStubHttpShadowingRegression:
    """A base-URL key must not shadow more specific keys like llms.txt —
    the closest-to-end match wins."""

    def test_base_url_does_not_shadow_llms_txt(self):
        base = "https://example.com/docs/"
        stub = StubHttp(
            {
                base: StubResponse(status_code=200, url=base),
                "llms.txt": StubResponse(status_code=200, text="# docs\n"),
            }
        )
        resp, _ = stub.get(base + "llms.txt")
        assert resp.text == "# docs\n"

    def test_most_specific_key_wins(self):
        stub = StubHttp(
            {
                "page": StubResponse(status_code=200, text="generic"),
                "page-a": StubResponse(status_code=200, text="specific"),
            }
        )
        resp, _ = stub.get("https://example.com/docs/page-a/")
        assert resp.text == "specific"


# ---------------------------------------------------------------------------
# 7. ScanReport error handling (clone failures never raise)
# ---------------------------------------------------------------------------


class TestScanErrorHandlingRegression:
    def test_invalid_url_never_raises(self):
        report = scan("file:///etc/passwd")
        assert isinstance(report, ScanReport)
        assert report.error is not None

    def test_clone_failure_never_raises(self):
        report = scan("https://github.com/canonical/definitely-not-real-xyz-123")
        assert isinstance(report, ScanReport)
        assert report.error is not None
        assert "clone" in report.error.lower()

    def test_report_serialization_roundtrip_preserves_error(self):
        report = ScanReport(
            repo_url="https://example.com/x",
            scanned_at=datetime(2026, 8, 22, 10, 0, tzinfo=timezone.utc),
            error="something failed",
        )
        restored = ScanReport.from_dict(report.to_dict())
        assert restored.error == "something failed"
        assert restored.results == []


# ---------------------------------------------------------------------------
# 8. Clone depth (RtdWebhookCheck + _derive_old_url need git history)
# ---------------------------------------------------------------------------


class TestCloneDepthRegression:
    """clone_repo() must use --depth 50 (not 1) so that RtdWebhookCheck can
    find the commit that last touched docs/ and _derive_old_url can scan
    conf.py history. A revert to depth 1 silently breaks both heuristics."""

    def test_clone_depth_is_50(self):
        from starter_pack_scanner.scanner import _CLONE_DEPTH
        assert _CLONE_DEPTH == 50
