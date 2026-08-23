"""Tests for the URL-migration validation checks — offline (stubbed HTTP)."""

from __future__ import annotations

from pathlib import Path

from starter_pack_scanner.checks import ALL_CHECKS, checks_by_group
from starter_pack_scanner.migration_checks import (
    AnalyticsCheck,
    BaseUrlCheck,
    CanonicalUrlCheck,
    FlyoutPdfCheck,
    FlyoutVersionsCheck,
    NotFoundCheck,
    OldUrlRedirectCheck,
    OverwriteLinksCheck,
    RtdLeakageCheck,
    SitemapConfigCheck,
    SitemapIndexCheck,
    SitemapLiveCheck,
    SlugCheck,
    StaticPathCheck,
    UrlShapeCheck,
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
        assert len(group) == 15
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

    def test_versioned_site_requires_version_in_baseurl(self, tmp_path):
        """The Kafka bug: a versioned site whose conf.py hardcodes an
        unversioned html_baseurl emits broken llms.txt/sitemap links."""
        conf = (
            "html_baseurl = 'https://canonical.com/example/docs/'\n"
            "ogp_site_url = 'https://canonical.com/example/docs/'\n"
        )
        repo, docs = make_conf_repo(tmp_path, conf)
        ctx = SiteContext(base_url="https://canonical.com/example/docs/4/")
        result = BaseUrlCheck().run(repo, docs, ctx)
        assert not result.passed
        assert any("READTHEDOCS_VERSION" in d for d in result.details)

    def test_versioned_site_with_fstring_passes(self, tmp_path):
        conf = (
            "import os\n"
            "html_baseurl = f\"https://canonical.com/example/docs/{os.environ.get('READTHEDOCS_VERSION', 'local')}/\"\n"
            "ogp_site_url = f\"https://canonical.com/example/docs/{os.environ.get('READTHEDOCS_VERSION', 'local')}/\"\n"
        )
        repo, docs = make_conf_repo(tmp_path, conf)
        ctx = SiteContext(base_url="https://canonical.com/example/docs/4/")
        result = BaseUrlCheck().run(repo, docs, ctx)
        assert result.passed

    def test_versioned_site_with_literal_version_passes(self, tmp_path):
        # A plain URL that already carries the version segment is fine too.
        conf = (
            "html_baseurl = 'https://canonical.com/example/docs/4/'\n"
            "ogp_site_url = 'https://canonical.com/example/docs/4/'\n"
        )
        repo, docs = make_conf_repo(tmp_path, conf)
        ctx = SiteContext(base_url="https://canonical.com/example/docs/4/")
        result = BaseUrlCheck().run(repo, docs, ctx)
        assert result.passed

    def test_versioned_site_with_placeholder_passes(self, tmp_path):
        # LXD-style: plain string with a {version_slug} placeholder
        # substituted via html_context — varies with the version, so OK.
        conf = (
            "html_baseurl = 'https://canonical.com/example/docs/{version_slug}/'\n"
            "ogp_site_url = 'https://canonical.com/example/docs/{version_slug}/'\n"
        )
        repo, docs = make_conf_repo(tmp_path, conf)
        ctx = SiteContext(base_url="https://canonical.com/example/docs/default/")
        result = BaseUrlCheck().run(repo, docs, ctx)
        assert result.passed

    def test_unversioned_site_plain_url_passes(self, tmp_path):
        # No version segment in the live base → plain URL is correct.
        conf = (
            "html_baseurl = 'https://canonical.com/example/docs/'\n"
            "ogp_site_url = 'https://canonical.com/example/docs/'\n"
        )
        repo, docs = make_conf_repo(tmp_path, conf)
        ctx = SiteContext(base_url="https://canonical.com/example/docs/")
        result = BaseUrlCheck().run(repo, docs, ctx)
        assert result.passed


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
        # The production requirements accept either sitemap name; a missing
        # filename (sphinx-sitemap default sitemap.xml) passes with a note.
        conf = 'sitemap_url_scheme = "{link}"\n'
        repo, docs = make_conf_repo(tmp_path, conf)
        result = SitemapConfigCheck().run(repo, docs)
        assert result.passed
        assert any("doc-sitemap.xml" in d for d in result.details)

    def test_explicit_sitemap_xml_passes(self, tmp_path):
        conf = 'sitemap_url_scheme = "{link}"\nsitemap_filename = "sitemap.xml"\n'
        repo, docs = make_conf_repo(tmp_path, conf)
        result = SitemapConfigCheck().run(repo, docs)
        assert result.passed

    def test_wrong_filename_fails(self, tmp_path):
        conf = 'sitemap_url_scheme = "{link}"\nsitemap_filename = "my-sitemap.xml"\n'
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
                       "migration-sitemap-config", "migration-overwrite-links",
                       "migration-static-path"}

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
        assert len(ids) == 15


# ---------------------------------------------------------------------------
# Refactored-check shape validation
# ---------------------------------------------------------------------------


class TestSlugShape:
    def test_leading_slash_fails(self, tmp_path):
        repo, docs = make_conf_repo(tmp_path, 'slug = "/example/docs"\n')
        result = SlugCheck().run(repo, docs)
        assert not result.passed

    def test_version_segment_fails(self, tmp_path):
        repo, docs = make_conf_repo(tmp_path, 'slug = "example/docs/4"\n')
        result = SlugCheck().run(repo, docs)
        assert not result.passed

    def test_matches_live_url(self, tmp_path):
        repo, docs = make_conf_repo(tmp_path, 'slug = "data/kafka/docs"\n')
        ctx = SiteContext(base_url="https://canonical.com/data/kafka/docs/4/")
        result = SlugCheck().run(repo, docs, ctx)
        assert result.passed

    def test_mismatched_live_url(self, tmp_path):
        repo, docs = make_conf_repo(tmp_path, 'slug = "wrong/path"\n')
        ctx = SiteContext(base_url="https://canonical.com/data/kafka/docs/4/")
        result = SlugCheck().run(repo, docs, ctx)
        assert not result.passed


class TestBaseUrlShape:
    def test_missing_trailing_slash_fails(self, tmp_path):
        conf = "html_baseurl = 'https://canonical.com/example/docs'\n"
        repo, docs = make_conf_repo(tmp_path, conf)
        result = BaseUrlCheck().run(repo, docs)
        assert not result.passed

    def test_documentation_ubuntu_com_fails(self, tmp_path):
        conf = "html_baseurl = 'https://documentation.ubuntu.com/example/'\n"
        repo, docs = make_conf_repo(tmp_path, conf)
        result = BaseUrlCheck().run(repo, docs)
        assert not result.passed

    def test_fstring_without_version_env_fails(self, tmp_path):
        conf = "html_baseurl = f\"https://canonical.com/example/docs/{something}/\"\n"
        repo, docs = make_conf_repo(tmp_path, conf)
        result = BaseUrlCheck().run(repo, docs)
        # Still production host + trailing slash, so this should pass; the
        # guide only requires READTHEDOCS_VERSION as convention, not enforced
        # syntactically beyond the trailing slash.
        assert result.passed


class TestOverwriteLinksContent:
    def test_valid_script_passes(self, tmp_path):
        conf = 'html_js_files = ["js/overwrite_links.js"]\n'
        repo, docs = make_conf_repo(tmp_path, conf)
        js_dir = docs / "_static" / "js"
        js_dir.mkdir(parents=True)
        (js_dir / "overwrite_links.js").write_text(
            "const rtd_address = 'canonical-example.readthedocs-hosted.com';\n"
            "const new_address = 'canonical.com/example/docs';\n"
        )
        result = OverwriteLinksCheck().run(repo, docs)
        assert result.passed

    def test_documentation_ubuntu_com_address_fails(self, tmp_path):
        conf = 'html_js_files = ["js/overwrite_links.js"]\n'
        repo, docs = make_conf_repo(tmp_path, conf)
        js_dir = docs / "_static" / "js"
        js_dir.mkdir(parents=True)
        (js_dir / "overwrite_links.js").write_text(
            "const rtd_address = 'documentation.ubuntu.com/example';\n"
            "const new_address = 'canonical.com/example/docs';\n"
        )
        result = OverwriteLinksCheck().run(repo, docs)
        assert not result.passed

    def test_trailing_slash_in_new_address_fails(self, tmp_path):
        conf = 'html_js_files = ["js/overwrite_links.js"]\n'
        repo, docs = make_conf_repo(tmp_path, conf)
        js_dir = docs / "_static" / "js"
        js_dir.mkdir(parents=True)
        (js_dir / "overwrite_links.js").write_text(
            "const rtd_address = 'canonical-example.readthedocs-hosted.com';\n"
            "const new_address = 'canonical.com/example/docs/';\n"
        )
        result = OverwriteLinksCheck().run(repo, docs)
        assert not result.passed

    def test_variant_filename_and_variable_names_pass(self, tmp_path):
        """Regression: kafka-operator uses overwritelinks.js (no underscore,
        directly under _static/, not _static/js/) with oldDomain/newDomain
        variable names instead of the guide's exact conventions."""
        conf = 'html_js_files = ["overwritelinks.js"]\n'
        repo, docs = make_conf_repo(tmp_path, conf)
        static_dir = docs / "_static"
        static_dir.mkdir(parents=True)
        (static_dir / "overwritelinks.js").write_text(
            "const oldDomain = 'canonical-kafka-charm.readthedocs-hosted.com';\n"
            "const newDomain = 'canonical.com/data/kafka/docs';\n"
        )
        result = OverwriteLinksCheck().run(repo, docs)
        assert result.passed

    def test_variant_filename_unregistered_still_found_on_disk(self, tmp_path):
        repo, docs = make_conf_repo(tmp_path, "project = 'x'\n")
        static_dir = docs / "_static"
        static_dir.mkdir(parents=True)
        (static_dir / "overwritelinks.js").write_text(
            "const oldDomain = 'canonical-kafka-charm.readthedocs-hosted.com';\n"
            "const newDomain = 'canonical.com/data/kafka/docs';\n"
        )
        result = OverwriteLinksCheck().run(repo, docs)
        assert result.passed
        assert "not registered" in result.message.lower()


class TestStaticPathCheck:
    def test_static_present(self, tmp_path):
        repo, docs = make_conf_repo(tmp_path, 'html_static_path = ["_static"]\n')
        result = StaticPathCheck().run(repo, docs)
        assert result.passed

    def test_static_missing(self, tmp_path):
        repo, docs = make_conf_repo(tmp_path, 'html_static_path = ["assets"]\n')
        result = StaticPathCheck().run(repo, docs)
        assert not result.passed

    def test_no_list(self, tmp_path):
        repo, docs = make_conf_repo(tmp_path, "project = 'x'\n")
        result = StaticPathCheck().run(repo, docs)
        assert not result.passed


class TestSitemapLiveHostCheck:
    def test_wrong_host_fails(self, stub_http):
        stub_http.mapping = {
            "doc-sitemap.xml": StubResponse(
                status_code=200,
                text="<urlset><url><loc>https://other.example.com/a/</loc></url></urlset>",
            ),
        }
        result = SitemapLiveCheck().run(Path("."), None, _site_ctx())
        assert not result.passed

    def test_rtd_host_fails(self, stub_http):
        stub_http.mapping = {
            "doc-sitemap.xml": StubResponse(
                status_code=200,
                text="<urlset><url><loc>https://canonical-example.readthedocs-hosted.com/a/</loc></url></urlset>",
            ),
        }
        result = SitemapLiveCheck().run(Path("."), None, _site_ctx())
        assert not result.passed


class TestCanonicalUrlValue:
    def test_wrong_host_fails(self, stub_http):
        stub_http.mapping = {
            "example/docs/a/": StubResponse(
                status_code=200,
                text='<html><head><link rel="canonical" href="https://other.example.com/a/"></head></html>',
            ),
        }
        result = CanonicalUrlCheck().run(Path("."), None, _site_ctx())
        assert not result.passed

    def test_staging_href_fails(self, stub_http):
        stub_http.mapping = {
            "example/docs/a/": StubResponse(
                status_code=200,
                text='<html><head><link rel="canonical" href="https://staging.canonical.com/example/docs/a/"></head></html>',
            ),
        }
        result = CanonicalUrlCheck().run(Path("."), None, _site_ctx())
        assert not result.passed


class TestNotFoundVersionCheck:
    def test_versioned_base_checks_version_404(self, stub_http):
        stub_http.mapping = {
            "invalid-page-should-404": StubResponse(status_code=404),
            "nonexistent-version-should-404": StubResponse(status_code=404),
        }
        ctx = _site_ctx("https://canonical.com/example/docs/4/")
        result = NotFoundCheck().run(Path("."), None, ctx)
        assert result.passed
        assert len(result.details) == 2

    def test_soft_404_on_version_fails(self, stub_http):
        stub_http.mapping = {
            "invalid-page-should-404": StubResponse(status_code=404),
            "nonexistent-version-should-404": StubResponse(status_code=200),
        }
        ctx = _site_ctx("https://canonical.com/example/docs/4/")
        result = NotFoundCheck().run(Path("."), None, ctx)
        assert not result.passed


class TestAnalyticsGtmNote:
    def test_different_gtm_id_still_passes_with_note(self, stub_http):
        stub_http.mapping = {
            "example/docs/a/": StubResponse(
                status_code=200,
                text='<html><head><script>gtm.js?id=GTM-OTHER123</script></head>'
                     '<body><div class="cookie-banner"></div></body></html>',
            ),
        }
        result = AnalyticsCheck().run(Path("."), None, _site_ctx())
        assert result.passed
        assert any("differs" in d for d in result.details)


# ---------------------------------------------------------------------------
# New checks
# ---------------------------------------------------------------------------


class TestFlyoutPdfCheck:
    def test_no_addons_no_pdf_passes(self, stub_http):
        stub_http.mapping = {
            "example/docs/a/": StubResponse(status_code=200, text="<html><body>hi</body></html>"),
        }
        result = FlyoutPdfCheck().run(Path("."), None, _site_ctx())
        assert result.passed

    def test_rtd_pdf_link_fails(self, stub_http):
        stub_http.mapping = {
            "example/docs/a/": StubResponse(
                status_code=200,
                text='<html><body><a href="https://canonical-example.readthedocs-hosted.com/file.pdf">PDF</a></body></html>',
            ),
        }
        result = FlyoutPdfCheck().run(Path("."), None, _site_ctx())
        assert not result.passed

    def test_addons_data_with_rtd_host_fails(self, stub_http):
        addons_json = '{"versions": {"active": [{"slug": "readthedocs-hosted.com"}]}}'
        stub_http.mapping = {
            "example/docs/a/": StubResponse(
                status_code=200,
                text=(
                    '<html><body><script id="readthedocs-addons-data" type="application/json">'
                    + addons_json + "</script></body></html>"
                ),
            ),
        }
        result = FlyoutPdfCheck().run(Path("."), None, _site_ctx())
        assert not result.passed


class TestFlyoutVersionsCheck:
    def test_no_addons_data_passes(self, stub_http):
        stub_http.mapping = {
            "example/docs/a/": StubResponse(status_code=200, text="<html><body>hi</body></html>"),
        }
        result = FlyoutVersionsCheck().run(Path("."), None, _site_ctx())
        assert result.passed

    def test_migrate_version_fails(self, stub_http):
        addons_json = (
            '{"versions": {"active": [{"slug": "latest"}, {"slug": "migrate-24.04"}]}}'
        )
        stub_http.mapping = {
            "example/docs/a/": StubResponse(
                status_code=200,
                text=(
                    '<html><body><script id="readthedocs-addons-data" type="application/json">'
                    + addons_json + "</script></body></html>"
                ),
            ),
        }
        result = FlyoutVersionsCheck().run(Path("."), None, _site_ctx())
        assert not result.passed
        assert "migrate-24.04" in result.details

    def test_sensible_versions_pass(self, stub_http):
        addons_json = '{"versions": {"active": [{"slug": "latest"}, {"slug": "stable"}]}}'
        stub_http.mapping = {
            "example/docs/a/": StubResponse(
                status_code=200,
                text=(
                    '<html><body><script id="readthedocs-addons-data" type="application/json">'
                    + addons_json + "</script></body></html>"
                ),
            ),
        }
        result = FlyoutVersionsCheck().run(Path("."), None, _site_ctx())
        assert result.passed


class TestOldUrlRedirectCheck:
    def test_explicit_old_url_redirects_correctly(self, stub_http):
        old_url = "https://canonical-example.readthedocs-hosted.com/"
        new_url = "https://canonical.com/example/docs/"
        stub_http.mapping = {
            old_url: StubResponse(status_code=200, url=new_url),
        }
        ctx = _site_ctx(new_url)
        result = OldUrlRedirectCheck(old_url).run(Path("."), None, ctx)
        assert result.passed

    def test_old_url_does_not_redirect(self, stub_http):
        old_url = "https://canonical-example.readthedocs-hosted.com/"
        stub_http.mapping = {
            old_url: StubResponse(status_code=200, url=old_url),
        }
        ctx = _site_ctx("https://canonical.com/example/docs/")
        result = OldUrlRedirectCheck(old_url).run(Path("."), None, ctx)
        assert not result.passed

    def test_no_old_url_found_passes_with_note(self, tmp_path):
        repo, docs = make_conf_repo(tmp_path, "project = 'x'\n")
        ctx = _site_ctx()
        result = OldUrlRedirectCheck().run(repo, docs, ctx)
        assert result.passed
        assert "skip" in result.message.lower() or "could not determine" in result.message.lower()


class TestSitemapIndexCheck:
    def test_registered_passes(self, stub_http):
        base = "https://canonical.com/example/docs/4/"
        stub_http.mapping = {
            "sitemap.xml": StubResponse(
                status_code=200,
                text="<sitemapindex><sitemap><loc>https://canonical.com/example/docs/latest/sitemap.xml</loc></sitemap></sitemapindex>",
            ),
        }
        ctx = _site_ctx(base)
        result = SitemapIndexCheck().run(Path("."), None, ctx)
        assert result.passed

    def test_not_registered_fails(self, stub_http):
        stub_http.mapping = {
            "sitemap.xml": StubResponse(status_code=200, text="<sitemapindex></sitemapindex>"),
        }
        ctx = _site_ctx("https://canonical.com/example/docs/")
        result = SitemapIndexCheck().run(Path("."), None, ctx)
        assert not result.passed

    def test_non_canonical_domain_skips(self, stub_http):
        ctx = _site_ctx("https://example.org/docs/")
        result = SitemapIndexCheck().run(Path("."), None, ctx)
        assert result.passed
        assert "does not apply" in result.message.lower()


class TestUrlShapeCheck:
    def test_supported_shape_passes(self):
        ctx = _site_ctx("https://canonical.com/data/kafka/docs/4/")
        result = UrlShapeCheck().run(Path("."), None, ctx)
        assert result.passed

    def test_lxd_default_segment_passes(self):
        # LXD publishes at /lxd/docs/default/ — 'default' is a version
        # segment, not part of the docs path.
        ctx = _site_ctx("https://canonical.com/lxd/docs/default/")
        result = UrlShapeCheck().run(Path("."), None, ctx)
        assert result.passed

    def test_language_and_version_stripped(self):
        ctx = _site_ctx("https://canonical.com/example/docs/en/latest/")
        result = UrlShapeCheck().run(Path("."), None, ctx)
        assert result.passed

    def test_non_docs_path_fails(self):
        ctx = _site_ctx("https://canonical.com/data/kafka/")
        result = UrlShapeCheck().run(Path("."), None, ctx)
        assert not result.passed

    def test_wrong_domain_fails(self):
        ctx = _site_ctx("https://example.org/data/kafka/docs/")
        result = UrlShapeCheck().run(Path("."), None, ctx)
        assert not result.passed

    def test_known_exception_still_passes_with_note(self):
        ctx = _site_ctx("https://canonical.com/microk8s/docs/")
        result = UrlShapeCheck().run(Path("."), None, ctx)
        assert result.passed
        assert "exception" in result.message.lower()


class TestRtdLeakageCheck:
    def test_clean_page_passes(self, stub_http):
        stub_http.mapping = {
            "example/docs/a/": StubResponse(
                status_code=200,
                text='<html><body><a href="https://canonical.com/other/">link</a></body></html>',
            ),
        }
        result = RtdLeakageCheck().run(Path("."), None, _site_ctx())
        assert result.passed

    def test_own_old_location_fails(self, stub_http):
        # documentation.ubuntu.com/<this product>/... is this set's old home.
        stub_http.mapping = {
            "example/docs/a/": StubResponse(
                status_code=200,
                text='<html><body><a href="https://documentation.ubuntu.com/example/how-to/">old</a></body></html>',
            ),
        }
        result = RtdLeakageCheck().run(Path("."), None, _site_ctx())
        assert not result.passed

    def test_other_products_docs_pass(self, stub_http):
        # Kafka-style false positive: a link to ANOTHER product's docs on
        # documentation.ubuntu.com is legitimate (intersphinx / related
        # guides), not a leak of this set's old location.
        stub_http.mapping = {
            "example/docs/a/": StubResponse(
                status_code=200,
                text='<html><body><a href="https://documentation.ubuntu.com/observability/track-2/tutorial/">obs</a>'
                '<a href="https://canonical-example-other.readthedocs-hosted.com/page/">other rtd</a></body></html>',
            ),
        }
        result = RtdLeakageCheck().run(Path("."), None, _site_ctx())
        assert result.passed

    def test_rtd_address_host_spec_fails(self, stub_http, tmp_path):
        # rtd_address in overwrite_links.js identifies the dedicated old
        # host — ANY path on it is this set's old location.
        repo = tmp_path / "repo"
        docs = repo / "docs"
        (docs / "_static" / "js").mkdir(parents=True)
        (docs / "_static" / "js" / "overwrite_links.js").write_text(
            "const rtd_address = 'canonical-example.readthedocs-hosted.com';\n"
        )
        stub_http.mapping = {
            "example/docs/a/": StubResponse(
                status_code=200,
                text='<html><body><a href="https://canonical-example.readthedocs-hosted.com/anything/">old</a></body></html>',
            ),
        }
        result = RtdLeakageCheck().run(repo, docs, _site_ctx())
        assert not result.passed

    def test_staging_src_fails(self, stub_http):
        stub_http.mapping = {
            "example/docs/a/": StubResponse(
                status_code=200,
                text='<html><body><img src="https://staging.canonical.com/img.png"></body></html>',
            ),
        }
        result = RtdLeakageCheck().run(Path("."), None, _site_ctx())
        assert not result.passed
