"""Scanner checks: base class, result dataclass, and all check implementations."""

from __future__ import annotations

import abc
import re
from dataclasses import dataclass, field
from pathlib import Path

import requests


# ---------------------------------------------------------------------------
# Check infrastructure
# ---------------------------------------------------------------------------


@dataclass
class CheckResult:
    """Result of a single check."""

    check_id: str
    check_name: str
    passed: bool
    message: str
    details: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        lines = [f"[{status}] {self.check_name}: {self.message}"]
        for detail in self.details:
            lines.append(f"       {detail}")
        return "\n".join(lines)


class BaseCheck(abc.ABC):
    """Abstract base class for starter pack checks.

    To create a new check, define a class that inherits from BaseCheck with
    class attributes ``id``, ``name``, ``description`` and implement ``run``.
    Then add the class to ``ALL_CHECKS`` at the bottom of this file.
    """

    id: str
    name: str
    description: str

    @abc.abstractmethod
    def run(self, repo_root: Path, docs_dir: Path | None) -> CheckResult:
        """Run the check against a cloned repository."""


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_README_NAMES = ["README.md", "README.rst", "README.txt", "README"]


def _find_readme(repo_root: Path) -> Path | None:
    """Return the first README file found at repo root."""
    existing = {p.name.lower(): p for p in repo_root.iterdir() if p.is_file()}
    for name in _README_NAMES:
        found = existing.get(name.lower())
        if found:
            return found
    return None


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


class DocsLocationCheck(BaseCheck):
    id = "docs-dir"
    name = "Docs Directory"
    description = "Checks whether the documentation is in the standard docs/ directory of the repository."

    def run(self, repo_root: Path, docs_dir: Path | None) -> CheckResult:
        if docs_dir is None:
            return CheckResult(
                check_id=self.id,
                check_name=self.name,
                passed=False,
                message="No starter-pack documentation directory found in the repository.",
            )

        relative = docs_dir.relative_to(repo_root)
        if str(relative) == "docs":
            return CheckResult(
                check_id=self.id,
                check_name=self.name,
                passed=True,
                message="Documentation is in the standard docs/ directory.",
            )

        return CheckResult(
            check_id=self.id,
            check_name=self.name,
            passed=False,
            message=f"Documentation found at {relative}/ instead of the standard docs/ directory.",
        )


class VersionCheck(BaseCheck):
    id = "version"
    name = "Starter Pack Version"
    description = "Checks whether the starter pack version is the latest available."

    _LATEST_VERSION_URL = (
        "https://raw.githubusercontent.com/canonical/sphinx-stack/"
        "main/docs/_dev/version"
    )

    # Possible local paths for the version file (new location first).
    _VERSION_PATHS = ["_dev/version", ".sphinx/version"]

    def _fetch_latest_version(self) -> str | None:
        try:
            resp = requests.get(self._LATEST_VERSION_URL, timeout=10)
            resp.raise_for_status()
            return resp.text.strip()
        except requests.RequestException:
            return None

    def _find_version_file(self, docs_dir: Path) -> Path | None:
        for relative in self._VERSION_PATHS:
            candidate = docs_dir / relative
            if candidate.is_file():
                return candidate
        return None

    def run(self, repo_root: Path, docs_dir: Path | None) -> CheckResult:
        if docs_dir is None:
            return CheckResult(
                check_id=self.id,
                check_name=self.name,
                passed=False,
                message="No docs directory found; cannot check version.",
            )

        version_file = self._find_version_file(docs_dir)
        if version_file is None:
            return CheckResult(
                check_id=self.id,
                check_name=self.name,
                passed=False,
                message="No version file found — the starter pack may be very old (pre-1.0).",
                details=[f"Looked for: {', '.join(self._VERSION_PATHS)} under {docs_dir.relative_to(repo_root)}/"],
            )

        local_version = version_file.read_text().strip()
        if not local_version:
            return CheckResult(
                check_id=self.id,
                check_name=self.name,
                passed=False,
                message=f"The version file ({version_file.relative_to(repo_root)}) is empty.",
            )

        latest_version = self._fetch_latest_version()
        if latest_version is None:
            return CheckResult(
                check_id=self.id,
                check_name=self.name,
                passed=True,
                message=f"Local version is {local_version} (could not fetch latest version to compare).",
            )

        if local_version == latest_version:
            return CheckResult(
                check_id=self.id,
                check_name=self.name,
                passed=True,
                message=f"Starter pack is up to date (version {local_version}).",
            )

        return CheckResult(
            check_id=self.id,
            check_name=self.name,
            passed=False,
            message=f"Starter pack version {local_version} is outdated (latest: {latest_version}).",
        )


class ReadmeDocsLinkCheck(BaseCheck):
    id = "readme-docs-link"
    name = "README Docs Link"
    description = "Checks whether the repository README contains a link to the documentation."

    _DOCS_URL_PATTERNS = [
        re.compile(r"https?://[^\s\)\"'>]+\.readthedocs\.io\b", re.IGNORECASE),
        re.compile(r"https?://[^\s\)\"'>]+readthedocs-hosted\.com\b", re.IGNORECASE),
        re.compile(r"https?://[^\s\)\"'>]+/docs?\b", re.IGNORECASE),
        re.compile(r"https?://docs\.[^\s\)\"'>]+", re.IGNORECASE),
    ]

    def run(self, repo_root: Path, docs_dir: Path | None) -> CheckResult:
        readme = _find_readme(repo_root)
        if readme is None:
            return CheckResult(
                check_id=self.id,
                check_name=self.name,
                passed=False,
                message="No README file found in the repository root.",
            )

        try:
            content = readme.read_text(errors="replace")
        except OSError:
            return CheckResult(
                check_id=self.id,
                check_name=self.name,
                passed=False,
                message=f"Could not read {readme.name}.",
            )

        found_urls: list[str] = []
        for pattern in self._DOCS_URL_PATTERNS:
            found_urls.extend(pattern.findall(content))

        if found_urls:
            seen: set[str] = set()
            unique: list[str] = []
            for u in found_urls:
                if u not in seen:
                    seen.add(u)
                    unique.append(u)
            return CheckResult(
                check_id=self.id,
                check_name=self.name,
                passed=True,
                message=f"Found {len(unique)} documentation link(s) in {readme.name}.",
                details=[u for u in unique[:5]],
            )

        return CheckResult(
            check_id=self.id,
            check_name=self.name,
            passed=False,
            message=f"No documentation links found in {readme.name}.",
        )


class ReadmeRtdBadgeCheck(BaseCheck):
    id = "readme-rtd-badge"
    name = "README RTD Badge"
    description = "Checks whether the repository README contains a Read the Docs badge."

    _RTD_BADGE_PATTERNS = [
        re.compile(r"readthedocs\.org/projects/[^/]+/badge", re.IGNORECASE),
        re.compile(r"img\.shields\.io/readthedocs/", re.IGNORECASE),
        re.compile(r"badge.*readthedocs|readthedocs.*badge", re.IGNORECASE),
    ]

    def run(self, repo_root: Path, docs_dir: Path | None) -> CheckResult:
        readme = _find_readme(repo_root)
        if readme is None:
            return CheckResult(
                check_id=self.id,
                check_name=self.name,
                passed=False,
                message="No README file found in the repository root.",
            )

        try:
            content = readme.read_text(errors="replace")
        except OSError:
            return CheckResult(
                check_id=self.id,
                check_name=self.name,
                passed=False,
                message=f"Could not read {readme.name}.",
            )

        for pattern in self._RTD_BADGE_PATTERNS:
            if pattern.search(content):
                return CheckResult(
                    check_id=self.id,
                    check_name=self.name,
                    passed=True,
                    message=f"Read the Docs badge found in {readme.name}.",
                )

        return CheckResult(
            check_id=self.id,
            check_name=self.name,
            passed=False,
            message=f"No Read the Docs badge found in {readme.name}.",
        )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

ALL_CHECKS = [
    DocsLocationCheck,
    VersionCheck,
    ReadmeDocsLinkCheck,
    ReadmeRtdBadgeCheck,
]
