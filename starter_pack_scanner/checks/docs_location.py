"""Check: Are the docs in the standard docs/ directory?"""

from __future__ import annotations

from pathlib import Path

from starter_pack_scanner.checks.base import BaseCheck, CheckResult


class DocsLocationCheck(BaseCheck):
    @property
    def id(self) -> str:
        return "docs-location"

    @property
    def name(self) -> str:
        return "Docs Location"

    @property
    def description(self) -> str:
        return "Checks whether the documentation is located in the standard docs/ directory."

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
