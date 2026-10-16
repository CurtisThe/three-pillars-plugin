#!/usr/bin/env python3
"""wrapup_paths.py — the design-dir paths a wrap-up commit stages, and staging them.

design: run-throughput (operator ruling H1, PR #178: the Decision 12 data is committed)

A dispatcher's design-dir writes are committed where its writer's output is committed:

* the interactive `/tp-phase-implement` phase wrap-up (step 9): `plan.md`, `lock.json`,
  `decisions.md` and `dispatch-telemetry.ndjson` (`dispatch_tasks.py`'s task rows);
* the orchestrator's commit on `tp/{slug}` after Tier 3.5 (`--candidate single`): the same,
  plus `candidates/<id>/` (the four artifacts `run_tier_3_5.py` wrote beside its ndjson rows).

An uncommitted ndjson is lost with the worktree at `/tp-post-merge`. ``paths`` returns only the
entries that exist and differ from ``HEAD`` (modified or untracked, never ignored), so an
empty list means "no stragglers: skip the commit". Stdlib only.

CLI: ``wrapup_paths.py --design-dir D [--candidate ID] [--root R] [--stage]`` → prints
``{"paths": [...], "staged": bool}``; ``--stage`` runs one ``git add -- <path>`` per path
(one dead pathspec never suppresses the others). Exit 0; 2 when git fails.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

_SHARED = str(Path(__file__).resolve().parent)
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

from dispatch_log import NDJSON_NAME  # noqa: E402 — the telemetry file's one name
from escape_ledger import NDJSON_NAME as LEDGER_NAME  # noqa: E402 — the escape-ledger file's name
from task_scope import _git_env  # noqa: E402 — the shipped scrub: never an inherited GIT_DIR

WRAPUP = ("plan.md", "lock.json", "decisions.md", NDJSON_NAME, LEDGER_NAME)


def _git(root, *args) -> str:
    return subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True,
                          check=True, env=_git_env()).stdout


def candidates(design_dir, candidate: str | None = None) -> list[str]:
    """The design-dir entries a wrap-up may stage, in staging order (existence unchecked)."""
    base = Path(design_dir).as_posix().rstrip("/")
    names = list(WRAPUP) + ([f"candidates/{candidate}"] if candidate else [])
    return [f"{base}/{name}" for name in names]


def paths(design_dir, root=".", candidate: str | None = None) -> list[str]:
    """``candidates`` that exist and are modified or untracked (not ignored) under ``root``."""
    out = []
    for path in candidates(design_dir, candidate):
        if not (Path(root) / path).exists():
            continue
        if _git(root, "status", "--porcelain", "--untracked-files=all", "--", path).strip():
            out.append(path)
    return out


def stage(root, staged: list[str]) -> None:
    """One ``git add`` per path, so one missing path can only fail its own add."""
    for path in staged:
        _git(root, "add", "--", path)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="design-dir paths a wrap-up commit stages")
    parser.add_argument("--design-dir", required=True)
    parser.add_argument("--candidate", help="also stage candidates/<id>/ (Tier 3.5)")
    parser.add_argument("--root", default=".")
    parser.add_argument("--stage", action="store_true", help="git add each listed path")
    args = parser.parse_args(argv)
    try:
        found = paths(args.design_dir, args.root, args.candidate)
        if args.stage:
            stage(args.root, found)
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"wrapup_paths: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"paths": found, "staged": bool(args.stage and found)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
