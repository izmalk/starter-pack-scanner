"""Unit tests for site.py helpers — pure functions, no network."""

from __future__ import annotations

from starter_pack_scanner import site


class TestParseLlmsTxt:
    def test_extracts_markdown_links(self):
        text = "# Title\n\n- [A](https://x.com/a)\n- [B](https://x.com/b)\n"
        assert site.parse_llms_txt(text) == ["https://x.com/a", "https://x.com/b"]

    def test_empty(self):
        assert site.parse_llms_txt("# nothing here") == []


class TestSamplePages:
    def test_short_list_returned_as_is(self):
        urls = ["a", "b"]
        assert site.sample_pages(urls, n=3) == ["a", "b"]

    def test_deduplicates(self):
        urls = ["a", "a", "b"]
        assert site.sample_pages(urls, n=3) == ["a", "b"]

    def test_seed_reproducible(self):
        urls = [f"https://x.com/p{i}" for i in range(20)]
        first = site.sample_pages(urls, n=3, seed=42)
        second = site.sample_pages(urls, n=3, seed=42)
        assert first == second
        assert len(first) == 3


class TestUrlHelpers:
    def test_to_page_url(self):
        assert site.to_page_url("https://x.com/t/index.html.md") == "https://x.com/t/"
        assert site.to_page_url("https://x.com/t/index.html") == "https://x.com/t/"
        assert site.to_page_url("https://x.com/t/") == "https://x.com/t/"

    def test_to_markdown_url(self):
        assert site.to_markdown_url("https://x.com/t/") == "https://x.com/t/index.html.md"
        assert site.to_markdown_url("https://x.com/t") == "https://x.com/t/index.html.md"


class TestIsMajorDomain:
    def test_canonical(self):
        assert site.is_major_domain("https://canonical.com/x/")

    def test_ubuntu(self):
        assert site.is_major_domain("https://ubuntu.com/server/docs")

    def test_subdomain(self):
        assert site.is_major_domain("https://lxd.canonical.com/docs")

    def test_rtd_rejected(self):
        assert not site.is_major_domain("https://example.readthedocs.io/")

    def test_unknown_rejected(self):
        assert not site.is_major_domain("https://example.com/docs")

    def test_extra_domains(self):
        assert not site.is_major_domain("https://docs.example.org/")
        assert site.is_major_domain("https://docs.example.org/", {"example.org"})


class TestConfValue:
    def test_plain_string(self):
        assert site._conf_value("html_baseurl = 'https://x.com/'\n", "html_baseurl") == "https://x.com/"

    def test_double_quotes(self):
        assert site._conf_value('html_baseurl = "https://x.com/"\n', "html_baseurl") == "https://x.com/"

    def test_fstring_returns_none(self):
        assert site._conf_value("html_baseurl = f'https://x.com/{ver}'\n", "html_baseurl") is None

    def test_missing_key(self):
        assert site._conf_value("other = 'x'\n", "html_baseurl") is None
