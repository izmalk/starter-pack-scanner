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

    def test_failed_check_shows_collapsed_fix_toggle(self, client, monkeypatch, tmp_path, local_repo):
        """Failed checks render a collapsed 'How to fix this?' <details>;
        passing checks render no toggle."""
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        # The web app imports validate_repo_url into its own namespace, so
        # patch it there too (the local_repo fixture only patches scanner's).
        import starter_pack_scanner.web.app as web_app

        monkeypatch.setattr(web_app, "validate_repo_url", lambda u: None)
        resp = client.post("/scan", data={"repo_url": local_repo, "offline": "true"})
        assert resp.status_code == 200
        assert "Scan report" in resp.text
        # The local fixture fails several repo-side checks (no slug, no
        # sitemap config, ...), so at least one toggle must be present.
        assert "How to fix this?" in resp.text
        assert '<details class="check-fix">' in resp.text
        # Collapsed by default: no 'open' attribute on the details element.
        assert '<details class="check-fix" open' not in resp.text
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


class TestProgressModal:
    """HTMX requests get the async job flow: modal shell → polls → results."""

    def _wait_for_done(self, client, job_id, tries: int = 100):
        import time

        for _ in range(tries):
            resp = client.get(f"/progress/{job_id}")
            if 'id="progress-done"' in resp.text:
                return resp
            time.sleep(0.05)
        raise AssertionError("job never finished")

    def _job_id_from(self, text: str) -> str:
        import re

        m = re.search(r"/progress/([0-9a-f]+)", text)
        assert m, "no job id in modal response"
        return m.group(1)

    def test_htmx_scan_returns_modal_then_results(self, client, monkeypatch, tmp_path, local_repo):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        import starter_pack_scanner.web.app as web_app

        monkeypatch.setattr(web_app, "validate_repo_url", lambda u: None)
        resp = client.post(
            "/scan",
            data={"repo_url": local_repo},
            headers={"HX-Request": "true"},
        )
        assert resp.status_code == 200
        # The modal shell with the retro window and the polling div.
        assert 'id="progress-modal"' in resp.text
        assert "retro-screen" in resp.text
        assert 'id="progress-poll"' in resp.text
        assert "hx-get" in resp.text

        job_id = self._job_id_from(resp.text)
        final = self._wait_for_done(client, job_id)
        assert 'data-status="ok"' in final.text
        # The final payload carries the rendered report.
        assert "Scan report" in final.text

    def test_htmx_batch_returns_modal_then_results(self, client, monkeypatch, tmp_path, local_repo):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        resp = client.post(
            "/batch",
            data={"batch_yaml": f"repos:\n  - {local_repo}\n"},
            headers={"HX-Request": "true"},
        )
        assert resp.status_code == 200
        assert 'id="progress-modal"' in resp.text
        assert "Batch scanning" in resp.text

        job_id = self._job_id_from(resp.text)
        final = self._wait_for_done(client, job_id)
        assert 'data-status="ok"' in final.text
        assert "Batch scan report" in final.text

    def test_progress_unknown_job(self, client):
        resp = client.get("/progress/does-not-exist")
        assert resp.status_code == 200
        assert 'data-status="gone"' in resp.text

    def test_progress_bar_partial_while_running(self, client, monkeypatch):
        """While a job runs, the poll returns the bar partial, not results."""
        import starter_pack_scanner.web.app as web_app

        job_id = web_app._new_job()
        web_app._job_update(job_id, 42, "Running check 5/26")
        try:
            resp = client.get(f"/progress/{job_id}")
            assert resp.status_code == 200
            assert 'aria-valuenow="42"' in resp.text
            assert "Running check 5/26" in resp.text
            assert "progress-done" not in resp.text
        finally:
            web_app._job_pop(job_id)

    def test_job_removed_after_collection(self, client, monkeypatch):
        import starter_pack_scanner.web.app as web_app

        job_id = web_app._new_job()
        web_app._job_finish(job_id, "<p>results</p>")
        resp = client.get(f"/progress/{job_id}")
        assert 'data-status="ok"' in resp.text
        # Second poll: the job is gone.
        resp2 = client.get(f"/progress/{job_id}")
        assert 'data-status="gone"' in resp2.text

    def test_scan_progress_callback_fires(self, client, monkeypatch, tmp_path, local_repo):
        """The scanner's progress callback drives the job's percent/step."""
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        import starter_pack_scanner.web.app as web_app

        monkeypatch.setattr(web_app, "validate_repo_url", lambda u: None)
        events: list[tuple[int, str]] = []
        original_scan = web_app.scan

        def spying_scan(*args, **kwargs):
            progress = kwargs.get("progress")

            def spy(pct: int, step: str) -> None:
                events.append((pct, step))
                if progress:
                    progress(pct, step)

            kwargs["progress"] = spy
            return original_scan(*args, **kwargs)

        monkeypatch.setattr(web_app, "scan", spying_scan)
        resp = client.post(
            "/scan",
            data={"repo_url": local_repo},
            headers={"HX-Request": "true"},
        )
        job_id = self._job_id_from(resp.text)
        self._wait_for_done(client, job_id)
        # Milestones were reported: cloning, checks, completion.
        steps = [s for _, s in events]
        assert any("Cloning" in s for s in steps)
        assert any("Running check" in s for s in steps)
        assert events[-1][0] == 100


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
