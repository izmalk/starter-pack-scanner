"""Check: Does the repo README link to the documentation?"""

from __future__ import annotations

import re
from pathlib import Path

from starter_pack_scanner.checks.base import BaseCheck, CheckResult

# Common README filenames (case-insensitive match).
_README_NAMES = ["README.md", "README.rst", "README.txt", "README"]

# Patterns that look like documentation URLs.
# Covers readthedocs-hosted, custom RTD, and common doc hosting patterns.
_DOCS_URL_PATTERNS = [
    re.compile(r"https?://[^\s\)\"'>]+\.readthedocs\.io\b", re.IGNORECASE),
    re.compile(r"https?://[^\s\)\"'>]+readthedocs-hosted\.com\b", re.IGNORECASE),
    re.compile(r"https?://[^\s\)\"'>]+/docs?\b", re.IGNORECASE),
    re.compile(r"https?://docs\.[^\s\)\"'>]+", re.IGNORECASE),
]


def _find_readme(repo_root: Path) -> Path | None:
    """Return the first README file found at repo root."""
    existing = {p.name.lower(): p for p in repo_root.iterdir() if p.is_file()}
    for name in _README_NAMES:
        found = existing.get(name.lower())
        if found:
            return found
    return None


class ReadmeDocsLinkCheck(BaseCheck):
    @property
    def id(self) -> str:
        return "readme-docs-link"

    @property
    def name(self) -> str:
        return "README Docs Link"

    @property
    def description(self) -> str:
        return "Checks whether the repository README contains a link to the documentation."

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
        for pattern in _DOCS_URL_PATTERNS:
            found_urls.extend(pattern.findall(content))

        if found_urls:
            # De-duplicate while preserving order
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
