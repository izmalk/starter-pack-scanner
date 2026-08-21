"""CLI entry point for the starter pack scanner."""

from __future__ import annotations

import argparse
import sys

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
        "--list-checks",
        action="store_true",
        help="List all available checks and exit.",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.list_checks:
        print("Available checks:\n")
        for cls in ALL_CHECKS:
            c = cls()
            print(f"  {c.id:20s} {c.description}")
        sys.exit(0)

    if not args.repo:
        parser.error("the following argument is required: repo")

    print(f"Scanning {args.repo} ...")
    if args.branch:
        print(f"  Branch: {args.branch}")
    if args.docs_url:
        print(f"  Docs URL override: {args.docs_url}")
    if args.seed is not None:
        print(f"  Sampling seed: {args.seed}")
    print()

    results = scan(
        repo_url=args.repo,
        branch=args.branch,
        exclude_checks=set(args.exclude),
        include_checks=set(args.check) if args.check is not None else None,
        docs_url=args.docs_url,
        seed=args.seed,
        allow_domains=set(args.allow_domains),
        offline=args.offline,
    )

    passed = 0
    failed = 0
    for r in results:
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
