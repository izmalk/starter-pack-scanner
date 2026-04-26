"""Core scanner logic: clone repo, detect docs, run checks."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from starter_pack_scanner.checks import ALL_CHECKS
from starter_pack_scanner.checks.base import BaseCheck, CheckResult

# Directories to search for starter-pack indicators, in priority order.
_CANDIDATE_DIRS = ["docs", "."]

# Signals that a directory is a starter-pack docs root (checked in order).
# .sphinx/ is the strongest signal; conf.py alone is generic Sphinx.
_SP_MARKERS = [".sphinx"]
_SPHINX_MARKERS = ["conf.py"]

# Repo-root file that hints at RTD-based docs even when docs dir is elsewhere.
_RTD_CONFIG = ".readthedocs.yaml"


def _is_starter_pack_dir(path: Path) -> bool:
    """Return True if *path* looks like a starter-pack docs root."""
    return any((path / m).exists() for m in _SP_MARKERS)


def _is_sphinx_dir(path: Path) -> bool:
    """Return True if *path* contains a Sphinx conf.py."""
    return (path / "conf.py").is_file()


def _find_docs_dir(repo_root: Path) -> Path | None:
    """Locate the starter-pack docs directory inside a cloned repo.

    Detection strategy (in priority order):
    1. Check ``docs/`` and repo root for a ``.sphinx/`` directory.
    2. Search one level deep for any dir containing ``.sphinx/``.
    3. If a ``.readthedocs.yaml`` exists at the repo root, parse it for
       a custom ``sphinx.configuration`` path pointing to conf.py, and
       derive the docs directory from that.
    4. Fall back to ``docs/`` or repo root if they contain ``conf.py``.
    5. Search one level deep for any dir containing ``conf.py``.
    """
    # --- pass 1: strong signal (.sphinx/) in priority dirs ---
    for candidate in _CANDIDATE_DIRS:
        path = repo_root / candidate
        if _is_starter_pack_dir(path):
            return path

    # --- pass 2: strong signal one level deep ---
    for child in sorted(repo_root.iterdir()):
        if child.is_dir() and not child.name.startswith(".") and _is_starter_pack_dir(child):
            return child

    # --- pass 3: .readthedocs.yaml may point to the docs dir ---
    rtd_path = repo_root / _RTD_CONFIG
    if not rtd_path.exists():
        # Also check the legacy filename without leading dot
        rtd_path = repo_root / "readthedocs.yaml"
    if rtd_path.exists():
        docs_dir = _docs_dir_from_rtd_config(repo_root, rtd_path)
        if docs_dir is not None:
            return docs_dir

    # --- pass 4: weaker signal (conf.py) in priority dirs ---
    for candidate in _CANDIDATE_DIRS:
        path = repo_root / candidate
        if _is_sphinx_dir(path):
            return path

    # --- pass 5: weaker signal one level deep ---
    for child in sorted(repo_root.iterdir()):
        if child.is_dir() and not child.name.startswith(".") and _is_sphinx_dir(child):
            return child

    return None


def _docs_dir_from_rtd_config(repo_root: Path, rtd_path: Path) -> Path | None:
    """Try to extract the docs directory from a .readthedocs.yaml file."""
    try:
        text = rtd_path.read_text()
    except OSError:
        return None

    # Lightweight YAML parsing — look for sphinx.configuration value
    # to avoid adding a PyYAML dependency.
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("configuration:"):
            value = stripped.split(":", 1)[1].strip().strip("\"'")
            if value:
                conf_path = repo_root / value
                if conf_path.exists():
                    return conf_path.parent
                # Even if the file doesn't exist, the parent dir may
                candidate = conf_path.parent
                if candidate.is_dir():
                    return candidate
    return None


def clone_repo(repo_url: str, dest: Path, branch: str | None = None) -> None:
    """Shallow-clone a repository."""
    cmd = ["git", "clone", "--depth", "1"]
    if branch:
        cmd += ["--branch", branch]
    cmd += ["--", repo_url, str(dest)]
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def scan(
    repo_url: str,
    branch: str | None = None,
    exclude_checks: set[str] | None = None,
    include_checks: set[str] | None = None,
) -> list[CheckResult]:
    """Clone a repo and run all enabled checks.

    Args:
        repo_url: Git-cloneable repository URL.
        branch: Optional branch/tag to check out.
        exclude_checks: Set of check IDs to skip.
        include_checks: If set, only run checks whose IDs are in this set.

    Returns:
        A list of CheckResult objects.
    """
    exclude_checks = exclude_checks or set()
    tmp_dir = tempfile.mkdtemp(prefix="sp-scanner-")
    repo_root = Path(tmp_dir) / "repo"

    try:
        clone_repo(repo_url, repo_root, branch)
        docs_dir = _find_docs_dir(repo_root)

        results: list[CheckResult] = []
        for check_cls in ALL_CHECKS:
            check: BaseCheck = check_cls()
            if check.id in exclude_checks:
                continue
            if include_checks and check.id not in include_checks:
                continue
            results.append(check.run(repo_root, docs_dir))

        return results
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
