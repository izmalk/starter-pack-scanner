# False-positive guide

How to decide whether a failed check is a false positive, and what
evidence to collect before reporting it.

## The bar

A failure is a false positive **only** when you can show the documentation
is actually correct *by the standard the check claims to enforce*. "I
think it looks fine" is not enough — you need a concrete artifact: a
working URL, a conf.py line, a spec section, a curl output.

If you cannot produce evidence, treat the failure as real and keep
fixing (or report it as unresolved after the iteration cap).

## Common false-positive patterns

### Intersphinx / cross-project links (migration-no-rtd-leakage)
Linking to *another* product's RTD-hosted docs (e.g. an intersphinx
target like `https://myst-parser.readthedocs.io/...`) is expected — the
check targets links to *this* docs set's old host. Evidence: the URL
belongs to a different project; the docs' own pages are all on the
production host.

### Version alias mismatch (migration-sitemap-index)
The site-wide sitemap index may register this docs set under a different
version alias than the scan resolved (e.g. `latest` vs `4`). If the
unversioned path IS registered, the docs are fine. (The scanner already
matches on the unversioned prefix, so a residual failure here usually
means a genuinely different path — double-check before claiming FP.)

### Deploy lag, not false positive
A live-site check failing right after a correct repo fix is **not** a
false positive — it's pending deploy. Mark it "pending deploy" and move
on. Only call FP when the deployed state is demonstrably correct.

### Legitimate naming variants (migration-overwrite-links)
Teams rename `overwrite_links.js` (e.g. `overwritelinks.js`) and its
variables (`oldDomain`/`newDomain`). The scanner matches common variants;
if it still fails on a functionally identical script, that's a scanner
gap worth reporting — include the script content as evidence.

### Checks that cannot pass from the repo
Some failures require action outside the docs repo (HAProxy config,
RTD dashboard settings, sitemap-index PRs). These are **real problems**
with external fixes, not false positives — report them to the user as
"requires external action" rather than filing scanner issues.

## Evidence checklist

Before filing a false-positive issue, you should have:

- [ ] The exact scanner command line used
- [ ] The check's `message` and `details` verbatim
- [ ] Concrete proof of correctness:
  - for URL checks: a `curl -I` showing the "broken" URL returns 200
  - for config checks: the relevant conf.py/template lines
  - for spec checks: the guide/spec section the check contradicts
- [ ] A one-sentence theory of *why* the scanner got it wrong (helps the
  maintainers fix the heuristic)

## Filing

File on `canonical/starter-pack-scanner` via `gh issue create` using the
template in SKILL.md step 5. One issue per check/repo combination — do not
batch unrelated false positives into one issue.

If `gh` is unavailable, write the issue body to
`false-positive-<check-id>.md` and tell the user.
