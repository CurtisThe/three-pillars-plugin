#!/usr/bin/env python3
"""wt_root.py — one checkout root for every role, kept off `.claude/`.

design: worktrees-under-wt-only (Task 1.1)

The auto-mode classifier gives no verdict on a write whose path sits under a
``.claude/`` directory, which is where worktree isolation puts a subagent. So every
role that needs a scratch checkout (worker, generator, regress, rerun, audit, cert,
attempt, hot-patch, baseline, revert) opens it here instead, under one root:

* run from a ``<repo>-wt/<slug>`` worktree: ``<root>/.tp-scratch/<role>-<slug>-<hex8>``;
* run from the seat: ``<seat-parent>/<seat-name>-wt/.tp-scratch/<slug>/<role>-<slug>-<hex8>``,
  outside the seat, a layout the worktree isolation guard accepts unchanged.

CLI (one JSON line on stdout; a refusal is one ``wt-root-refused`` line on stderr, exit 1):

    wt_root.py check <path>
    wt_root.py open --role R --slug S --base-ref REF [--root .]
    wt_root.py reap --role R --slug S [--root .]

``reap`` is fail-open (always exit 0 for a valid role and slug; a failure rides the JSON
as ``error``). Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scratch_root  # noqa: E402
from worker_root import has_claude_component  # noqa: E402

REFUSED = "wt-root-refused"
ROLES = ("worker", "generator", "regress", "rerun", "audit", "cert",
         "attempt", "hot-patch", "baseline", "revert", "compile")
SLUG_RE = re.compile(r"[a-z0-9][a-z0-9-]*\Z")


def _refusal(path) -> str:
    return (f"{REFUSED}: {path} is under a .claude/ directory, where the auto-mode classifier "
            "gives no verdict on writes; run from a <repo>-wt/<slug> worktree or the seat")


def _check(role: str, slug: str) -> None:
    if role not in ROLES:
        raise ValueError(f"{REFUSED}: unknown role {role!r} (one of {', '.join(ROLES)})")
    if not SLUG_RE.match(slug or ""):
        raise ValueError(f"{REFUSED}: slug {slug!r} is not a design name ([a-z0-9-]+)")


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)


def scratch_parent(root, slug: str) -> str:
    """The directory checkouts for `slug` live in. Pure: creates nothing."""
    real = os.path.realpath(str(root))
    if has_claude_component(real):
        raise ValueError(_refusal(real))
    outer = os.path.dirname(real)
    if os.path.basename(outer).endswith("-wt"):
        return os.path.join(real, scratch_root.SCRATCH_DIR)
    return os.path.join(outer, os.path.basename(real) + "-wt", scratch_root.SCRATCH_DIR, slug)


def ensure_parent(root, slug: str) -> str:
    """Create the scratch parent (excluding `.tp-scratch/` when it is inside root)."""
    path = scratch_parent(root, slug)
    os.makedirs(path, exist_ok=True)
    if path.startswith(os.path.realpath(str(root)) + os.sep):
        scratch_root.ensure_excluded(os.path.realpath(str(root)))
    return path


def open_checkout(root, role: str, slug: str, base_ref: str) -> str:
    """Create a detached `<role>-<slug>-<hex8>` worktree; return its real path."""
    _check(role, slug)
    if not os.path.isdir(str(root)):
        raise ValueError(f"{REFUSED}: root {root} is not a directory")
    parent = ensure_parent(root, slug)
    path = os.path.join(parent, f"{role}-{slug}-{uuid.uuid4().hex[:8]}")
    r = _git(os.path.realpath(str(root)), "worktree", "add", "--detach", "--end-of-options", path, base_ref)
    if r.returncode != 0:
        raise ValueError(f"{REFUSED}: git worktree add failed: {r.stderr.strip()}")
    return os.path.realpath(path)


def reap(root, role: str, slug: str) -> tuple[list[str], str]:
    """Remove only `<role>-<slug>-*` checkouts, then prune. Fail-open: (paths, error)."""
    reaped: list[str] = []
    try:
        _check(role, slug)
        real = os.path.realpath(str(root))
        parent = os.path.realpath(scratch_parent(real, slug))
        name = re.compile(rf"{re.escape(role + '-' + slug)}-[0-9a-f]{{8}}\Z")
        listing = _git(real, "worktree", "list", "--porcelain")
        if listing.returncode != 0:
            return reaped, f"git worktree list failed: {listing.stderr.strip()}"
        for line in listing.stdout.splitlines():
            if not line.startswith("worktree "):
                continue
            path = os.path.realpath(line[len("worktree "):])
            if (name.match(os.path.basename(path)) and os.path.dirname(path) == parent
                    and _git(real, "worktree", "remove", "--force", "--force", path).returncode == 0):
                reaped.append(path)
        _git(real, "worktree", "prune")
    except (OSError, ValueError, UnicodeDecodeError) as exc:  # tp-allow-fail-open: best-effort cleanup; error rides the JSON
        return reaped, str(exc)
    return reaped, ""


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="wt_root.py", description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check").add_argument("path")
    o = sub.add_parser("open")
    o.add_argument("--role", required=True)
    o.add_argument("--slug", required=True)
    o.add_argument("--base-ref", required=True)
    o.add_argument("--root", default=".")
    r = sub.add_parser("reap")
    r.add_argument("--role", required=True)
    r.add_argument("--slug", required=True)
    r.add_argument("--root", default=".")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.cmd == "check":
        if has_claude_component(args.path):
            print(_refusal(args.path), file=sys.stderr)
            return 1
        print(json.dumps({"path": args.path}))
        return 0
    if args.cmd == "open":
        try:
            path = open_checkout(args.root, args.role, args.slug, args.base_ref)
        except ValueError as exc:
            print(exc, file=sys.stderr)
            return 1
        print(json.dumps({"path": path}))
        return 0
    reaped, error = reap(args.root, args.role, args.slug)
    out: dict = {"reaped": reaped}
    if error:
        out["error"] = error
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
