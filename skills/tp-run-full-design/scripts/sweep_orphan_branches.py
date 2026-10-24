#!/usr/bin/env python3
"""sweep_orphan_branches.py — Option B post-run sweeper CLI (backstop).

Thin, always-exit-0 wrapper over `sweep_orphan_agent_branches()` (name-guarded,
fail-open, live-worktree-excluding helper in cleanup_worker_worktree.py) for the
orchestrator's exit-time seam — both the `## Cleanup` abnormal path and the
after-Tier-7 normal-termination pointer shell this script, so a `worktree-agent-*`
auto-branch whose per-worker sweep (Option A) was skipped by an early abort or
crash still gets reclaimed.

Owned-only: the sweep deletes only the branches this run recorded under
``--slug`` (``owned_agent_branches``), and never one that a live worktree has
checked out or whose id names a live ``agent-<id>`` worktree. Without
``--slug`` (or with no record) nothing is deleted, so a second run's branches in
the same clone are safe.

Usage:
    python3 skills/tp-run-full-design/scripts/sweep_orphan_branches.py \
        [--slug <design-slug>] [--root <repo>] [--decisions-log <path>]

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

import owned_agent_branches  # noqa: E402
from cleanup_worker_worktree import sweep_orphan_agent_branches  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--slug",
        default=None,
        help="design slug whose recorded agent branches may be deleted",
    )
    parser.add_argument(
        "--root",
        default=".",
        help="repo root the git calls and the ownership record live under",
    )
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
        owned = owned_agent_branches.owned(args.root, args.slug) if args.slug else set()
        deleted = sweep_orphan_agent_branches(
            decisions_log=args.decisions_log, owned=owned, root=args.root
        )
    except Exception:
        # Option B is a backstop — a helper exception must never make the
        # orchestrator's exit non-zero.
        deleted = []

    sys.stdout.write(json.dumps({"deleted": deleted}) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
