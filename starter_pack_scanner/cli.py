"""CLI entry point for the starter pack scanner."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from starter_pack_scanner import cache
from starter_pack_scanner.batch import BatchFileError, load_batch, run_batch
from starter_pack_scanner.checks import ALL_CHECKS, _BOLD, _GREEN, _RED, _RESET, _c, _use_color
from starter_pack_scanner.scanner import scan


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="starter-pack-scanner",
        description="Scan a repository for Canonical Starter Pack documentation and run checks.",
    )
    parser.add_argument(
        "repo",
        nargs="?",
        default=None,
        help="Git-cloneable repository URL (e.g. https://github.com/canonical/kafka-operator).",
    )
    parser.add_argument(
        "--batch",
        default=None,
        metavar="FILE",
        help="YAML file with a list of repositories to scan (see batch-scan.yml).",
    )
    parser.add_argument(
        "--group",
        default=None,
        metavar="GROUP",
        help="Only run checks in this group (e.g. 'migration' for URL-migration validation).",
    )
    parser.add_argument(
        "-b",
        "--branch",
        default=None,
        help="Branch or tag to scan (default: repo default branch).",
    )
    parser.add_argument(
        "--exclude",
        nargs="*",
        default=[],
        metavar="CHECK_ID",
        help="Check IDs to skip.",
    )
    parser.add_argument(
        "--check",
        nargs="*",
        default=None,
        metavar="CHECK_ID",
        help="Run only the specified checks (space-separated IDs).",
    )
    parser.add_argument(
        "--docs-url",
        default=None,
        metavar="URL",
        help="Published documentation base URL (auto-detected from conf.py otherwise).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        metavar="N",
        help="Seed for the random page sampling, for reproducible runs.",
    )
    parser.add_argument(
        "--allow-domain",
        action="append",
        default=[],
        dest="allow_domains",
        metavar="DOMAIN",
        help="Extra domain accepted by the docs-domain check (repeatable).",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Skip all checks that require network access to the published docs site.",
    )
    parser.add_argument(
        "--no-recommendations",
        action="store_true",
        help="Hide the 'Fix:' guidance shown for failed checks (for terse CI logs).",
    )
    parser.add_argument(
        "--old-url",
        default=None,
        metavar="URL",
        help="Pre-migration documentation URL, for migration-old-url-redirect "
             "(auto-derived from conf.py git history otherwise).",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Bypass the scan cache and always run a fresh scan.",
    )
    parser.add_argument(
        "--clear-cache",
        action="store_true",
        help="Delete all cached scan reports and exit.",
    )
    parser.add_argument(
        "--list-checks",
        action="store_true",
        help="List all available checks and exit.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output the report as JSON (machine-readable; for scripts and AI agents).",
    )
    return parser


def _run_batch_mode(args: argparse.Namespace) -> int:
    """Run the scanner over a batch file. Returns the exit code."""
    try:
        entries = load_batch(Path(args.batch))
    except BatchFileError as exc:
        print(_c(f"Error: {exc}", _RED, _BOLD))
        return 2

    print(f"Batch scanning {len(entries)} repositor(ies) from {args.batch} ...\n")

    total_failed = 0
    any_error = False
    for i, (entry, report) in enumerate(run_batch(entries, use_cache=not args.no_cache), 1):
        print(_c(f"[{i}/{len(entries)}] {entry.repo}", _BOLD))
        if report.error:
            any_error = True
            print(_c(f"  Error: {report.error}", _RED, _BOLD))
            print()
            continue
        timestamp = report.scanned_at.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
        print(f"  Report generated at {timestamp}")
        for r in report.results:
            print(f"  {r}")
        print(f"\n  Results: {report.passed} passed, {report.failed} failed, "
              f"{len(report.results)} total\n")
        total_failed += report.failed

    if any_error:
        print(_c("Some repositories could not be scanned.", _RED, _BOLD))
        return 2
    return 1 if total_failed > 0 else 0


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.clear_cache:
        removed = cache.clear()
        print(f"Removed {removed} cached report(s) from {cache.cache_dir()}")
        sys.exit(0)

    if args.list_checks:
        print("Available checks:\n")
        for cls in ALL_CHECKS:
            c = cls()
            print(f"  {c.id:20s} {c.description}")
        sys.exit(0)

    # Apply the recommendation visibility preference before any report is
    # printed (CheckResult.__str__ reads the module-level toggle).
    from starter_pack_scanner.base import set_show_recommendations

    set_show_recommendations(not args.no_recommendations)

    if not args.repo and not args.batch:
        parser.error("the following argument is required: repo (or --batch FILE)")

    if args.batch:
        sys.exit(_run_batch_mode(args))

    key = cache.cache_key(
        repo_url=args.repo,
        branch=args.branch,
        docs_url=args.docs_url,
        include_checks=set(args.check) if args.check is not None else None,
        exclude_checks=set(args.exclude),
        offline=args.offline,
        seed=args.seed,
        old_url=args.old_url,
    )
    # Note: check_group affects which checks run; fold it into the key via
    # the include set when a group is selected.
    if args.group:
        from starter_pack_scanner.checks import checks_by_group

        group_ids = {c().id for c in checks_by_group(args.group)}
        key = cache.cache_key(
            repo_url=args.repo,
            branch=args.branch,
            docs_url=args.docs_url,
            include_checks=group_ids,
            exclude_checks=set(args.exclude),
            offline=args.offline,
            seed=args.seed,
            old_url=args.old_url,
        )

    report = None
    if not args.no_cache:
        report = cache.get(key)

    if report is not None:
        if not args.json_output:
            print(f"Using cached report for {args.repo} (use --no-cache to re-scan)")
    else:
        if not args.json_output:
            print(f"Scanning {args.repo} ...")
            if args.branch:
                print(f"  Branch: {args.branch}")
            if args.docs_url:
                print(f"  Docs URL override: {args.docs_url}")
            if args.seed is not None:
                print(f"  Sampling seed: {args.seed}")
            print()

        report = scan(
            repo_url=args.repo,
            branch=args.branch,
            exclude_checks=set(args.exclude),
            include_checks=set(args.check) if args.check is not None else None,
            docs_url=args.docs_url,
            seed=args.seed,
            allow_domains=set(args.allow_domains),
            offline=args.offline,
            check_group=args.group,
            old_url=args.old_url,
        )
        cache.put(key, report)

    if report.error:
        if args.json_output:
            import json

            print(json.dumps(report.to_dict(), indent=2))
        else:
            print(_c(f"Error: {report.error}", _RED, _BOLD))
        sys.exit(2)

    if args.json_output:
        import json

        print(json.dumps(report.to_dict(), indent=2))
        sys.exit(1 if report.failed > 0 else 0)

    # Convert to the system local timezone (no user input or storage needed).
    timestamp = report.scanned_at.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    print(f"Report generated at {timestamp}\n")

    passed = 0
    failed = 0
    for r in report.results:
        print(r)
        if r.passed:
            passed += 1
        else:
            failed += 1

    print(f"\n{_c('=' * 50, _BOLD)}")
    passed_str = _c(str(passed), _GREEN, _BOLD)
    failed_str = _c(str(failed), _RED, _BOLD) if failed else str(failed)
    total_str = _c(str(passed + failed), _BOLD)
    print(f"{_c('Results:', _BOLD)} {passed_str} passed, {failed_str} failed, {total_str} total")
    if failed:
        print(_c("Note: checks are heuristic — please verify any failures manually.", _BOLD))

    sys.exit(1 if failed > 0 else 0)
