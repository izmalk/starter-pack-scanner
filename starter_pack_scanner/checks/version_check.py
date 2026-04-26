"""Check: Is the starter pack up to date?"""

from __future__ import annotations

from pathlib import Path

import requests

from starter_pack_scanner.checks.base import BaseCheck, CheckResult

LATEST_VERSION_URL = (
    "https://raw.githubusercontent.com/canonical/sphinx-docs-starter-pack/"
    "main/docs/.sphinx/version"
)


def _fetch_latest_version() -> str | None:
    """Fetch the latest starter pack version from the upstream repo."""
    try:
        resp = requests.get(LATEST_VERSION_URL, timeout=10)
        resp.raise_for_status()
        return resp.text.strip()
    except requests.RequestException:
        return None


class VersionCheck(BaseCheck):
    @property
    def id(self) -> str:
        return "version"

    @property
    def name(self) -> str:
        return "Starter Pack Version"

    @property
    def description(self) -> str:
        return "Checks whether the starter pack version is the latest available."

    def run(self, repo_root: Path, docs_dir: Path | None) -> CheckResult:
        if docs_dir is None:
            return CheckResult(
                check_id=self.id,
                check_name=self.name,
                passed=False,
                message="No docs directory found; cannot check version.",
            )

        version_file = docs_dir / ".sphinx" / "version"
        if not version_file.exists():
            # Very old starter packs may not have a version file at all.
            return CheckResult(
                check_id=self.id,
                check_name=self.name,
                passed=False,
                message="No .sphinx/version file found — the starter pack may be very old (pre-1.0).",
                details=[f"Expected file: {version_file.relative_to(repo_root)}"],
            )

        local_version = version_file.read_text().strip()
        if not local_version:
            return CheckResult(
                check_id=self.id,
                check_name=self.name,
                passed=False,
                message="The .sphinx/version file is empty.",
            )

        latest_version = _fetch_latest_version()
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
