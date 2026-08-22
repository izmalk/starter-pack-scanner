"""Tests for the web GUI — FastAPI TestClient, fully offline.

Scan requests are pointed at local git fixtures; the HTTP layer is stubbed.
"""

from __future__ import annotations

import pytest


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
        assert client.get("/static/localtime.js").status_code == 200

    def test_batch_tab_has_example_placeholder(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        # The example batch is rendered as the textarea placeholder.
        assert 'placeholder="' in resp.text
        assert "canonical/kafka-operator" in resp.text
        assert "canonical/cassandra-operator" in resp.text
        assert "Batch scan" in resp.text
        # Help line with Vanilla's information icon + tooltip + inline error element.
        assert "p-icon--information" in resp.text
        assert "tooltip" in resp.text
        assert 'id="batch-yaml-error"' in resp.text
        # Client-side validation script is referenced.
        assert "batch-validate.js" in resp.text


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


class TestBatchEndpoint:
    def _yaml(self, repo: str) -> str:
        return f"repos:\n  - {repo}\n"

    def test_empty_yaml_runs_example(self, client, monkeypatch, tmp_path):
        # An empty field means "run the example" — it must not error.
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        from starter_pack_scanner.batch import EXAMPLE_BATCH_YAML

        # Point the example repos at an invalid URL so the scan is fast
        # and deterministic (validation error, no network clone attempt).
        monkeypatch.setattr(
            "starter_pack_scanner.web.app.EXAMPLE_BATCH_YAML",
            "repos:\n  - file:///etc/passwd\n",
        )
        resp = client.post("/batch", data={"batch_yaml": ""})
        assert resp.status_code == 200
        assert "Batch scan report" in resp.text
        assert "Error" in resp.text  # the example entry failed validation
        assert EXAMPLE_BATCH_YAML  # the real example is non-empty

    def test_invalid_yaml_shows_error(self, client):
        resp = client.post("/batch", data={"batch_yaml": "repos: [unclosed"})
        assert resp.status_code == 200
        assert "Batch scan failed" in resp.text
        assert "Invalid YAML" in resp.text

    def test_unknown_key_shows_error(self, client):
        bad = "repos:\n  - repo: https://github.com/canonical/x\n    bogus: 1\n"
        resp = client.post("/batch", data={"batch_yaml": bad})
        assert resp.status_code == 200
        assert "Unknown keys" in resp.text

    def test_batch_with_invalid_repo_renders(self, client):
        resp = client.post("/batch", data={"batch_yaml": self._yaml("file:///etc/passwd")})
        assert resp.status_code == 200
        assert "Batch scan report" in resp.text
        assert "Error" in resp.text

    def test_batch_with_local_repo_renders(self, client, monkeypatch, tmp_path, local_repo):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        resp = client.post("/batch", data={"batch_yaml": self._yaml(local_repo)})
        assert resp.status_code == 200
        assert "Batch scan report" in resp.text
        assert "1 repositor" in resp.text

    def test_batch_results_have_tabs_and_rescan(self, client, monkeypatch, tmp_path, local_repo):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        yaml_input = (
            f"repos:\n  - {local_repo}\n"
            "  - repo: https://github.com/canonical/not-a-real-repo-xyz\n"
        )
        resp = client.post("/batch", data={"batch_yaml": yaml_input})
        assert resp.status_code == 200
        # Tabbed results (Vanilla p-tabs pattern): one tab per docs set.
        assert 'class="p-tabs__list"' in resp.text
        assert 'role="tab"' in resp.text
        assert "data-batch-panel" in resp.text
        assert 'role="tabpanel"' in resp.text
        # Per-tab and global re-scan buttons.
        assert resp.text.count("Re-scan all") == 1
        assert "Re-scan" in resp.text

    def test_batch_tab_short_names(self, client, monkeypatch, tmp_path, local_repo):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        yaml_input = f"repos:\n  - {local_repo}\n"
        resp = client.post("/batch", data={"batch_yaml": yaml_input})
        # The tab shows the URL-derived short name (repo dir, suffix stripped).
        assert "batch-tab-count" in resp.text


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
        # UTC fallback text is rendered; the browser converts to local time.
        assert "2026-08-21 10:00 UTC" in resp.text
        assert f'datetime="{fake.scanned_at.isoformat()}"' in resp.text

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
