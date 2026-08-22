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

# Recommendation length budget. The soft limit is a style guideline; the hard
# limit is enforced by the test suite so recommendations stay scannable.
RECOMMENDATION_SOFT_LIMIT = 300
RECOMMENDATION_HARD_LIMIT = 500

# Contextual recommendations for the shared "cannot run" results below. These
# override the check's own recommendation, because the actionable fix is about
# the scan setup rather than the thing the check would have verified.
_SITE_UNAVAILABLE_RECOMMENDATION = (
    "Pass the published docs URL explicitly with "
    "`--docs-url https://canonical.com/<product>/docs/`, or set `html_baseurl` "
    "(or `ogp_site_url`) in `conf.py` to a reachable production URL. "
    "Use `--offline` to skip all live-site checks."
)

_NO_PAGES_RECOMMENDATION = (
    "Page sampling needs `llms.txt` or `sitemap.xml` at the docs root. Add "
    "`sphinx_sitemap` (and optionally `sphinx_llm.txt`) to `extensions` in "
    "`conf.py`, and confirm the sitemap is enabled in the Read the Docs "
    "project settings."
)


def site_unavailable(check: "BaseCheck", site_ctx: SiteContext | None) -> CheckResult:
    """Standard failure result when the published-site context is missing."""
    details = list(site_ctx.errors) if site_ctx else []
    return CheckResult(
        check_id=check.id,
        check_name=check.name,
        passed=False,
        message="Could not resolve the published documentation URL; cannot run this check.",
        details=details or ["Pass --docs-url to specify the published documentation base URL."],
        recommendation=_SITE_UNAVAILABLE_RECOMMENDATION,
    )


def no_pages(check: "BaseCheck", site_ctx: SiteContext) -> CheckResult:
    """Standard failure result when no pages could be sampled."""
    return CheckResult(
        check_id=check.id,
        check_name=check.name,
        passed=False,
        message="No documentation pages could be sampled (llms.txt and sitemap.xml unavailable or empty).",
        details=site_ctx.errors,
        recommendation=_NO_PAGES_RECOMMENDATION,
    )


@dataclass
class CheckResult:
    """Result of a single check.

    ``recommendation`` holds free-form guidance on how to fix a failure. It is
    normally inherited from the check class (see ``BaseCheck.recommendation``)
    and stamped on by ``BaseCheck.execute()``; individual results may set their
    own when the actionable fix differs from the check's general advice.
    """

    check_id: str
    check_name: str
    passed: bool
    message: str
    details: list[str] = field(default_factory=list)
    recommendation: str = ""

    def to_dict(self) -> dict:
        """Plain-dict form, JSON-serialisable (used by the cache and web UI)."""
        return {
            "check_id": self.check_id,
            "check_name": self.check_name,
            "passed": self.passed,
            "message": self.message,
            "details": list(self.details),
            "recommendation": self.recommendation,
        }

    @classmethod
    def from_dict(cls, data: dict) -> CheckResult:
        # 'recommendation' is optional so that reports cached by older
        # versions of the scanner still deserialise.
        return cls(
            check_id=data["check_id"],
            check_name=data["check_name"],
            passed=data["passed"],
            message=data["message"],
            details=list(data.get("details", [])),
            recommendation=data.get("recommendation", ""),
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
        if not self.passed and self.recommendation and _show_recommendations():
            lines.append(f"       {_c('Fix:', _BOLD)} {self.recommendation}")
        return "\n".join(lines)


# Module-level toggle for the CLI's --no-recommendations flag. Kept here (not
# passed through every call) because __str__ is invoked deep inside report
# printing; the CLI sets it once at startup.
_SHOW_RECOMMENDATIONS = True


def set_show_recommendations(enabled: bool) -> None:
    """Control whether CheckResult.__str__ prints the 'Fix:' block."""
    global _SHOW_RECOMMENDATIONS
    _SHOW_RECOMMENDATIONS = enabled


def _show_recommendations() -> bool:
    return _SHOW_RECOMMENDATIONS


class BaseCheck(abc.ABC):
    """Abstract base class for starter pack checks.

    To create a new check, define a class that inherits from BaseCheck with
    class attributes ``id``, ``name``, ``description``, ``recommendation``
    and implement ``run``. Then add the class to ``ALL_CHECKS`` in
    ``checks.py``.

    Optional class attributes:

    - ``requires_site``: True if the check needs the published-site context
      (network access); the scanner then builds a SiteContext.
    - ``group``: check group name (e.g. "migration"); used to run only a
      subset of checks via ``--group`` / ``check_group``.

    ``recommendation`` is free-form guidance shown to the user when the check
    fails ("How to fix this?"). Keep it under
    ``RECOMMENDATION_SOFT_LIMIT`` characters where possible; the test suite
    enforces ``RECOMMENDATION_HARD_LIMIT``. Plain text with bare URLs and
    ``-``/``1.`` list lines renders correctly in both the CLI and the web GUI.
    """

    id: str
    name: str
    description: str
    recommendation: str = ""
    requires_site: bool = False
    group: str | None = None

    @abc.abstractmethod
    def run(self, repo_root: Path, docs_dir: Path | None, site_ctx: SiteContext | None = None) -> CheckResult:
        """Run the check against a cloned repository."""

    def execute(
        self, repo_root: Path, docs_dir: Path | None, site_ctx: SiteContext | None = None
    ) -> CheckResult:
        """Run the check and stamp the class recommendation onto the result.

        Callers (the scanner) should use this rather than ``run()`` directly,
        so that every result carries its fix guidance. A result that already
        set its own ``recommendation`` keeps it.
        """
        result = self.run(repo_root, docs_dir, site_ctx)
        if not result.recommendation:
            result.recommendation = self.recommendation
        return result
