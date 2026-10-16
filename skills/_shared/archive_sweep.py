"""archive_sweep.py — one-time sweep of the completed-design archive.

Lists the per-design drops and the byte totals over
``three-pillars-docs/completed-tp-designs/*`` using ONE
``archive_allowlist.plan_prune_many`` call over every archived design dir
(never a per-design loop, which is order-dependent: a reference from one
design's drop candidate to another's is only resolved when both dirs are in
the same fixpoint). ``design.md`` is in the allowlist and is never a drop.

This script is OFFERED BY ``/tp-docs-update`` as a dry run and NEVER RUNS
AUTOMATICALLY. The default (no ``--apply``) only prints the plan; ``--apply``
calls ``archive_allowlist.apply`` and stages ``git rm`` for the tracked drops
without committing, printing the plan only after the apply succeeds (a refusal
prints nothing of it to stdout and exits 1). A repo with no ``completed-tp-designs/`` directory — or
one without any design subdirectories — prints ``nothing to sweep`` and exits
0.

CLI: ``archive_sweep.py [--apply] [--json] [--repo-root R]``. Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from archive_allowlist import (PrunePlan, UncommittedDropError, apply,
                               design_dir_problem, plan_prune_many)

COMPL = "three-pillars-docs/completed-tp-designs"
_SLUG_PART = len(COMPL.split("/"))  # index of the slug in a split repo path


def archived_design_dirs(repo_root: str | Path) -> list[str]:
    """Sorted repo-relative paths of the immediate subdirs of the archive.

    Non-directory entries are skipped; a missing archive yields ``[]``.
    """
    base = Path(repo_root) / COMPL
    if not base.is_dir():
        return []
    return sorted(f"{COMPL}/{e.name}" for e in os.scandir(base) if e.is_dir())


def evaluable_dirs(dirs: list[str], repo_root: str | Path) -> list[str]:
    """The dirs `plan_prune_many` can evaluate. A dir holding no tracked file
    has nothing to prune: it is skipped, named on stderr, never silently."""
    ok = []
    for d in dirs:
        problem = design_dir_problem(repo_root, d)
        if problem:
            print(f"archive_sweep: skipping {problem}", file=sys.stderr)
        else:
            ok.append(d)
    return ok


def summarize(plan: PrunePlan, repo_root: str | Path) -> dict:
    """Group a plan's drops by design slug, with per-design byte totals.

    Only designs with at least one drop are reported. Sizes are stat'ed
    before any removal (``apply`` is called after this returns).
    """
    root = Path(repo_root)
    per: dict[str, list[str]] = {}
    for p in plan.drop:
        parts = p.split("/")
        if len(parts) > _SLUG_PART + 1:
            per.setdefault(parts[_SLUG_PART], []).append(p)
    designs = []
    for slug in sorted(per):
        drops = per[slug]
        nbytes = 0
        for d in drops:
            try:
                nbytes += os.path.getsize(root / d)
            except OSError:
                pass
        designs.append({"slug": slug, "drop": drops, "bytes": nbytes})
    return {"designs": designs,
            "total_bytes": sum(d["bytes"] for d in designs)}


def sweep(repo_root: str | Path) -> dict:
    """Dry-run sweep: one ``plan_prune_many`` over every archived dir."""
    dirs = evaluable_dirs(archived_design_dirs(repo_root), repo_root)
    if not dirs:
        return {"designs": [], "total_bytes": 0}
    return summarize(plan_prune_many(dirs, repo_root), repo_root)


def _print(out: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(out, indent=2))
        return
    if not out["designs"]:
        print("nothing to sweep")
        return
    for d in out["designs"]:
        print(f"{d['slug']}: {len(d['drop'])} files, {d['bytes']} bytes")
    print(f"total: {out['total_bytes']} bytes")


def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="one-time completed-tp-designs sweep (dry run by default)")
    ap.add_argument("--apply", action="store_true",
                    help="git rm the tracked drops (staged, not committed)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--repo-root", default=os.getcwd())
    args = ap.parse_args(argv)

    dirs = evaluable_dirs(archived_design_dirs(args.repo_root), args.repo_root)
    if not dirs:
        _print({"designs": [], "total_bytes": 0}, args.json)
        return 0
    plan = plan_prune_many(dirs, args.repo_root)
    out = summarize(plan, args.repo_root)  # sizes stat'ed before any removal
    if args.apply:
        try:
            apply(plan, args.repo_root)
        except UncommittedDropError as exc:
            print(f"archive_sweep: {exc}", file=sys.stderr)
            return 1  # refused: nothing of the plan reaches stdout
    _print(out, args.json)  # after a successful apply, as archive_allowlist does
    return 0


if __name__ == "__main__":
    sys.exit(_main())
