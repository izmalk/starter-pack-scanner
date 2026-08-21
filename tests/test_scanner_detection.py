"""Tests for docs-dir detection heuristics — local fixtures, offline."""

from __future__ import annotations

from starter_pack_scanner.scanner import _find_docs_dir
from tests.conftest import make_repo


class TestFindDocsDir:
    def test_standard_docs(self, tmp_path):
        repo = make_repo(tmp_path)
        assert _find_docs_dir(repo) == repo / "docs"

    def test_sphinx_at_root(self, tmp_path):
        repo = make_repo(tmp_path, docs_dir=".")
        assert _find_docs_dir(repo) == repo

    def test_sphinx_in_subdirectory(self, tmp_path):
        repo = make_repo(tmp_path, docs_dir="documentation")
        assert _find_docs_dir(repo) == repo / "documentation"

    def test_conf_py_only_fallback(self, tmp_path):
        # No .sphinx marker, but conf.py in docs/ — weaker signal still works
        repo = make_repo(tmp_path, starter_pack=False)
        assert _find_docs_dir(repo) == repo / "docs"

    def test_no_docs_at_all(self, tmp_path):
        repo = make_repo(tmp_path, docs_dir=None)
        assert _find_docs_dir(repo) is None

    def test_rtd_config_points_to_docs(self, tmp_path):
        repo = make_repo(tmp_path, docs_dir="src/docs")
        (repo / ".readthedocs.yaml").write_text(
            "sphinx:\n  configuration: src/docs/conf.py\n"
        )
        assert _find_docs_dir(repo) == repo / "src" / "docs"
