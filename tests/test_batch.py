"""Tests for batch scanning (YAML loading, validation, execution) — offline."""

from __future__ import annotations

import textwrap

import pytest

from starter_pack_scanner.batch import BatchEntry, BatchFileError, load_batch, run_batch


def write_batch(tmp_path, content: str) -> object:
    path = tmp_path / "batch.yml"
    path.write_text(textwrap.dedent(content))
    return path


class TestLoadBatch:
    def test_valid_full_format(self, tmp_path):
        path = write_batch(tmp_path, """
            defaults:
              branch: main
              offline: true

            repos:
              - repo: https://github.com/canonical/kafka-operator
                docs_url: https://canonical.com/data/kafka/docs/
              - repo: https://github.com/canonical/opensearch-operator
            """)
        entries = load_batch(path)
        assert len(entries) == 2
        assert entries[0].repo == "https://github.com/canonical/kafka-operator"
        assert entries[0].branch == "main"
        assert entries[0].docs_url == "https://canonical.com/data/kafka/docs/"
        assert entries[0].offline is True
        # Per-entry override of defaults
        assert entries[1].branch == "main"

    def test_plain_url_shorthand(self, tmp_path):
        path = write_batch(tmp_path, """
            repos:
              - https://github.com/canonical/valkey-operator
            """)
        entries = load_batch(path)
        assert entries[0].repo == "https://github.com/canonical/valkey-operator"
        assert entries[0].branch is None

    def test_check_group(self, tmp_path):
        path = write_batch(tmp_path, """
            repos:
              - repo: https://github.com/canonical/cassandra-operator
                check_group: migration
            """)
        entries = load_batch(path)
        assert entries[0].check_group == "migration"

    def test_example_batch_file_valid(self):
        """The example batch-scan.yml shipped in the repo root must load."""
        import pathlib

        example = pathlib.Path(__file__).parent.parent / "batch-scan.yml"
        entries = load_batch(example)
        repos = {e.repo for e in entries}
        assert "https://github.com/canonical/kafka-operator" in repos
        assert "https://github.com/canonical/opensearch-operator" in repos
        assert "https://github.com/canonical/valkey-operator" in repos
        assert "https://github.com/canonical/cassandra-operator" in repos
        assert any(e.check_group == "migration" for e in entries)

    def test_example_batch_constant_valid(self, tmp_path):
        """The EXAMPLE_BATCH_YAML constant (GUI placeholder/fallback) must load."""
        from starter_pack_scanner.batch import EXAMPLE_BATCH_YAML

        path = tmp_path / "example.yml"
        path.write_text(EXAMPLE_BATCH_YAML)
        entries = load_batch(path)
        assert len(entries) == 4
        assert any(e.check_group == "migration" for e in entries)

    def test_example_batch_constant_has_no_comments(self):
        """The GUI placeholder example is comment-free (per design)."""
        from starter_pack_scanner.batch import EXAMPLE_BATCH_YAML

        assert "#" not in EXAMPLE_BATCH_YAML

    # --- validation errors ---

    def test_missing_file(self, tmp_path):
        with pytest.raises(BatchFileError, match="Could not read"):
            load_batch(tmp_path / "nope.yml")

    def test_invalid_yaml(self, tmp_path):
        path = tmp_path / "batch.yml"
        path.write_text("repos: [unclosed")
        with pytest.raises(BatchFileError, match="Invalid YAML"):
            load_batch(path)

    def test_empty_file(self, tmp_path):
        path = write_batch(tmp_path, "")
        with pytest.raises(BatchFileError, match="empty"):
            load_batch(path)

    def test_no_repos_key(self, tmp_path):
        path = write_batch(tmp_path, "defaults: {}\n")
        with pytest.raises(BatchFileError, match="no 'repos'"):
            load_batch(path)

    def test_empty_repos_list(self, tmp_path):
        path = write_batch(tmp_path, "repos: []\n")
        with pytest.raises(BatchFileError, match="empty"):
            load_batch(path)

    def test_entry_missing_repo(self, tmp_path):
        path = write_batch(tmp_path, """
            repos:
              - branch: main
            """)
        with pytest.raises(BatchFileError, match="missing a 'repo'"):
            load_batch(path)

    def test_entry_bad_url_scheme(self, tmp_path):
        path = write_batch(tmp_path, """
            repos:
              - repo: ftp://example.com/repo
            """)
        with pytest.raises(BatchFileError, match="https://"):
            load_batch(path)

    def test_unknown_entry_key(self, tmp_path):
        path = write_batch(tmp_path, """
            repos:
              - repo: https://github.com/canonical/x
                bogus_key: 1
            """)
        with pytest.raises(BatchFileError, match="Unknown keys"):
            load_batch(path)

    def test_unknown_defaults_key(self, tmp_path):
        path = write_batch(tmp_path, """
            defaults:
              bogus: 1
            repos:
              - repo: https://github.com/canonical/x
            """)
        with pytest.raises(BatchFileError, match="Unknown keys in 'defaults'"):
            load_batch(path)

    def test_unknown_check_group(self, tmp_path):
        path = write_batch(tmp_path, """
            repos:
              - repo: https://github.com/canonical/x
                check_group: nonexistent
            """)
        with pytest.raises(BatchFileError, match="unknown check_group"):
            load_batch(path)

    def test_non_bool_offline(self, tmp_path):
        path = write_batch(tmp_path, """
            repos:
              - repo: https://github.com/canonical/x
                offline: "yes please"
            """)
        with pytest.raises(BatchFileError, match="'offline' must be a boolean"):
            load_batch(path)


class TestShortName:
    def test_operator_suffix_stripped(self):
        entry = BatchEntry(repo="https://github.com/canonical/kafka-operator")
        assert entry.short_name == "kafka"

    def test_plain_repo_name(self):
        entry = BatchEntry(repo="https://github.com/canonical/sphinx-stack")
        assert entry.short_name == "sphinx-stack"

    def test_git_suffix_stripped(self):
        entry = BatchEntry(repo="https://github.com/canonical/example.git")
        assert entry.short_name == "example"

    def test_docs_suffix_stripped(self):
        entry = BatchEntry(repo="https://github.com/canonical/example-docs")
        assert entry.short_name == "example"

    def test_fallback_for_bare_url(self):
        entry = BatchEntry(repo="https://example.com")
        assert entry.short_name  # non-empty, exact value not important


class TestRunBatch:
    def test_run_batch_offline(self, tmp_path, monkeypatch, local_repo):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
        entries = [
            BatchEntry(repo=local_repo, offline=True),
        ]
        results = run_batch(entries)
        assert len(results) == 1
        entry, report = results[0]
        assert entry.repo == local_repo
        assert report.error is None
        assert len(report.results) > 0

    def test_run_batch_uses_cache(self, tmp_path, monkeypatch, local_repo):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
        entries = [BatchEntry(repo=local_repo, offline=True)]
        # First run populates the cache; second run must not re-scan.
        run_batch(entries)
        # Corrupt the cache entry's timestamp to detect a cache hit.
        from starter_pack_scanner import cache

        key = cache.cache_key(repo_url=local_repo, offline=True)
        report = cache.get(key)
        report.scanned_at = report.scanned_at.replace(year=2000)
        cache.put(key, report)

        results = run_batch(entries)
        assert results[0][1].scanned_at.year == 2000  # served from cache

    def test_run_batch_refresh_bypasses_cache(self, tmp_path, monkeypatch, local_repo):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
        entries = [BatchEntry(repo=local_repo, offline=True)]
        run_batch(entries)
        results = run_batch(entries, refresh=True)
        assert results[0][1].scanned_at.year != 2000

    def test_run_batch_invalid_repo(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
        entries = [BatchEntry(repo="file:///etc/passwd")]
        results = run_batch(entries)
        _, report = results[0]
        assert report.error is not None
