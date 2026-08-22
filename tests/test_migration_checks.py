"""Tests for the URL-migration validation checks — offline (stubbed HTTP)."""

from __future__ import annotations

from pathlib import Path

from starter_pack_scanner.checks import ALL_CHECKS, checks_by_group
from starter_pack_scanner.migration_checks import (
    AnalyticsCheck,
    BaseUrlCheck,
    CanonicalUrlCheck,
    NotFoundCheck,
    OverwriteLinksCheck,
    SitemapConfigCheck,
    SitemapLiveCheck,
    SlugCheck,
)
from starter_pack_scanner.site import SiteContext
from tests.conftest import StubResponse


def make_conf_repo(tmp_path: Path, conf: str) -> tuple[Path, Path]:
    """Create a minimal repo with the given conf.py; return (root, docs_dir)."""
    repo = tmp_path / "repo"
    docs = repo / "docs"
    docs.mkdir(parents=True)
    (docs / "conf.py").write_text(conf)
    return repo, docs


class TestGroupRegistry:
    def test_migration_group_registered(self):
        group = checks_by_group("migration")
        assert len(group) == 8
        ids = {c().id for c in group}
        assert "migration-slug" in ids
        assert "migration-404" in ids

    def test_all_checks_have_unique_ids(self):
        ids = [c().id for c in ALL_CHECKS]
        assert len(ids) == len(set(ids))

    def test_general_checks_have_no_group(self):
        from starter_pack_scanner.checks import DocsLocationCheck

        assert getattr(DocsLocationCheck, "group", None) is None


class TestSlugCheck:
    def test_slug_set(self, tmp_path):
        repo, docs = make_conf_repo(tmp_path, 'slug = "example/docs"\n')
        result = SlugCheck().run(repo, docs)
        assert result.passed
        assert "example/docs" in result.message

    def test_slug_missing(self, tmp_path):
        repo, docs = make_conf_repo(tmp_path, "project = 'x'\n")
        result = SlugCheck().run(repo, docs)
        assert not result.passed

    def test_no_docs_dir(self, tmp_path):
        result = SlugCheck().run(tmp_path, None)
        assert not result.passed


class TestBaseUrlCheck:
    def test_production_urls(self, tmp_path):
        conf = (
            "html_baseurl = 'https://canonical.com/example/docs/'\n"
            "ogp_site_url = 'https://canonical.com/example/docs/'\n"
        )
        repo, docs = make_conf_repo(tmp_path, conf)
        result = BaseUrlCheck().run(repo, docs)
        assert result.passed

    def test_fstring_production_url(self, tmp_path):
        conf = (
            "import os\n"
            "html_baseurl = f\"https://canonical.com/example/docs/{os.environ.get('V', 'local')}/\"\n"
        )
        repo, docs = make_conf_repo(tmp_path, conf)
        result = BaseUrlCheck().run(repo, docs)
        assert result.passed

    def test_rtd_url_fails(self, tmp_path):
        conf = "html_baseurl = 'https://example.readthedocs-hosted.com/'\n"
        repo, docs = make_conf_repo(tmp_path, conf)
        result = BaseUrlCheck().run(repo, docs)
        assert not result.passed

    def test_missing_urls(self, tmp_path):
        repo, docs = make_conf_repo(tmp_path, "project = 'x'\n")
        result = BaseUrlCheck().run(repo, docs)
        assert not result.passed


class TestSitemapConfigCheck:
    def test_correct_config(self, tmp_path):
        conf = (
            'sitemap_url_scheme = "{link}"\n'
            'sitemap_filename = "doc-sitemap.xml"\n'
        )
        repo, docs = make_conf_repo(tmp_path, conf)
        result = SitemapConfigCheck().run(repo, docs)
        assert result.passed

    def test_wrong_scheme(self, tmp_path):
        conf = 'sitemap_url_scheme = "{version}{link}"\nsitemap_filename = "doc-sitemap.xml"\n'
        repo, docs = make_conf_repo(tmp_path, conf)
        result = SitemapConfigCheck().run(repo, docs)
        assert not result.passed

    def test_missing_filename(self, tmp_path):
        conf = 'sitemap_url_scheme = "{link}"\n'
        repo, docs = make_conf_repo(tmp_path, conf)
        result = SitemapConfigCheck().run(repo, docs)
        assert not result.passed


class TestOverwriteLinksCheck:
    def test_registered_in_js_files(self, tmp_path):
        conf = 'html_js_files = ["js/overwrite_links.js"]\n'
        repo, docs = make_conf_repo(tmp_path, conf)
        result = OverwriteLinksCheck().run(repo, docs)
        assert result.passed

    def test_script_file_only(self, tmp_path):
        repo, docs = make_conf_repo(tmp_path, "project = 'x'\n")
        js_dir = docs / "_static" / "js"
        js_dir.mkdir(parents=True)
        (js_dir / "overwrite_links.js").write_text("// script\n")
        result = OverwriteLinksCheck().run(repo, docs)
        assert result.passed

    def test_completely_missing(self, tmp_path):
        repo, docs = make_conf_repo(tmp_path, "project = 'x'\n")
        result = OverwriteLinksCheck().run(repo, docs)
        assert not result.passed


def _site_ctx(base: str = "https://canonical.com/example/docs/") -> SiteContext:
    return SiteContext(
        base_url=base,
        llms_txt_url=base + "llms.txt",
        llms_txt_text="# docs\n- [A](https://canonical.com/example/docs/a/index.html.md)\n",
        pages=["https://canonical.com/example/docs/a/index.html.md"],
    )


class TestSitemapLiveCheck:
    def test_sitemap_present(self, stub_http):
        stub_http.mapping = {
            "doc-sitemap.xml": StubResponse(
                status_code=200,
                text="<urlset><url><loc>https://canonical.com/example/docs/a/</loc></url></urlset>",
            ),
        }
        result = SitemapLiveCheck().run(Path("."), None, _site_ctx())
        assert result.passed

    def test_sitemap_with_staging_urls(self, stub_http):
        stub_http.mapping = {
            "sitemap.xml": StubResponse(
                status_code=200,
                text="<urlset><url><loc>https://staging.canonical.com/example/docs/a/</loc></url></urlset>",
            ),
        }
        result = SitemapLiveCheck().run(Path("."), None, _site_ctx())
        assert not result.passed
        assert "staging" in result.message.lower()

    def test_no_sitemap(self, stub_http):
        result = SitemapLiveCheck().run(Path("."), None, _site_ctx())
        assert not result.passed

    def test_no_site_context(self):
        result = SitemapLiveCheck().run(Path("."), None, None)
        assert not result.passed


class TestCanonicalUrlCheck:
    def test_canonical_present(self, stub_http):
        stub_http.mapping = {
            "example/docs/a/": StubResponse(
                status_code=200,
                text='<html><head><link rel="canonical" href="https://canonical.com/example/docs/a/"></head></html>',
            ),
        }
        result = CanonicalUrlCheck().run(Path("."), None, _site_ctx())
        assert result.passed

    def test_canonical_missing(self, stub_http):
        stub_http.mapping = {
            "example/docs/a/": StubResponse(status_code=200, text="<html><head></head></html>"),
        }
        result = CanonicalUrlCheck().run(Path("."), None, _site_ctx())
        assert not result.passed


class TestNotFoundCheck:
    def test_real_404(self, stub_http):
        stub_http.mapping = {
            "invalid-page-should-404": StubResponse(status_code=404, text="not found"),
        }
        result = NotFoundCheck().run(Path("."), None, _site_ctx())
        assert result.passed

    def test_soft_404(self, stub_http):
        stub_http.mapping = {
            "invalid-page-should-404": StubResponse(status_code=200, text="<html>page</html>"),
        }
        result = NotFoundCheck().run(Path("."), None, _site_ctx())
        assert not result.passed
        assert "soft" in result.message.lower()


class TestAnalyticsCheck:
    def test_gtm_and_cookie_present(self, stub_http):
        stub_http.mapping = {
            "example/docs/a/": StubResponse(
                status_code=200,
                text='<html><head><script>gtm.js?id=GTM-KNX3CJC</script></head>'
                     '<body><div class="cookie-banner"></div></body></html>',
            ),
        }
        result = AnalyticsCheck().run(Path("."), None, _site_ctx())
        assert result.passed

    def test_missing_gtm(self, stub_http):
        stub_http.mapping = {
            "example/docs/a/": StubResponse(
                status_code=200, text='<html><body><div class="cookie"></div></body></html>'
            ),
        }
        result = AnalyticsCheck().run(Path("."), None, _site_ctx())
        assert not result.passed


class TestScanWithGroup:
    def test_scan_migration_group_offline(self, local_repo):
        from starter_pack_scanner.scanner import scan

        report = scan(local_repo, offline=True, check_group="migration")
        ids = {r.check_id for r in report.results}
        # Only repo-side migration checks run offline
        assert ids == {"migration-slug", "migration-baseurl",
                       "migration-sitemap-config", "migration-overwrite-links"}

    def test_scan_migration_group_with_site(self, local_repo, stub_http):
        from starter_pack_scanner.scanner import scan

        base = "https://canonical.com/example/docs/"
        stub_http.mapping = {
            base: StubResponse(status_code=200, url=base),
            "llms.txt": StubResponse(
                status_code=200,
                text=f"# docs\n- [A]({base}a/index.html.md)\n",
            ),
            "doc-sitemap.xml": StubResponse(
                status_code=200,
                text=f"<urlset><url><loc>{base}a/</loc></url></urlset>",
            ),
            "a/index.html.md": StubResponse(status_code=200, text="# A\n"),
            "a/": StubResponse(
                status_code=200,
                text='<html><head><link rel="canonical" href="' + base + 'a/">'
                     '<script>gtm.js?id=GTM-KNX3CJC</script></head>'
                     '<body><div class="cookie"></div></body></html>',
            ),
            "invalid-page-should-404": StubResponse(status_code=404),
        }
        report = scan(local_repo, check_group="migration")
        ids = {r.check_id for r in report.results}
        assert len(ids) == 8
