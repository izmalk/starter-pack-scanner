# AGENTS.md — Guidance for AI agents working on this repository

This document helps agentic AI (and humans) use, extend, and troubleshoot the
**starter-pack-scanner** effectively. Read it before making changes.

## What this tool does

Scans Git repositories that use Canonical's Sphinx Stack (Starter Pack) and
runs a modular set of checks against them — both the repository contents
(conf.py, README, version files) and the published documentation site
(llms.txt, sitemaps, canonical URLs, analytics, 404 behaviour).

Three interfaces share one core:

- **CLI**: `starter-pack-scanner <repo-url>` (single) or `--batch FILE` (many)
- **Web GUI**: `starter-pack-scanner-web` → http://127.0.0.1:8765 (local only)
- **Python API**: `starter_pack_scanner.scanner.scan()`

## Repository layout

```
starter_pack_scanner/
├── base.py              # CheckResult + BaseCheck (shared infra; import from here)
├── checks.py            # General checks + ALL_CHECKS registry + checks_by_group()
├── migration_checks.py  # URL-migration validation group (RTD → Canonical domains)
├── scanner.py           # scan(): clone → detect docs dir → run checks → ScanReport
├── site.py              # SiteContext: docs URL resolution, llms.txt, page sampling
├── http.py              # HTTP client with retries (all live-site checks use this)
├── rtd.py               # Read the Docs API v3 + GitHub commit-status client (for rtd-webhook)
├── batch.py             # Batch scanning from YAML files (load_batch / run_batch)
├── cache.py             # On-disk JSON cache (~/.cache/starter-pack-scanner/)
├── cli.py               # CLI entry point (supports --json for agents)
└── web/
    ├── app.py           # FastAPI app (GET /, POST /scan, POST /batch)
    ├── templates/       # Jinja2: index.html, _results.html, _batch_results.html
    └── static/          # style.css (Vanilla Framework vars), theme.js, tabs.js
.github/skills/docs-scan-fix/  # AI skill: scan → fix → re-scan → report FPs
tests/                   # Pytest suite — fully offline, no network
├── conftest.py          # Fixtures: make_repo(), StubHttp, local_repo, client
├── test_regressions.py  # Guards against previously fixed bugs
└── ...                  # Per-module test files
batch-scan.yml           # Example batch file (Kafka, OpenSearch, Valkey, Cassandra)
Makefile                 # install / run / serve-web / stop / test / lint / clean
```

## Key concepts

### Check architecture

- All checks inherit `BaseCheck` (in `base.py`) and implement
  `run(repo_root, docs_dir, site_ctx) -> CheckResult`.
- Class attributes: `id`, `name`, `description`, and optionally:
  - `requires_site = True` — needs the published-site context (network);
    the scanner builds a `SiteContext` only when at least one such check runs.
  - `group = "migration"` — belongs to a check group; selected via
    `--group` (CLI) or `check_group` (API/GUI).
- Register new checks by adding the class to `ALL_CHECKS` in `checks.py`.
  The CLI `--list-checks`, GUI, and batch mode pick them up automatically.
- **Every check must define a `recommendation`** (fix guidance shown on
  failure). Keep it under `RECOMMENDATION_SOFT_LIMIT` (300) chars where
  possible; `tests/test_recommendations.py` enforces the hard limit
  (`RECOMMENDATION_HARD_LIMIT`, 500). Both constants live in `base.py`.
- **Import rule**: `base.py` holds `CheckResult`/`BaseCheck` to avoid
  circular imports. `checks.py` and `migration_checks.py` both import from
  `base.py`. Never import `checks.py` from a check module at module level.
- **Shared "unavailable" results**: `base.py` provides `site_unavailable(check,
  site_ctx)` and `no_pages(check, site_ctx)` — use these instead of writing a
  per-class `_unavailable()` method. Both set their own scan-setup
  recommendation, which `execute()` preserves.
- **`execute()` vs `run()`**: the scanner calls `check.execute(...)`, which
  wraps `run()` and stamps the class `recommendation` onto the result. Tests
  may call `run()` directly (the recommendation is then empty). Never make
  the scanner call `run()` directly or recommendations are lost.
- **Checks needing constructor args**: `DocsDomainCheck(allow_domains)`,
  `OldUrlRedirectCheck(old_url)`, and `RtdWebhookCheck(rtd_project)` take an
  argument. `scanner.py::scan()` special-cases their instantiation by class
  identity in an if/elif chain — any new check needing a constructor arg must
  be added there too.

### Scan flow

`scan()` never raises for scan failures — it returns a `ScanReport` with
`error` set. Individual check failures are `CheckResult(passed=False)`.

`scan()` and `run_batch()` take an optional `progress: Callable[[int, str],
None]` callback (percent, step) fired at milestones (clone, docs-dir
detection, site resolution, each check). The web GUI's progress modal is
driven by it; CLI/API callers ignore it.

### Caching

- One JSON file per scan configuration in `~/.cache/starter-pack-scanner/`
  (XDG-aware), keyed by SHA-256 of (repo_url, branch, docs_url, include,
  exclude, offline, seed, old_url, rtd_project). Entries older than one week
  (`cache.MAX_AGE`) are auto-invalidated on read — `cache.get()` deletes the
  stale file and returns a miss. Refresh explicitly (`--no-cache`,
  "Re-scan" button, `refresh=true`). **Every new scan-affecting parameter
  must be added to `cache.cache_key()` AND both call sites in `cli.py` AND
  the call site in `batch.py`** — forgetting one lets a re-run silently
  return a stale cached report.
- **Gotcha**: `check_group` is not a cache-key parameter. When a group is
  selected, fold its check IDs into `include_checks` for the key (see
  `cli.py` and `web/app.py` for the pattern).

### URL validation (security)

`validate_repo_url()` in `scanner.py` guards the web GUI against SSRF:
https-only (http for localhost), no embedded credentials, DNS-resolved
hostnames must not be private/loopback/link-local. The web server binds
127.0.0.1 only; there is no auth by design.

### RTD webhook check (`rtd-webhook`)

Verifies the Read the Docs webhook is installed **and** firing, using only
public unauthenticated endpoints (no dashboard/integrations access):

- **RTD API v3** (`rtd.fetch_builds(slug, commit=<sha>)`) proves the webhook
  *fired*: a build whose `commit` matches the last docs commit. The API is
  publicly readable for public projects (anon limit: 5 req/min; set
  `READTHEDOCS_TOKEN` to lift to 60/min). `rtd.py` tries `.com` (Business)
  then `.org` (Community).
- **GitHub commit-status API** (`rtd.rtd_status_from_github`) proves the
  integration is *installed*: RTD writes a `docs/readthedocs.com:<slug>`
  status back to the repo. Its presence also reveals the RTD slug.

**Slug discovery** (first hit wins): explicit `--rtd-project` → published
page `<meta name="readthedocs-project-slug">` → GitHub status context →
"cannot verify" (never a false FAIL).

**Clone depth**: `scanner.clone_repo()` uses `--depth 50` (not 1) so the
check can find the commit that last touched `docs/`. This also fixes the
existing `_derive_old_url()` heuristic in `migration_checks.py`, which
scans `git log -n 50 -p -- conf.py` and previously only ever saw 1 commit.

The check never produces a false FAIL: when the slug cannot be discovered
or the APIs are unreachable (401/403/404/429), it passes with a "cannot
verify" note.

## Common tasks

```bash
make install          # set up .venv with everything (CLI + web GUI)
make install-cli      # CLI-only install (no web GUI deps)
make test             # run the offline test suite (225 tests)
make lint             # compile-check all sources
make serve-web        # start the GUI at http://127.0.0.1:8765 (aliases: server-web, web)
make run REPO=https://github.com/canonical/kafka-operator
```

### Running a batch scan

```bash
starter-pack-scanner --batch batch-scan.yml
```

Batch file format (YAML): optional `defaults` mapping + `repos` list; each
entry is a plain URL string or a mapping with `repo` plus any of: `branch`,
`docs_url`, `check_group`, `offline`, `exclude_checks`, `include_checks`,
`old_url`.
Validation errors raise `BatchFileError` with a precise message (CLI prints
it and exits 2; the GUI shows it inline).

### Running only the URL-migration checks

```bash
starter-pack-scanner https://github.com/canonical/kafka-operator --group migration
```

The migration group (15 checks) verifies the RTD → Canonical-domain migration
process against the guide's authoritative 7-item production checklist plus
additional requirements found throughout the guide: slug shape, base URL
shape (trailing slash + version segment), sitemap config, overwrite_links.js
content (`rtd_address`/`new_address`), `html_static_path`, live sitemap host
validation, canonical URL value validation, 404 for both invalid pages and
invalid versions, analytics (GTM + cookie banner), flyout/PDF host checks,
flyout version sanity, old-URL redirect, sitemap-index registration,
supported-URL shape, and RTD/staging link leakage on pages.

Version segments are treated as an **open set**: Read the Docs derives them
from the version *name* (an RTD alias like `latest`/`stable`/`default`, or a
branch/tag name like `main`, `24.04`, `3.6-lts`). Never assume only numeric
segments — LXD publishes at `/lxd/docs/default/`. Likewise, the production
requirements accept the sitemap at either `/sitemap.xml` or `/doc-sitemap.xml`.

Version segments are treated as an **open set**: Read the Docs derives them
from the version *name* (an RTD alias like `latest`/`stable`/`default`, or a
branch/tag name like `main`, `24.04`, `3.6-lts`). Never assume only numeric
segments — LXD publishes at `/lxd/docs/default/`. Likewise, the production
requirements accept the sitemap at either `/sitemap.xml` or `/doc-sitemap.xml`.

The migration guide itself
(`documentation.ubuntu.com/rtd-proxy/how-to/migrate/`) is behind Canonical
SSO and can't be fetched directly — use `github_repo`/`github_text_search`
against `canonical/RTD-Proxy` instead; the guide source is
`docs/how-to/migrate.rst` and `docs/how-to/validate-configuration.rst`.

`migration_checks.py` uses a `_Conf` dataclass (`_load_conf(docs_dir)`) to
parse `conf.py` (`.value()`, `.fstring()`, `.is_fstring()`,
`.list_contains()`, `.list_values()`), and `site.py` helpers `is_staging()`,
`is_rtd_host()`, `RTD_HOSTS`, `expected_slug_from_url()`,
`looks_like_version_segment()` for the shape/host validations.

## Testing rules (important)

- **The test suite is fully offline.** Never add tests that clone from
  GitHub or hit the network — CI must not hammer external services.
- Repositories: use `make_repo()` from `tests/conftest.py` (local `git init`
  fixtures in tmp dirs).
- HTTP: use the `stub_http` fixture (a `StubHttp` mapping URL substrings to
  canned `StubResponse`s). Note: when several keys match, the one closest to
  the **end** of the URL wins.
- Web: use the `client` fixture (FastAPI's `TestClient`, defined in
  `tests/conftest.py`).
- `local_repo` fixture: a `file://` URL with validation patched to allow it.
- **Regression tests**: when fixing a bug, add a test to
  `tests/test_regressions.py` (or the relevant module's test file) that
  fails without the fix. Existing regression coverage includes:
  versioned-URL rewriting, README docs-link false positives, cache-key
  collisions, FastAPI 422s on empty fields, and StubHttp key shadowing.

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `ImportError: cannot import name 'BaseCheck' ... (circular import)` | A check module imports from `checks.py` at module level. Import from `base.py` instead. |
| Web form returns 422 instead of friendly error | FastAPI `Form(...)` (required) on an optional field — use `Form(default="")`. |
| GUI serves stale/wrong check set | Cache key collision — remember to fold `check_group` into `include_checks` for the key (in `cli.py`, `web/app.py`, AND `batch.py`). |
| Live-site checks report 404 for pages that work in a browser | Versioned docs site: the base redirects to `/docs/4/` but llms.txt/sitemap.xml list unversioned links. `site.rewrite_versioned()` handles this — make sure sampled pages go through it. **Exception**: `llms-txt-links` deliberately probes `raw_pages` (unrewritten) — a versioned site with unversioned published links is a real defect and must fail. |
| README docs-link check passes on wrong links | The check matches against the product's own docs URL (conf.py/site context); generic `/docs` links only apply as a fallback when the product URL is unknown. |
| `git clone failed` with no detail | stderr is captured; the last line is shown. Check the URL and network. |
| Tests fail with `StubHttp` returning wrong response | Substring matching: a base-URL key can shadow specific paths; the closest-to-end match wins — order keys accordingly. |
| HTMX blocked in browser console | SRI hash mismatch on the CDN `<script>` tag; recompute with `curl -sL <url> \| openssl dgst -sha384 -binary \| openssl base64 -A`. |
| Server unreachable | It binds 127.0.0.1:8765 only; check `ss -tln \| grep 8765`. |

## Style and conventions

- Python ≥3.10, type hints with `from __future__ import annotations`.
- Frontend: Vanilla Framework (hotlinked) + `--vf-color-*` CSS variables;
  dark mode via the `is-dark` class on `<html>`; icons are inline Lucide
  SVGs (ISC license — keep the copyright comment in the template).
- Docs: update `README.md` when adding user-facing features; keep
  `AGENTS.md` in sync with architectural changes.
- Licenses of third-party assets are documented in README's
  "Third-party assets and licenses" table.
