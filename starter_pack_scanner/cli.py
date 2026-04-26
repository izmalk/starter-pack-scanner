"""CLI entry point for the starter pack scanner."""

from __future__ import annotations

import argparse
import sys

from starter_pack_scanner.checks import ALL_CHECKS
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
        "--only",
        nargs="*",
        default=None,
        metavar="CHECK_ID",
        help="Run only the specified check IDs.",
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
    print()

    results = scan(
        repo_url=args.repo,
        branch=args.branch,
        exclude_checks=set(args.exclude),
        include_checks=set(args.only) if args.only is not None else None,
    )

    passed = 0
    failed = 0
    for r in results:
        print(r)
        if r.passed:
            passed += 1
        else:
            failed += 1

    print(f"\n{'='*50}")
    print(f"Results: {passed} passed, {failed} failed, {passed + failed} total")

    sys.exit(1 if failed > 0 else 0)
