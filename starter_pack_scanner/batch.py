"""Batch scanning: run the scanner over a list of repositories from a YAML file.

File format (see ``batch-scan.yml`` in the repository root for an example):

.. code-block:: yaml

    # Optional defaults applied to every entry (each can be overridden):
    defaults:
      branch: main
      docs_url: null
      check_group: null
      offline: false
      exclude_checks: []
      include_checks: []

    repos:
      - repo: https://github.com/canonical/kafka-operator
        docs_url: https://canonical.com/data/kafka/docs/
      - repo: https://github.com/canonical/opensearch-operator
        branch: main
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import yaml

from starter_pack_scanner.scanner import ProgressFn, ScanReport, scan


class BatchFileError(Exception):
    """Raised when a batch file is invalid (syntax or semantics)."""


# Example batch content: used as the placeholder in the web GUI and as the
# fallback when the batch field is submitted empty. Keep in sync with
# batch-scan.yml in the repository root (tests assert both stay valid).
EXAMPLE_BATCH_YAML = """\
repos:
  - repo: https://github.com/canonical/kafka-operator
    docs_url: https://canonical.com/data/kafka/docs/

  - repo: https://github.com/canonical/opensearch-operator
    docs_url: https://canonical.com/data/opensearch/docs/

  - repo: https://github.com/canonical/valkey-operator
    docs_url: https://canonical.com/data/valkey/docs/

  - repo: https://github.com/canonical/cassandra-operator
    docs_url: https://canonical.com/data/cassandra/docs/
    check_group: migration
"""


@dataclass
class BatchEntry:
    """One repository to scan, with its scan options."""

    repo: str
    branch: str | None = None
    docs_url: str | None = None
    check_group: str | None = None
    offline: bool = False
    exclude_checks: set[str] = field(default_factory=set)
    include_checks: set[str] | None = None
    old_url: str | None = None
    rtd_project: str | None = None

    @property
    def short_name(self) -> str:
        """Short display name inferred from the repo URL.

        e.g. https://github.com/canonical/kafka-operator → "kafka"
        """
        from urllib.parse import urlparse

        path = urlparse(self.repo).path.strip("/")
        name = path.rsplit("/", 1)[-1] if path else self.repo
        for suffix in ("-operator", "-docs", "-documentation", ".git"):
            if name.endswith(suffix) and len(name) > len(suffix):
                name = name[: -len(suffix)]
                break
        return name

    def to_dict(self) -> dict:
        return {
            "repo": self.repo,
            "branch": self.branch,
            "docs_url": self.docs_url,
            "check_group": self.check_group,
            "offline": self.offline,
            "exclude_checks": sorted(self.exclude_checks),
            "include_checks": sorted(self.include_checks) if self.include_checks else None,
            "old_url": self.old_url,
            "rtd_project": self.rtd_project,
        }


# Keys allowed in an entry (besides "repo").
_ENTRY_KEYS = {"repo", "branch", "docs_url", "check_group", "offline",
               "exclude_checks", "include_checks", "old_url", "rtd_project"}
_DEFAULTS_KEYS = _ENTRY_KEYS - {"repo"}


def load_batch(path: Path | str) -> list[BatchEntry]:
    """Load and validate a batch file. Raises BatchFileError on problems."""
    path = Path(path)
    try:
        text = path.read_text()
    except OSError as exc:
        raise BatchFileError(f"Could not read batch file {path}: {exc}") from exc

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise BatchFileError(f"Invalid YAML in {path}: {exc}") from exc

    if data is None:
        raise BatchFileError(f"Batch file {path} is empty.")
    if not isinstance(data, dict):
        raise BatchFileError(
            f"Batch file {path} must be a mapping with a 'repos' key, "
            f"got {type(data).__name__}."
        )

    defaults = data.get("defaults") or {}
    if not isinstance(defaults, dict):
        raise BatchFileError("'defaults' must be a mapping.")
    unknown = set(defaults) - _DEFAULTS_KEYS
    if unknown:
        raise BatchFileError(f"Unknown keys in 'defaults': {sorted(unknown)}.")

    repos = data.get("repos")
    if repos is None:
        raise BatchFileError(f"Batch file {path} has no 'repos' list.")
    if not isinstance(repos, list):
        raise BatchFileError("'repos' must be a list.")
    if not repos:
        raise BatchFileError("'repos' list is empty.")

    entries: list[BatchEntry] = []
    for i, item in enumerate(repos):
        entries.append(_parse_entry(item, i, defaults))
    return entries


def _parse_entry(item: object, index: int, defaults: dict) -> BatchEntry:
    """Parse and validate one entry of the 'repos' list."""
    where = f"repos[{index}]"
    if isinstance(item, str):
        # Shorthand: a bare URL string.
        item = {"repo": item}
    if not isinstance(item, dict):
        raise BatchFileError(
            f"{where} must be a mapping (or a plain URL string), "
            f"got {type(item).__name__}."
        )

    unknown = set(item) - _ENTRY_KEYS
    if unknown:
        raise BatchFileError(f"Unknown keys in {where}: {sorted(unknown)}.")

    repo = item.get("repo")
    if not repo or not isinstance(repo, str):
        raise BatchFileError(f"{where} is missing a 'repo' URL.")
    repo = repo.strip()
    if not repo.startswith(("https://", "http://", "file://")):
        raise BatchFileError(
            f"{where}: repo URL must start with https:// (or http:// for localhost)."
        )

    merged = {**defaults, **{k: v for k, v in item.items() if k != "repo"}}

    branch = merged.get("branch")
    if branch is not None and not isinstance(branch, str):
        raise BatchFileError(f"{where}: 'branch' must be a string.")

    docs_url = merged.get("docs_url")
    if docs_url is not None and not isinstance(docs_url, str):
        raise BatchFileError(f"{where}: 'docs_url' must be a string.")

    check_group = merged.get("check_group")
    if check_group is not None and not isinstance(check_group, str):
        raise BatchFileError(f"{where}: 'check_group' must be a string.")
    if check_group is not None:
        from starter_pack_scanner.checks import ALL_CHECKS

        valid = {getattr(c, "group", None) for c in ALL_CHECKS} - {None}
        if check_group not in valid:
            raise BatchFileError(
                f"{where}: unknown check_group {check_group!r} (available: {sorted(valid)})."
            )

    offline = merged.get("offline", False)
    if not isinstance(offline, bool):
        raise BatchFileError(f"{where}: 'offline' must be a boolean.")

    exclude = merged.get("exclude_checks") or []
    if not isinstance(exclude, list) or not all(isinstance(e, str) for e in exclude):
        raise BatchFileError(f"{where}: 'exclude_checks' must be a list of check IDs.")
    include = merged.get("include_checks")
    if include is not None:
        if not isinstance(include, list) or not all(isinstance(e, str) for e in include):
            raise BatchFileError(f"{where}: 'include_checks' must be a list of check IDs.")

    old_url = merged.get("old_url")
    if old_url is not None and not isinstance(old_url, str):
        raise BatchFileError(f"{where}: 'old_url' must be a string.")

    rtd_project = merged.get("rtd_project")
    if rtd_project is not None and not isinstance(rtd_project, str):
        raise BatchFileError(f"{where}: 'rtd_project' must be a string.")

    return BatchEntry(
        repo=repo,
        branch=branch,
        docs_url=docs_url,
        check_group=check_group,
        offline=offline,
        exclude_checks=set(exclude),
        include_checks=set(include) if include is not None else None,
        old_url=old_url,
        rtd_project=rtd_project,
    )


def run_batch(
    entries: list[BatchEntry],
    use_cache: bool = True,
    refresh: bool = False,
    progress: ProgressFn | None = None,
) -> list[tuple[BatchEntry, ScanReport]]:
    """Run the scanner for every entry. Returns (entry, report) pairs.

    ``progress`` (optional) is called with (percent, step) as the batch
    advances; per-repo scan milestones are scaled into the repo's slice.
    """
    from starter_pack_scanner import cache
    from starter_pack_scanner.checks import checks_by_group

    results: list[tuple[BatchEntry, ScanReport]] = []
    total = len(entries)
    for index, entry in enumerate(entries):
        repo_start = 100 * index // total
        repo_end = 100 * (index + 1) // total
        repo_span = repo_end - repo_start

        def scaled(pct: int, step: str, _s: int = repo_start, _span: int = repo_span, _e: str = entry.short_name) -> None:
            if progress is not None:
                progress(_s + _span * pct // 100, f"[{_e}] {step}")

        # Fold the check group into the cache key via its include set, so
        # group-filtered scans don't collide with full scans (same pattern
        # as cli.py and web/app.py).
        include_ids = entry.include_checks
        if entry.check_group:
            group_ids = {c().id for c in checks_by_group(entry.check_group)}
            include_ids = (include_ids or set()) | group_ids
        key = cache.cache_key(
            repo_url=entry.repo,
            branch=entry.branch,
            docs_url=entry.docs_url,
            include_checks=include_ids,
            exclude_checks=entry.exclude_checks,
            offline=entry.offline,
            old_url=entry.old_url,
            rtd_project=entry.rtd_project,
        )
        report = None
        if use_cache and not refresh:
            report = cache.get(key)
        if report is None:
            report = scan(
                repo_url=entry.repo,
                branch=entry.branch,
                exclude_checks=entry.exclude_checks,
                include_checks=entry.include_checks,
                docs_url=entry.docs_url,
                check_group=entry.check_group,
                offline=entry.offline,
                old_url=entry.old_url,
                rtd_project=entry.rtd_project,
                progress=scaled,
            )
            cache.put(key, report)
        else:
            scaled(100, "served from cache")
        results.append((entry, report))
    if progress is not None:
        progress(100, "Batch scan complete")
    return results
