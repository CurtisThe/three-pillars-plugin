#!/usr/bin/env python3
"""sweep_orphan_branches.py — Option B post-run sweeper CLI (backstop).

Thin, always-exit-0 wrapper over `sweep_orphan_agent_branches()` (Option A's
name-guarded, fail-open, live-worktree-excluding helper in
cleanup_worker_worktree.py) for the orchestrator's exit-time seam — both the
`## Cleanup` abnormal path and the after-Tier-7 normal-termination pointer
shell this script, so any `worktree-agent-*` auto-branch whose per-worker
sweep (Option A, Task 1.2) was skipped by an early abort or crash still gets
reclaimed.

Usage:
    python3 skills/tp-run-full-design/scripts/sweep_orphan_branches.py \
        [--decisions-log <path>]

Prints ``{"deleted": [...]}`` to stdout and ALWAYS exits 0 — Option B is a
backstop, so a helper exception must never make the orchestrator's exit
non-zero.

design: worktree-agent-branch-cleanup
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from cleanup_worker_worktree import sweep_orphan_agent_branches  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--decisions-log",
        type=Path,
        default=None,
        help="path to decisions.md to append one line per deleted branch",
    )
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        # argparse raises SystemExit(2) on a usage error (unknown flag, bad
        # value). Option B is a fail-open backstop — a malformed invocation
        # must never make the orchestrator's exit non-zero — so degrade any
        # error exit to 0 with an empty deleted list. A clean --help (code 0)
        # is left to exit normally.
        if exc.code not in (0, None):
            sys.stdout.write(json.dumps({"deleted": []}) + "\n")
            return 0
        raise

    try:
        deleted = sweep_orphan_agent_branches(decisions_log=args.decisions_log)
    except Exception:
        # Option B is a backstop — a helper exception must never make the
        # orchestrator's exit non-zero.
        deleted = []

    sys.stdout.write(json.dumps({"deleted": deleted}) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
