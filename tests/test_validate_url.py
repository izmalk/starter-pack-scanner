"""Tests for URL validation (SSRF guard) — pure offline unit tests."""

from __future__ import annotations

import pytest

from starter_pack_scanner.scanner import validate_repo_url


class TestScheme:
    def test_https_accepted(self):
        assert validate_repo_url("https://github.com/canonical/kafka-operator") is None

    def test_http_localhost_accepted(self):
        assert validate_repo_url("http://localhost/repo.git") is None

    def test_http_remote_rejected(self):
        assert validate_repo_url("http://example.com/repo.git") is not None

    @pytest.mark.parametrize(
        "url",
        [
            "file:///etc/passwd",
            "ssh://git@github.com/canonical/kafka-operator",
            "git://github.com/canonical/kafka-operator",
            "ftp://example.com/repo.git",
        ],
    )
    def test_other_schemes_rejected(self, url):
        assert validate_repo_url(url) is not None

    def test_no_scheme_rejected(self):
        assert validate_repo_url("github.com/canonical/kafka-operator") is not None


class TestCredentials:
    def test_embedded_credentials_rejected(self):
        assert validate_repo_url("https://user:pass@github.com/repo") is not None

    def test_username_only_rejected(self):
        assert validate_repo_url("https://user@github.com/repo") is not None


class TestPrivateAddresses:
    @pytest.mark.parametrize(
        "url",
        [
            "https://127.0.0.1/repo.git",
            "https://10.0.0.5/repo.git",
            "https://192.168.1.10/repo.git",
            "https://169.254.169.254/latest/meta-data",  # cloud metadata endpoint
            "https://[::1]/repo.git",
        ],
    )
    def test_private_ip_rejected(self, url):
        assert validate_repo_url(url) is not None

    def test_private_hostname_rejected(self, monkeypatch):
        import starter_pack_scanner.scanner as scanner_mod

        monkeypatch.setattr(
            scanner_mod,
            "_resolve_all_ips",
            lambda host: [__import__("ipaddress").ip_address("10.1.2.3")],
        )
        assert validate_repo_url("https://internal.example.com/repo.git") is not None

    def test_public_hostname_accepted(self, monkeypatch):
        import starter_pack_scanner.scanner as scanner_mod

        monkeypatch.setattr(
            scanner_mod,
            "_resolve_all_ips",
            lambda host: [__import__("ipaddress").ip_address("93.184.216.34")],
        )
        assert validate_repo_url("https://example.com/repo.git") is None
