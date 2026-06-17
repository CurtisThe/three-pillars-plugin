#!/usr/bin/env python3
"""invariant_check.py — citation coherence checker (inv #38 delegation target).

Exit codes:
  0  clean tree (no citation violations)
  1  violations found (one repair line per violation on stdout)
  2  internal error / corrupt framework-check.sh (fail-closed)

Flags:
  --repo-root <path>   path to repo root (default: .)
  --count              print active_count() and exit 0

Mirrors file_size_guard.py / hot_patch_check.py CLI shape.
stdlib-only: argparse, pathlib, sys.

design: invariant-citation-coherence
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure _shared/ is on path for sibling imports
_SHARED_DIR = Path(__file__).resolve().parent
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="invariant_check.py",
        description="Check citation coherence (inv #38).",
    )
    p.add_argument(
        "--repo-root",
        default=".",
        metavar="PATH",
        help="Path to repo root (default: current directory)",
    )
    p.add_argument(
        "--count",
        action="store_true",
        help="Print active_count() and exit 0",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    """Run citation coherence checks; return exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()

    if args.count:
        return _run_count(repo_root)

    return _run_checks(repo_root)


def _run_count(repo_root: Path) -> int:
    """Print active_count() for the repo and exit 0."""
    try:
        import invariant_map
        fc = repo_root / "framework-check.sh"
        m = invariant_map.parse_invariant_map(fc)
        count = invariant_map.active_count(m)
        print(count)
        return 0
    except Exception as exc:
        print(f"invariant_check: --count error: {exc}", file=sys.stderr)
        return 2


def _run_checks(repo_root: Path) -> int:
    """Run run_citation_checks and emit repair lines; return 0 or 1 or 2."""
    try:
        import citation_liveness
        report = citation_liveness.run_citation_checks(repo_root)
    except Exception as exc:
        print(f"invariant_check: internal error: {exc}", file=sys.stderr)
        return 2

    if report.ok:
        return 0

    try:
        lines = citation_liveness.format_violations(report)
    except Exception as exc:
        print(f"invariant_check: format error: {exc}", file=sys.stderr)
        return 2

    for line in lines:
        print(line)
    return 1


if __name__ == "__main__":
    sys.exit(main())
