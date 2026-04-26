"""Check: Does the repo README have a Read the Docs badge?"""

from __future__ import annotations

import re
from pathlib import Path

from starter_pack_scanner.checks.base import BaseCheck, CheckResult

_README_NAMES = ["README.md", "README.rst", "README.txt", "README"]

# Patterns matching Read the Docs badge images/shields.
_RTD_BADGE_PATTERNS = [
    # shields.io style: ![badge](https://readthedocs.org/projects/NAME/badge/...)
    re.compile(r"readthedocs\.org/projects/[^/]+/badge", re.IGNORECASE),
    # img.shields.io/readthedocs style
    re.compile(r"img\.shields\.io/readthedocs/", re.IGNORECASE),
    # Any image tag referencing readthedocs badge
    re.compile(r"badge.*readthedocs|readthedocs.*badge", re.IGNORECASE),
]


def _find_readme(repo_root: Path) -> Path | None:
    existing = {p.name.lower(): p for p in repo_root.iterdir() if p.is_file()}
    for name in _README_NAMES:
        found = existing.get(name.lower())
        if found:
            return found
    return None


class ReadmeRtdBadgeCheck(BaseCheck):
    @property
    def id(self) -> str:
        return "readme-rtd-badge"

    @property
    def name(self) -> str:
        return "README RTD Badge"

    @property
    def description(self) -> str:
        return "Checks whether the repository README contains a Read the Docs badge."

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

        for pattern in _RTD_BADGE_PATTERNS:
            match = pattern.search(content)
            if match:
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
