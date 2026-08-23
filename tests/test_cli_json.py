"""Tests for the CLI's --json output mode — offline, using local fixtures."""

from __future__ import annotations

import json

import pytest

from starter_pack_scanner.cli import main


class TestJsonOutput:
    def test_json_report_is_valid_and_parseable(self, local_repo, monkeypatch, tmp_path, capsys):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        with pytest.raises(SystemExit) as exc:
            main([local_repo, "--json", "--offline"])
        # Local fixture fails some repo-side checks → exit 1.
        assert exc.value.code == 1

        out = capsys.readouterr().out
        # stdout must be pure JSON — no progress lines before it.
        assert not out.startswith("Scanning")
        data = json.loads(out)
        assert data["repo_url"] == local_repo
        assert data["docs_dir"] == "docs"
        assert isinstance(data["results"], list) and data["results"]

    def test_json_contains_recommendations(self, local_repo, monkeypatch, tmp_path, capsys):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        with pytest.raises(SystemExit):
            main([local_repo, "--json", "--offline"])
        data = json.loads(capsys.readouterr().out)
        failed = [r for r in data["results"] if not r["passed"]]
        assert failed, "fixture should have failures"
        # Every failed check carries its fix guidance.
        assert all(r.get("recommendation") for r in failed)

    def test_json_all_pass_exits_zero(self, local_repo, monkeypatch, tmp_path, capsys):
        """With only the passing checks selected, --json exits 0."""
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        with pytest.raises(SystemExit) as exc:
            main([local_repo, "--json", "--offline", "--check", "docs-dir"])
        assert exc.value.code == 0
        data = json.loads(capsys.readouterr().out)
        assert len(data["results"]) == 1
        assert data["results"][0]["passed"] is True

    def test_json_error_report(self, capsys):
        """Scan-level errors also emit JSON (exit 2)."""
        with pytest.raises(SystemExit) as exc:
            main(["file:///etc/passwd", "--json"])
        assert exc.value.code == 2
        data = json.loads(capsys.readouterr().out)
        assert data["error"]
        assert data["results"] == []
