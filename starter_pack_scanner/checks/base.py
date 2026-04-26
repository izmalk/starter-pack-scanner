"""Base class for all scanner checks."""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from pathlib import Path


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

    To create a new check:
    1. Create a new file in the checks/ directory.
    2. Define a class that inherits from BaseCheck.
    3. Implement the `id`, `name`, `description` properties and the `run` method.
    4. Register the class in checks/__init__.py by adding it to ALL_CHECKS.
    """

    @property
    @abc.abstractmethod
    def id(self) -> str:
        """Short unique identifier for the check (e.g. 'docs-location')."""

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Human-readable name of the check."""

    @property
    @abc.abstractmethod
    def description(self) -> str:
        """One-line description of what this check verifies."""

    @abc.abstractmethod
    def run(self, repo_root: Path, docs_dir: Path | None) -> CheckResult:
        """Run the check against a cloned repository.

        Args:
            repo_root: Path to the root of the cloned repository.
            docs_dir: Path to the detected docs directory, or None if not found.

        Returns:
            A CheckResult with the outcome.
        """
