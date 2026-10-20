#!/usr/bin/env python3
"""ladder_files.py — the per-design ladder directory: its file layout and its cleanup.

design: run-throughput (seat rulings G4, G5 — PR #178 live checks #2 and #3)

``<git-common-dir>/tp-ladder/<slug>/`` (``L``) holds, per task ``<id>``, the ladder record
``R`` (``<id>.json``) and the side files one attempt writes: ``C`` (``<id>.check.json``),
``S`` (``.scan.json``), ``F`` (``.reply.txt``), ``W`` (``.watch.json``, the watchdog state),
``P`` (``.poll.json``, the latest poll) and ``V`` (``.review.txt``, a no-oracle task's Opus
diff-review reply). ``F``, ``V``, ``C`` and ``S`` are the four a ``tp-worker`` ever writes,
and a worktree-isolated worker refuses a path outside its own tree, so ``paths`` prints
those four under ``<worktree>/.tp-scratch/tp-ladder/<slug>/`` (``T``, scratch: excluded,
never ``git status``) while the dispatcher-owned ``R``/``W``/``P`` stay in ``L``.
Callers that pass no ``T`` (``clear_task``, legacy) keep the ``L``-only layout, and both
``--fresh`` and ``sweep`` clear the ``F``/``V``/``C``/``S`` copies in each directory they
cover.

* ``paths`` resolves them to **literal absolute paths** and creates the directory, so a
  dispatcher's commands carry no ``$(git rev-parse …)`` substitution and no ``mkdir``
  compound: a worktree-isolated ``tp-worker`` refuses any computed argument (G5).
  ``--fresh`` first clears this task's side files from an earlier attempt, so ``next``
  and ``orphans`` never read a stale ``C``/``P``/``F``/``S``/``W`` (G4).
* ``sweep`` (run by ``task_verify.py sweep``) clears the side files of every task with no
  live attempt record left in ``tp-attempts/<slug>/`` — done or discarded attempts.

An orphan-marked or stopped ``W`` is kept until its attempt is done (``attempt_orphans.status``:
end of turn, or the stop with no open local request): it is what keeps the rest of the phase
off the GPU. The ladder record ``R`` is never removed here (``tier_ladder.py start`` rewrites
it), nor is the durable stop record ``STOPS`` (``stops.ndjson``,
``stopped_agents.append_ladder``): it matches no ``SIDE`` suffix. Stdlib only.

CLI (one JSON object on stdout; exit 2 on a bad slug/task or a non-git root)::

    ladder_files.py paths --slug S [--task ID] [--fresh] [--root .]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

_SHARED = str(Path(__file__).resolve().parent)
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

import attempt_orphans  # noqa: E402 — status (the orphans predicate)
import scratch_root  # noqa: E402 — SCRATCH_DIR, the in-tree scratch base
import task_attempts  # noqa: E402 — common_dir, the attempt records' home

LADDER = "tp-ladder"
TREE = scratch_root.SCRATCH_DIR + "/" + LADDER  # the in-tree copy of the ladder dir
AGENT_WRITTEN = ("reply", "review", "check", "scan")  # F + V + C + S: what a tp-worker writes
SIDE = {"check": ".check.json", "scan": ".scan.json", "reply": ".reply.txt",
        "watch": ".watch.json", "poll": ".poll.json", "review": ".review.txt"}
STOPS = "stops.ndjson"  # durable per-stop record (router_daily); never a side file


def _segment(value: str, what: str) -> str:
    value = str(value or "")
    if not value or value in (".", "..") or "/" in value or "\\" in value:
        raise ValueError(f"{what} must be one path segment, got {value!r}")
    return value


def ladder_dir(root, slug: str) -> Path:
    """``<git-common-dir>/tp-ladder/<slug>`` (absolute, realpath) for the repo at ``root``."""
    return Path(task_attempts.common_dir(root)) / LADDER / _segment(slug, "slug")


def tree_dir(root, slug: str) -> Path:
    """``<worktree toplevel>/.tp-scratch/tp-ladder/<slug>`` — the in-tree ladder dir."""
    return Path(task_attempts.toplevel(root)) / TREE / _segment(slug, "slug")


def paths(ldir: Path, task: str, tdir=None) -> dict:
    """``{record, check, scan, reply, watch, poll, review}`` for ``task``.

    ``AGENT_WRITTEN`` keys resolve under ``tdir`` when it is given; without it every
    path stays under ``ldir`` (the pre-in-tree layout the legacy callers keep).
    """
    task = _segment(task, "task")
    out = {"record": str(ldir / f"{task}.json"),
           **{k: str(ldir / f"{task}{suffix}") for k, suffix in SIDE.items()}}
    if tdir is not None:
        for key in AGENT_WRITTEN:
            out[key] = str(Path(tdir) / f"{task}{SIDE[key]}")
    return out


def _live_orphan(path: Path, config_dir) -> bool:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(state, dict):
        return False
    candidate = bool(state.get("orphan")) or int(state.get("stop_attempts") or 0) > 0
    return candidate and attempt_orphans.status(state, config_dir=config_dir)["state"] != "done"


def _clear(files, config_dir) -> tuple[list[str], list[str]]:
    removed, kept = [], []
    for path in files:
        if path.name.endswith(SIDE["watch"]) and _live_orphan(path, config_dir):
            kept.append(str(path))
            continue
        try:
            path.unlink()
            removed.append(str(path))
        except FileNotFoundError:
            pass
    return removed, kept


def clear_task(ldir: Path, task: str, config_dir=None, tdir=None) -> dict:
    """Remove ``task``'s side files (never ``R``; a live orphan ``W`` stays).

    With ``tdir`` the agent-written copy in the in-tree dir goes too, and the legacy
    ``L`` copies of all four are removed either way.
    """
    files = [Path(p) for k, p in paths(ldir, task, tdir).items() if k != "record"]
    if tdir is not None:
        files += [Path(p) for k, p in paths(ldir, task).items() if k in AGENT_WRITTEN]
    removed, kept = _clear([f for f in files if f.exists()], config_dir)
    return {"removed": removed, "kept_orphans": kept}


def _task_of(name: str) -> str | None:
    return next((name[: -len(s)] for s in SIDE.values() if name.endswith(s)), None)


def live_tasks(root, slug: str) -> set:
    """Task ids with an attempt record still in ``tp-attempts/<slug>/``."""
    rec_dir = (Path(task_attempts.common_dir(root)) / task_attempts.RECORDS
               / task_attempts.slug_of(slug))
    out = set()
    for path in rec_dir.glob("*.json") if rec_dir.is_dir() else []:
        try:
            out.add(str(json.loads(path.read_text(encoding="utf-8"))["task_id"]))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return out


def _stale(ld: Path, live: set) -> list[Path]:
    """``ld``'s side files whose task id has no live attempt record."""
    if not Path(ld).is_dir():
        return []
    return [p for p in sorted(Path(ld).iterdir())
            if _task_of(p.name) is not None and _task_of(p.name) not in live]


def sweep(root, slug: str, config_dir=None) -> dict:
    """Clear every side file whose task has no live attempt → ``{removed, kept_orphans}``.

    Covers both ladder dirs: ``L`` (all side files) and the in-tree ``T`` (where an
    abandoned attempt's ``F``/``V``/``C``/``S`` are left behind).
    """
    try:
        ldir, tdir = ladder_dir(root, slug), tree_dir(root, slug)
    except (ValueError, subprocess.CalledProcessError):
        return {"removed": [], "kept_orphans": []}
    live = live_tasks(root, slug)
    removed, kept = _clear(_stale(ldir, live) + _stale(tdir, live), config_dir)
    return {"removed": removed, "kept_orphans": kept}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="The ladder directory's literal paths.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("paths")
    sp.add_argument("--slug", required=True)
    sp.add_argument("--task")
    sp.add_argument("--fresh", action="store_true",
                    help="first clear this task's side files from an earlier attempt")
    sp.add_argument("--root", default=".")
    args = parser.parse_args(argv)
    try:
        ldir, tdir = ladder_dir(args.root, args.slug), tree_dir(args.root, args.slug)
        scratch_root.ensure_excluded(args.root)  # before any write: T is scratch
        os.makedirs(ldir, exist_ok=True)
        os.makedirs(tdir, exist_ok=True)
        out: dict = {"dir": str(ldir)}
        if args.task is not None:
            out.update(paths(ldir, args.task, tdir))
            if args.fresh:
                out["cleared"] = clear_task(ldir, args.task, tdir=tdir)
        elif args.fresh:
            raise ValueError("--fresh needs --task")
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(f"ladder_files: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(out, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
