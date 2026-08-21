# Starter Pack Scanner

A CLI tool to scan Git repositories that use [Canonical's Sphinx Stack](https://github.com/canonical/sphinx-stack) (ex. Starter Pack) and run a modular set of checks against them.

## Requirements

- Python 3.10+
- Git (available on `PATH`)
- For the web GUI only: install with the `web` extra (see below)

## Installation

```bash
cd starter-pack-scanner
pip install -e .
```

Or with the web GUI extras:

```bash
pip install -e ".[web]"
```

A `Makefile` is provided for common tasks (`make help` lists them all):

```bash
make install      # create .venv and install the CLI
make install-web  # create .venv and install CLI + web GUI
make run REPO=https://github.com/canonical/kafka-operator  # run the scanner
make serve-web    # start the web GUI at http://127.0.0.1:8765
make test         # run the test suite (offline, no network needed)
make lint         # compile-check all sources
make clean        # remove build artifacts (keeps .venv)
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

### Caching

Scan reports are cached on disk (one JSON file per scan configuration under
`~/.cache/starter-pack-scanner/`, honouring `XDG_CACHE_HOME`). Repeated scans
of the same repository are served from the cache instantly. Every report
shows the timestamp it was generated at.

- `--no-cache` — bypass the cache and run a fresh scan (the result replaces
  the cached entry).
- `--clear-cache` — delete all cached reports and exit.

There is no automatic expiry: refresh a report explicitly with `--no-cache`
or the "Re-scan" button in the web GUI.

## Web GUI

A minimal local web interface (FastAPI + Jinja2 + HTMX) for running scans
from the browser: enter a repository URL, optionally the published docs URL
and a branch, and get a rendered report of all checks.

### Start and stop

```bash
# Install with the web extra (once):
pip install -e ".[web]"

# Start (binds to 127.0.0.1:8765 — local only):
starter-pack-scanner-web

# Stop: press Ctrl+C in the terminal running it.
```

Or with make: `make serve-web`.

Then open <http://127.0.0.1:8765>. Alternatively run
`python -m starter_pack_scanner.web.app`.

The GUI shares the on-disk cache with the CLI: a scan started from the
browser is visible to the CLI and vice versa. The report shows its
generation timestamp and a "cached" badge when served from the cache;
the "Re-scan (bypass cache)" button forces a fresh scan.

### Security notes

The web GUI has **no authentication** and is intended for local use only:

- The server binds to `127.0.0.1` only — it is not reachable from the
  network. Do not expose it via port forwarding or reverse proxies.
- Repository URLs are validated before cloning: only `https://` is accepted
  (`http://` for localhost), embedded credentials are rejected, and hostnames
  resolving to private/loopback/link-local addresses are refused (basic SSRF
  protection).
- `git clone` runs with a 120-second timeout, and at most two scans run
  concurrently.

### Maintenance notes

- The GUI renders whatever checks are in `ALL_CHECKS` — adding a new check
  (see below) requires no web changes.
- Styling is built on [Vanilla Framework](https://vanillaframework.io/)
  (Canonical's design system), hotlinked from `assets.ubuntu.com`: Ubuntu
  fonts, `--vf-color-*` custom properties, and the `is-dark` class for dark
  mode. Custom styles in `starter_pack_scanner/web/static/style.css` only
  reference Vanilla's variables — to bump the version, change the `<link>`
  tag in `templates/index.html`.
- HTMX is loaded from a CDN (`unpkg.com`); to use the GUI fully offline,
  vendor `htmx.min.js` into `starter_pack_scanner/web/static/` and update the
  `<script>` tag in `templates/index.html`.
- Templates live in `starter_pack_scanner/web/templates/`, styles in
  `web/static/style.css`, and the theme toggle in `web/static/theme.js`
  (tri-state: auto / light / dark, persisted in `localStorage`).

## Testing

The test suite is fully offline — it never clones from GitHub or touches the
network, so it is safe to run from any CI infrastructure without rate-limit
concerns:

- Repositories are local `git init` fixtures created in a temp directory.
- All HTTP traffic (live-site checks) goes through a stubbed `http.get`.
- The web GUI is tested with FastAPI's `TestClient`.

```bash
make test          # or: python -m pytest tests/ -v
```

Requires `pytest` and `httpx` (`pip install pytest httpx`).

## Third-party assets and licenses

The web GUI uses the following third-party assets:

| Asset | Usage | License |
|-------|-------|---------|
| [Vanilla Framework](https://vanillaframework.io/) (Canonical) | CSS hotlinked from `assets.ubuntu.com` (typography, colors, Ubuntu fonts) | LGPL-3.0 |
| [Lucide](https://lucide.dev) icons (`monitor`, `sun`, `moon`) | Inlined SVGs in `web/templates/index.html` (theme toggle) | ISC |
| [HTMX](https://htmx.org) | JavaScript hotlinked from `unpkg.com` | 0BSD |

The Lucide SVGs are embedded copies, so their copyright notice is kept in the
template comment next to the icons (ISC requires the notice accompany
copies). The hotlinked assets (Vanilla Framework, HTMX, Ubuntu fonts) are not
redistributed by this project.

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
- `2` — The scan could not run (invalid URL, failed clone, missing git).

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