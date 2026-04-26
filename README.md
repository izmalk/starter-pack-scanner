# Starter Pack Scanner

A CLI tool to scan Git repositories that use [Canonical's Sphinx Starter Pack](https://github.com/canonical/sphinx-docs-starter-pack) and run a modular set of checks against them.

## Requirements

- Python 3.10+
- Git (available on `PATH`)

## Installation

```bash
cd starter-pack-scanner
pip install -e .
```

Or without installing:

```bash
pip install -r requirements.txt
python -m starter_pack_scanner <repo-url>
```

## Usage

Scan a repository:

```bash
starter-pack-scanner https://github.com/canonical/kafka-operator
```

Scan a specific branch or tag:

```bash
starter-pack-scanner https://github.com/canonical/kafka-operator --branch main
```

List available checks:

```bash
starter-pack-scanner --list-checks
```

Run only specific checks:

```bash
starter-pack-scanner https://github.com/canonical/kafka-operator --only docs-location version
```

Exclude specific checks:

```bash
starter-pack-scanner https://github.com/canonical/kafka-operator --exclude version
```

## Available checks

| ID | Description |
|----|-------------|
| `docs-location` | Checks whether the documentation is located in the standard `docs/` directory. |
| `version` | Checks whether the starter pack version is the latest available (currently **1.6**). |
| `readme-docs-link` | Checks whether the repository README contains a link to the documentation. |
| `readme-rtd-badge` | Checks whether the repository README contains a Read the Docs badge. |

## How it works

1. The scanner shallow-clones the target repository to a temporary directory.
2. It detects the documentation root using multiple signals, in priority order:
   - A `.sphinx/` directory in `docs/` or the repo root (strongest signal).
   - A `.sphinx/` directory in any top-level subdirectory.
   - A `.readthedocs.yaml` that points to a `conf.py` location.
   - A `conf.py` file in `docs/`, the repo root, or any top-level subdirectory.
3. Each enabled check runs against the repository and produces a PASS/FAIL result.
4. The temporary clone is cleaned up automatically.

## Exit codes

- `0` — All checks passed.
- `1` — One or more checks failed.

## Adding a new check

1. Create a new Python file in `starter_pack_scanner/checks/`, e.g. `my_check.py`.

2. Define a class that inherits from `BaseCheck`:

    ```python
    from __future__ import annotations
    from pathlib import Path
    from starter_pack_scanner.checks.base import BaseCheck, CheckResult


    class MyCheck(BaseCheck):
        @property
        def id(self) -> str:
            return "my-check"

        @property
        def name(self) -> str:
            return "My Custom Check"

        @property
        def description(self) -> str:
            return "Describe what this check verifies."

        def run(self, repo_root: Path, docs_dir: Path | None) -> CheckResult:
            # repo_root: Path to the cloned repository root
            # docs_dir:  Path to the detected docs directory (or None)
            if some_condition:
                return CheckResult(
                    check_id=self.id, check_name=self.name,
                    passed=True, message="All good.",
                )
            return CheckResult(
                check_id=self.id, check_name=self.name,
                passed=False, message="Something is wrong.",
                details=["Extra context line 1", "Extra context line 2"],
            )
    ```

3. Register it in `starter_pack_scanner/checks/__init__.py`:

    ```python
    from starter_pack_scanner.checks.my_check import MyCheck

    ALL_CHECKS = [
        DocsLocationCheck,
        VersionCheck,
        MyCheck,           # ← add here
    ]
    ```

## Removing or disabling a check

- **At runtime**: use `--exclude <check-id>` to skip checks.
- **Permanently**: remove the class from the `ALL_CHECKS` list in `checks/__init__.py`.