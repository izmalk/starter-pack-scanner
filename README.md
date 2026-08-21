# Starter Pack Scanner

A CLI tool to scan Git repositories that use [Canonical's Sphinx Stack](https://github.com/canonical/sphinx-stack) (ex. Starter Pack) and run a modular set of checks against them.

## Requirements

- Python 3.10+
- Git (available on `PATH`)

## Installation

```bash
cd starter-pack-scanner
pip install -e .
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
starter-pack-scanner https://github.com/canonical/kafka-operator --check docs-dir version
```

Exclude specific checks:

```bash
starter-pack-scanner https://github.com/canonical/kafka-operator --exclude version
```

Skip all checks that need network access to the published docs site:

```bash
starter-pack-scanner https://github.com/canonical/kafka-operator --offline
```

Override the published docs URL (auto-detected from `conf.py` otherwise):

```bash
starter-pack-scanner https://github.com/canonical/kafka-operator --docs-url https://canonical.com/data/kafka/docs/4/
```

Make the random page sampling reproducible:

```bash
starter-pack-scanner https://github.com/canonical/kafka-operator --seed 42
```

Extend the list of major documentation domains:

```bash
starter-pack-scanner https://github.com/canonical/kafka-operator --allow-domain example.com
```

## Available checks

| ID | Description |
|----|-------------|
| `docs-dir` | Checks whether the documentation is in the standard `docs/` directory of the repository. |
| `version` | Checks whether the starter pack version is the latest available. |
| `readme-docs-link` | Checks whether the repository README contains a link to the documentation. |
| `readme-rtd-badge` | Checks whether the repository README contains a Read the Docs badge. |
| `llms-txt` | Checks that the published documentation serves an `llms.txt` index for AI agents. |
| `llms-txt-links` | Checks that a sample of links from `llms.txt` resolves to live pages. |
| `llms-full-txt` | Checks that `llms.txt` links to `llms-full.txt` and that the link is not broken. |
| `page-metadata` | Checks that sampled pages have a non-empty meta description. |
| `docs-domain` | Checks that the documentation is published on a major company domain (e.g. `canonical.com`, `ubuntu.com`). |
| `page-markdown` | Checks that sampled pages serve a Markdown version for AI (page URL + `index.html.md`). |
| `page-agent-directive` | Checks that sampled pages contain a visually-hidden AI discovery directive (`llms.txt` pointer). |

The last seven checks are live-site checks: they resolve the published docs URL
from `conf.py` (`html_baseurl`, following redirects to the final URL), fetch
`llms.txt`, and sample 3 pages (from `llms.txt`, falling back to `sitemap.xml`)
shared by all checks. Use `--seed` for reproducible sampling and `--docs-url`
to override URL detection.

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

1. Define a class in `starter_pack_scanner/checks.py` that inherits from `BaseCheck`:

    ```python
    class MyCheck(BaseCheck):
        id = "my-check"
        name = "My Custom Check"
        description = "Describe what this check verifies."

        # Set to True if the check needs the published-site context
        # (network access); the scanner then builds a SiteContext.
        requires_site = False

        def run(
            self,
            repo_root: Path,
            docs_dir: Path | None,
            site_ctx: SiteContext | None = None,
        ) -> CheckResult:
            # repo_root: Path to the cloned repository root
            # docs_dir:  Path to the detected docs directory (or None)
            # site_ctx:  Published-site context (or None); only populated
            #            when requires_site is True
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

2. Add it to the `ALL_CHECKS` list at the bottom of `starter_pack_scanner/checks.py`.

## Removing or disabling a check

- **At runtime**: use `--exclude <check-id>` to skip checks.
- **Permanently**: remove the class from the `ALL_CHECKS` list in `checks.py`.