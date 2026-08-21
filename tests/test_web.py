"""Tests for the web GUI — FastAPI TestClient, fully offline.

Scan requests are pointed at local git fixtures; the HTTP layer is stubbed.
"""

from __future__ import annotations

import pytest

fastapi_testclient = pytest.importorskip("fastapi.testclient")

from starter_pack_scanner.web.app import app  # noqa: E402


@pytest.fixture()
def client(monkeypatch, local_repo, stub_http):
    """TestClient with validation allowing only the local fixture URL."""
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        yield c


class TestIndex:
    def test_index_renders(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "Starter Pack Scanner" in resp.text
        assert 'name="repo_url"' in resp.text
        assert 'name="docs_url"' in resp.text
        assert 'name="branch"' in resp.text  # inside collapsed Advanced section

    def test_static_assets_served(self, client):
        assert client.get("/static/style.css").status_code == 200
        assert client.get("/static/theme.js").status_code == 200


class TestScanEndpoint:
    def test_scan_renders_report(self, client):
        resp = client.post(
            "/scan",
            data={"repo_url": "https://github.com/canonical/kafka-operator"},
        )
        # The URL is valid but not clonable in tests — either a report or a
        # friendly error card must come back, never a 500.
        assert resp.status_code == 200
        assert "Scan failed" in resp.text or "Scan report" in resp.text

    def test_empty_url_shows_error(self, client):
        resp = client.post("/scan", data={"repo_url": ""})
        assert resp.status_code == 200
        assert "Scan failed" in resp.text
        assert "enter a repository URL" in resp.text

    def test_invalid_url_shows_error(self, client):
        resp = client.post("/scan", data={"repo_url": "file:///etc/passwd"})
        assert resp.status_code == 200
        assert "Scan failed" in resp.text
        assert "scheme" in resp.text

    def test_private_ip_url_shows_error(self, client):
        resp = client.post("/scan", data={"repo_url": "https://169.254.169.254/x"})
        assert resp.status_code == 200
        assert "Scan failed" in resp.text

    def test_bad_docs_url_shows_error(self, client):
        resp = client.post(
            "/scan",
            data={"repo_url": "https://github.com/canonical/x", "docs_url": "ftp://bad"},
        )
        assert resp.status_code == 200
        assert "Scan failed" in resp.text
        assert "docs URL" in resp.text


class TestScanCaching:
    def test_second_scan_is_cached(self, client, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        from starter_pack_scanner import cache
        from starter_pack_scanner.scanner import ScanReport
        from starter_pack_scanner.checks import CheckResult
        from datetime import datetime, timezone

        repo = "https://github.com/canonical/cached-repo"
        key = cache.cache_key(repo_url=repo)
        fake = ScanReport(
            repo_url=repo,
            scanned_at=datetime(2026, 8, 21, 10, 0, tzinfo=timezone.utc),
            results=[
                CheckResult(check_id="t", check_name="T", passed=True, message="ok")
            ],
        )
        cache.put(key, fake)

        resp = client.post("/scan", data={"repo_url": repo})
        assert resp.status_code == 200
        assert "badge-cached" in resp.text
        assert "2026-08-21 10:00" in resp.text

    def test_refresh_bypasses_cache(self, client, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        from starter_pack_scanner import cache
        from starter_pack_scanner.scanner import ScanReport
        from starter_pack_scanner.checks import CheckResult
        from datetime import datetime, timezone

        repo = "https://github.com/canonical/cached-repo"
        key = cache.cache_key(repo_url=repo)
        fake = ScanReport(
            repo_url=repo,
            scanned_at=datetime(2026, 8, 21, 10, 0, tzinfo=timezone.utc),
            results=[],
        )
        cache.put(key, fake)

        resp = client.post("/scan", data={"repo_url": repo, "refresh": "true"})
        assert resp.status_code == 200
        # The cached (empty) report is not served: a fresh scan ran instead.
        assert "badge-cached" not in resp.text
