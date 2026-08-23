# Check catalog — fix playbooks

Per-check guidance for the docs-scan-fix skill. Each entry: what the check
verifies, where to fix it, and how to verify before re-scanning.

Check groups: repo checks (fix in the repository) and live-site checks
(fix in the repo, verify on the deployed site — expect deploy lag).

## General checks

### `docs-dir` — docs in `docs/`
- **Fix:** move documentation to a top-level `docs/` directory; update
  `.readthedocs.yaml` → `sphinx.configuration` to the new `conf.py` path.
- **Verify:** `docs/conf.py` exists; RTD build config points at it.

### `version` — starter pack up to date
- **Fix:** from `docs/`, run `make update` (or `python _dev/update_sp.py`);
  commit refreshed `_dev/` files.
- **Verify:** `docs/_dev/version` matches the latest at
  canonical/sphinx-stack.

### `readme-docs-link` — README links to the docs
- **Fix:** add a documentation link to the repo README, using the exact
  URL from `html_baseurl` in `conf.py`.
- **Verify:** the URL in the README opens the live docs.

### `readme-rtd-badge` — README has a build badge
- **Fix:** add the RTD badge image linked to the docs.
- **Verify:** badge markdown renders (image URL returns 200).

### `llms-txt` — llms.txt served
- **Fix:** add `sphinx_llm.txt` to `extensions` in `conf.py`; set
  `llms_txt_description`.
- **Verify:** `llms.txt` exists in the build output (`_build/`).

### `llms-txt-links` — llms.txt links resolve
- **Fix:** versioned docs need `html_baseurl` with the version segment and
  trailing slash: `f"https://canonical.com/<slug>/{os.environ.get('READTHEDOCS_VERSION', 'local')}/"`.
  Version-less links 404 on versioned sites.
- **Verify:** a link from the generated llms.txt opens with HTTP 200.

### `llms-full-txt` — llms-full.txt linked and reachable
- **Fix:** same root cause as `llms-txt-links` (html_baseurl shape);
  both files are emitted together by sphinx_llm.txt.

### `page-metadata` — pages have meta description
- **Fix:** add MyST front matter to each page:
  `myst: html_meta: description: "..."` (keep under ~160 chars).
- **Verify:** built HTML contains `<meta name="description" ...>`.

### `docs-domain` — published on a major domain
- **Fix:** publish under canonical.com/ubuntu.com/etc. per the RTD-Proxy
  migration guide. If the domain is legitimately new, the *user* may pass
  `--allow-domain` — do not add it yourself to silence the check.

### `page-markdown` — Markdown version served
- **Fix:** `sphinx_llm.txt` in `extensions` (pulls sphinx-markdown-builder);
  verify `<page>/index.html.md` exists in the build output.

### `page-agent-directive` — hidden AI directive on pages
- **Fix:** add a visually-hidden `<div data-agent-directive>` pointing at
  llms.txt to `_templates/header.html`; hide with the clip-rect technique
  (NOT `display: none` — cloaking risk). See agentdocsspec.com/spec/.

## Migration checks (repo-side)

### `migration-slug`
- **Fix:** `slug = "<path>/<to>/docs"` in conf.py — URL path after the
  domain, docs root only: no scheme, no leading/trailing `/`, no `en`,
  no version segment. Must match the HAProxy frontend path.

### `migration-baseurl`
- **Fix:** `html_baseurl` and `ogp_site_url` = production URL, trailing
  slash, version segment when versioned (f-string over
  READTHEDOCS_VERSION). Never readthedocs-hosted.com.

### `migration-sitemap-config`
- **Fix:** `sitemap_url_scheme = "{link}"` and
  `sitemap_filename = "doc-sitemap.xml"` in conf.py.

### `migration-overwrite-links`
- **Fix:** customise `scripts/url-overwrite.js` from canonical/RTD-Proxy →
  save as `_static/js/overwrite_links.js` → register in `html_js_files`.
  `rtd_address` = the `*.readthedocs-hosted.com` host (no protocol);
  `new_address` = new path (no protocol, no trailing slash). Tag-versioned
  docs: use the RTD custom-script addon instead and REMOVE the file from
  the repo (both present = error).

### `migration-static-path`
- **Fix:** `html_static_path = ["_static"]` (append, don't replace).

## Migration checks (live-site)

All of these verify the *deployed* site — fixes land only after a docs
rebuild + deploy. Verify the repo change is correct, then expect lag.

### `migration-sitemap-live`
- **Fix:** sitemap URLs come from `html_baseurl` + `sitemap_url_scheme`;
  wrong host or missing/duplicated version segment → fix `html_baseurl`.

### `migration-canonical-url`
- **Fix:** canonical URLs come from `html_baseurl`; staging/RTD values mean
  it's still pointing at the old host. Also check `overwrite_links.js`
  `new_address`.

### `migration-404`
- **Fix:** soft 404s need the HAProxy `http-response set-status 404` rule
  (see the migration guide's Backend section) — this is a scanner-repo
  config change via @docproxysupport, not a docs-repo edit. A wrong `slug`
  in conf.py is the usual root cause.

### `migration-analytics`
- **Fix:** GTM snippet (Canonical container `GTM-KNX3CJC`) + cookie banner
  in the page templates; the Sphinx Stack ships defaults in
  `_templates/header.html` and `cookie-banner.css`.

### `migration-flyout-pdf` / `migration-flyout-versions`
- **Fix:** flyout/PDF links pointing at RTD hosts → check
  `overwrite_links.js` values; leftover `migrate-*`/`test` versions →
  clean up in the RTD dashboard (delete/hide, remove temp redirects).

### `migration-old-url-redirect`
- **Fix:** add the redirect in the RTD dashboard: documentation.ubuntu.com
  sources → Ubuntu Documentation Library project; readthedocs-hosted.com
  sources → the old project itself. Old project must be removed from the
  Library's subprojects first.

### `migration-sitemap-index`
- **Fix:** PR adding a `<sitemap>` entry to
  canonical/canonical.com `templates/sitemap-index.xml` or
  canonical/ubuntu.com `templates/sitemap_index.xml`.

### `migration-url-shape`
- **Fix:** docs belong under the product marketing page
  (`canonical.com/<product>/docs`). Exception-list paths (dqlite,
  microk8s, ...) need @docproxysupport coordination.

### `migration-no-rtd-leakage`
- **Fix:** grep the sources for hardcoded RTD URLs
  (`grep -r readthedocs docs/`); check `overwrite_links.js` is registered
  with correct values. Intersphinx targets to other RTD-hosted projects
  are expected and fine — that's a likely false positive.
