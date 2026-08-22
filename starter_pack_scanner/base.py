"""Shared check infrastructure: CheckResult and BaseCheck.

Kept in a dedicated module so that check modules (checks.py,
migration_checks.py, ...) can import the base classes without circular
imports.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from pathlib import Path

from starter_pack_scanner.site import SiteContext


@dataclass
class CheckResult:
    """Result of a single check."""

    check_id: str
    check_name: str
    passed: bool
    message: str
    details: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Plain-dict form, JSON-serialisable (used by the cache and web UI)."""
        return {
            "check_id": self.check_id,
            "check_name": self.check_name,
            "passed": self.passed,
            "message": self.message,
            "details": list(self.details),
        }

    @classmethod
    def from_dict(cls, data: dict) -> CheckResult:
        return cls(
            check_id=data["check_id"],
            check_name=data["check_name"],
            passed=data["passed"],
            message=data["message"],
            details=list(data.get("details", [])),
        )

    def __str__(self) -> str:
        from starter_pack_scanner.checks import _BOLD, _GREEN, _RED, _c

        if self.passed:
            status = _c("PASS", _GREEN, _BOLD)
        else:
            status = _c("FAIL", _RED, _BOLD)
        lines = [f"[{status}] {self.check_name}: {self.message}"]
        for detail in self.details:
            lines.append(f"       {detail}")
        return "\n".join(lines)


class BaseCheck(abc.ABC):
    """Abstract base class for starter pack checks.

    To create a new check, define a class that inherits from BaseCheck with
    class attributes ``id``, ``name``, ``description`` and implement ``run``.
    Then add the class to ``ALL_CHECKS`` in ``checks.py``.

    Optional class attributes:

    - ``requires_site``: True if the check needs the published-site context
      (network access); the scanner then builds a SiteContext.
    - ``group``: check group name (e.g. "migration"); used to run only a
      subset of checks via ``--group`` / ``check_group``.
    """

    id: str
    name: str
    description: str
    requires_site: bool = False
    group: str | None = None

    @abc.abstractmethod
    def run(self, repo_root: Path, docs_dir: Path | None, site_ctx: SiteContext | None = None) -> CheckResult:
        """Run the check against a cloned repository."""
