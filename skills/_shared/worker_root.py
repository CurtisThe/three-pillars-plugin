#!/usr/bin/env python3
"""worker_root.py — the tp-worker write root, kept off `.claude/`.

design: classifier-no-verdict-nested-writes (Task 1.1)

The auto-mode classifier returns no verdict on a write whose path sits under a
``.claude/`` directory, and the harness puts a worktree-isolated subagent there.
So the orchestrator opens the ``tp-worker``'s candidate worktree itself, under its own
``.tp-scratch/`` (gitignored, accepted by the worktree isolation guard), and pins the
worker to it.

CLI (one JSON line on stdout; a refusal is one ``worker-root-*`` line on stderr, exit 1):

    worker_root.py check <path>
    worker_root.py open --slug S --phase N --base-ref R [--root .]
    worker_root.py verify --path P
    worker_root.py reap --slug S [--keep P] [--root .]
    worker_root.py tip --branch B [--root .]
    worker_root.py assert-unmoved --branch B --sha S [--root .]

``reap`` is fail-open (always exit 0; an evaluation failure rides the JSON as ``error``).
``tip`` and ``assert-unmoved`` are the orchestrator's check that a worker that left its
worktree did not commit onto the branch it runs on (``worker-escaped-worktree``). Stdlib only.
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

CAND_PREFIX = "tp-cand-"
REFUSED = "worker-root-refused"
OPEN_FAILED = "worker-root-open-failed"
ESCAPED = "worker-escaped-worktree"
SLUG_RE = re.compile(r"[a-z0-9][a-z0-9-]*\Z")


def has_claude_component(path) -> bool:
    """True when `path`, as given or resolved, has a `.claude` part."""
    raw = str(path)
    return any(".claude" in Path(p).parts for p in (raw, os.path.realpath(raw)))


def _refusal(path) -> str:
    return (f"{REFUSED}: {path} is under a .claude/ directory, where the auto-mode classifier "
            "gives no verdict on writes; run the orchestrator from a <repo>-wt/<slug> worktree")


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)


def _check_phase(phase) -> None:
    if not re.fullmatch(r"[0-9]+", str(phase)):
        raise ValueError(f"{REFUSED}: --phase must be a non-negative integer, got {phase!r}")


def _check_slug(slug: str) -> None:
    if not SLUG_RE.match(slug or ""):
        raise ValueError(f"{REFUSED}: slug {slug!r} is not a design name ([a-z0-9-]+)")


def open_worktree(root, slug: str, phase, base_ref: str) -> str:
    """Create the detached candidate worktree; return its real path. Raises ValueError on refusal."""
    _check_slug(slug)
    _check_phase(phase)
    if not os.path.isdir(str(root)):
        raise ValueError(f"{OPEN_FAILED}: root {root} is not a directory")
    root = os.path.realpath(str(root))
    if has_claude_component(root):
        raise ValueError(_refusal(root))
    scratch_root.ensure_excluded(root)
    path = os.path.join(scratch_root.parent(root), f"{CAND_PREFIX}{slug}-p{phase}-{uuid.uuid4().hex[:8]}")
    if has_claude_component(path):
        raise ValueError(_refusal(path))
    try:
        r = _git(root, "worktree", "add", "--detach", "--end-of-options", path, base_ref)
    except OSError as exc:
        raise ValueError(f"{OPEN_FAILED}: {exc}") from exc
    if r.returncode != 0:
        raise ValueError(f"{OPEN_FAILED}: git worktree add failed: {r.stderr.strip()}")
    return os.path.realpath(path)


def verify_toplevel(path) -> bool:
    """True when `path` is absolute and the current directory's git toplevel is `path`."""
    if not path or not os.path.isabs(str(path)):
        return False
    r = _git(os.getcwd(), "rev-parse", "--show-toplevel")
    return r.returncode == 0 and os.path.realpath(r.stdout.strip()) == os.path.realpath(str(path))


def reap(root, slug: str, keep=None) -> tuple[list[str], str]:
    """Remove every `tp-cand-<slug>-*` worktree except `keep`, then prune.

    Fail-open: returns (reaped paths, error text); an empty error means the listing was read.
    """
    root = os.path.realpath(str(root))
    name = re.compile(rf"{re.escape(CAND_PREFIX + slug)}-p\d+-[0-9a-f]{{8}}\Z")
    keep = os.path.realpath(str(keep)) if keep else None
    reaped: list[str] = []
    try:
        listing = _git(root, "worktree", "list", "--porcelain")
        if listing.returncode != 0:
            return reaped, f"git worktree list failed: {listing.stderr.strip()}"
        for line in listing.stdout.splitlines():
            if not line.startswith("worktree "):
                continue
            path = os.path.realpath(line[len("worktree "):])
            if (name.match(os.path.basename(path)) and path != keep
                    and os.path.dirname(path) == os.path.join(root, scratch_root.SCRATCH_DIR)
                    and _git(root, "worktree", "remove", "--force", "--force", path).returncode == 0):
                reaped.append(path)
        _git(root, "worktree", "prune")
    except (OSError, UnicodeDecodeError) as exc:  # tp-allow-fail-open: best-effort cleanup; the error rides the JSON
        return reaped, str(exc)
    return reaped, ""


def branch_tip(root, branch: str) -> str:
    """The sha `branch` points at, or "" when it cannot be read."""
    try:
        r = _git(root, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}")
    except OSError:
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="worker_root.py", description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check").add_argument("path")
    o = sub.add_parser("open")
    o.add_argument("--slug", required=True)
    o.add_argument("--phase", required=True)
    o.add_argument("--base-ref", required=True)
    o.add_argument("--root", default=".")
    sub.add_parser("verify").add_argument("--path", required=True)
    r = sub.add_parser("reap")
    r.add_argument("--slug", required=True)
    r.add_argument("--keep")
    r.add_argument("--root", default=".")
    t = sub.add_parser("tip")
    t.add_argument("--branch", required=True)
    t.add_argument("--root", default=".")
    a = sub.add_parser("assert-unmoved")
    a.add_argument("--branch", required=True)
    a.add_argument("--sha", required=True)
    a.add_argument("--root", default=".")
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
            path = open_worktree(args.root, args.slug, args.phase, args.base_ref)
        except ValueError as exc:
            print(exc, file=sys.stderr)
            return 1
        print(json.dumps({"path": path}))
        return 0
    if args.cmd == "verify":
        if verify_toplevel(args.path):
            print(json.dumps({"path": args.path}))
            return 0
        print(f"{REFUSED}: cwd {os.getcwd()} is not the worker worktree {args.path!r} (it must be an "
              f"absolute path); prefix every command with `cd <WORKTREE> &&`", file=sys.stderr)
        return 1
    if args.cmd == "reap":
        try:
            _check_slug(args.slug)
        except ValueError as exc:
            print(exc, file=sys.stderr)
            return 1
        reaped, error = reap(args.root, args.slug, args.keep)
        out = {"reaped": reaped}
        if error:
            out["error"] = error
        print(json.dumps(out))
        return 0
    if args.cmd == "tip":
        sha = branch_tip(args.root, args.branch)
        if not sha:
            print(f"{OPEN_FAILED}: cannot read branch {args.branch!r} in {args.root}", file=sys.stderr)
            return 1
        print(json.dumps({"branch": args.branch, "sha": sha}))
        return 0
    now = branch_tip(args.root, args.branch)
    if now and now == args.sha:
        print(json.dumps({"branch": args.branch, "sha": now}))
        return 0
    print(f"{ESCAPED}: {args.branch} moved from {args.sha[:12]} to {now[:12] or 'unreadable'} while the "
          "worker ran: it committed outside its worktree", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
