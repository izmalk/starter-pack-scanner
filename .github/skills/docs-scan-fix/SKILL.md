---
name: docs-scan-fix
description: 'Scan a documentation repository with starter-pack-scanner, fix every failed check using its recommendations, and re-scan until clean. Use when asked to audit, validate, or fix Canonical Sphinx Stack (Starter Pack) documentation, resolve scanner failures, or verify a docs migration. Also files scanner false-positive reports as GitHub issues.'
argument-hint: '<repo-url> [docs-url]'
---

# Docs Scan & Fix

Run the starter-pack-scanner against a documentation repository, fix every
failed check, and iterate until the report is clean (or remaining failures
are confirmed false positives, which get reported to the scanner project).

## When to Use

- "Scan/audit/validate the docs in <repo>"
- "Fix the failing checks in the docs"
- "Verify the docs migration completed correctly"
- Any request involving Canonical Sphinx Stack documentation quality

## Prerequisites

- The scanner CLI: `starter-pack-scanner` (repo: canonical/starter-pack-scanner).
  If not installed, install it first (`pip install -e .` from a clone).
- `gh` CLI authenticated, for false-positive issue filing (optional — see
  step 5 for the fallback).
- Network access for live-site checks; use `--offline` only when the user
  asks for repo-only checks.

## Procedure

### 1. Run the scan

```bash
starter-pack-scanner <repo-url> --json --no-cache
```

- `--json` gives a machine-readable report on stdout (see schema below).
- `--no-cache` forces a fresh scan — always use it in the fix loop so you
  see the effect of your edits, not a cached report.
- Add `--docs-url <url>` when the published docs URL is known and differs
  from what `conf.py` implies (e.g. a specific version like
  `https://canonical.com/data/kafka/docs/4/`).
- Add `--group migration` when the task is specifically about an RTD →
  Canonical domain migration.
- Exit code: 0 = all passed, 1 = failures present, 2 = scan could not run.

**Report schema** (stdout, one JSON object):

```json
{
  "repo_url": "...", "docs_dir": "docs",
  "results": [
    {
      "check_id": "migration-slug",
      "check_name": "Migration: Slug",
      "passed": false,
      "message": "why it failed",
      "details": ["specific evidence, e.g. offending URLs"],
      "recommendation": "how to fix it"
    }
  ]
}
```

### 2. Triage every failed check

For each `results[]` entry with `"passed": false`:

1. Read `message` + `details` — they name the exact file/setting/URL at fault.
2. Read `recommendation` — the primary fix guidance.
3. Consult the [check catalog](./references/check-catalog.md) for the
   check's playbook: exact files to edit, common pitfalls, and how to
   verify the fix locally before re-scanning.
4. Decide: **real problem** (fix it) or **false positive** (see the
   [false-positive guide](./references/false-positive-guide.md) for the
   evidence bar — do not dismiss a failure without concrete evidence).

### 3. Fix and re-scan (the loop)

1. Apply fixes for all real problems. Prefer the minimal change the
   recommendation describes; do not refactor beyond what the check needs.
2. Re-run the scan:

   ```bash
   starter-pack-scanner <repo-url> --json --no-cache
   ```

3. Compare with the previous report:
   - Fixed checks now pass → drop them from the worklist.
   - Still failing → re-read the message; the fix may need a rebuild or
     deploy before the live site reflects it (see "Live-site lag" below).
   - Newly failing → your edit broke something; revert or adjust.
4. Repeat until: all checks pass, OR every remaining failure is a
   confirmed false positive.

**Hard limit: 5 iterations.** If failures persist after 5 loops, stop,
summarise what remains and why, and ask the user how to proceed. Do not
loop forever on a check that cannot be fixed from the repository.

**Live-site lag:** checks against the published site (canonical.com etc.)
reflect the *deployed* docs, not your local edits. A conf.py fix only shows
up after the docs rebuild and deploy on Read the Docs. When a fix is
correct in the repo but the live check still fails, verify the source
change is right, note "pending deploy" for that check, and move on — do
not keep re-scanning.

### 4. Handle false positives

A failure is a false positive only when you have concrete evidence the
docs are actually correct (see the
[false-positive guide](./references/false-positive-guide.md) for criteria
and examples). For each confirmed false positive, file an issue on the
scanner project (step 5) — never silently ignore a failure.

### 5. File scanner issues for false positives

For each confirmed false positive, file an issue on
`canonical/starter-pack-scanner`:

```bash
gh issue create --repo canonical/starter-pack-scanner \
  --title "False positive: <check-id> on <repo-short-name>" \
  --body "<issue body>"
```

Issue body template (fill every field; evidence is what makes it actionable):

```markdown
## False positive report

**Check:** `<check-id>` — <check_name>
**Scanned repo:** <repo-url>
**Scanner command:** starter-pack-scanner <repo-url> <flags used>
**Scanner version:** output of `pip show starter-pack-scanner | grep Version`

**What the check reported:**
> <message>
> <details lines>

**Why this is a false positive:**
<concrete evidence: the conf.py lines, the live URL that works, the
screenshot, the guide section that contradicts the check>

**Expected:** <what the check should have done>
**Actual:** <what it did>
```

If `gh` is unavailable or unauthenticated, save the issue body to
`false-positive-<check-id>.md` in the working directory and tell the user
to file it manually.

Also file scanner issues (same repo, same `gh` flow) for any other scanner
problem encountered: crashes, hangs, misleading messages, checks that
cannot be satisfied. Title those `Scanner bug: ...` instead.

### 6. Report the outcome

Summarise for the user:

- **Fixed:** check ids + one line each on what was changed
- **False positives:** check ids + issue links (or draft file paths)
- **Pending deploy:** check ids fixed in-repo but not yet visible live
- **Unresolved:** anything left after the iteration cap, with reasoning

## Rules

- Never edit files outside the documentation repository being scanned
  (the scanner's own repo only receives issues).
- Never weaken or bypass a check (e.g. adding it to `--exclude`) to make
  a report clean — that hides problems rather than fixing them. Excludes
  are for the user to decide, not for this skill.
- Always use `--no-cache` inside the fix loop.
- One fix per check per iteration where practical — it keeps the
  re-scan diff attributable.
