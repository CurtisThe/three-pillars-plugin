"""attempt_start_check.py — worker start-of-task sanity check for one attempt.

design: hybrid-routing-hardening (Task 4.1)

A spawned task-worker's very first move must be to confirm it is standing in
the right place before it touches anything: the exact attempt directory, a
real git work tree, that directory's own toplevel, the expected attempt
branch, and HEAD still at the expected base (no stray prior commit). This
module performs exactly those five checks, in order, and stops at the first
one that fails — it never inspects the rest once one has failed.

Passes silently (exit 0, no output) iff all five checks hold. On the first
failing check it prints exactly one line of JSON to stdout and exits 1:
``{"task_id": ID, "sha": null, "claimed": "aborted-cwd", "check": "<name>",
"expected": "...", "actual": "..."}`` — the same shape a worker's own
abort-early reply uses, so a dispatcher can treat this script's stdout as
that reply verbatim.

No writes: this script never touches git state or the filesystem beyond
reading it. Every git call is read-only (`rev-parse`) and its returncode is
checked explicitly — never `check=True`, since a non-zero returncode from
git is exactly a check failing, not an exceptional condition. A missing
`git` binary or a `cwd` that does not exist is likewise a check failing
(OSError caught), not a crash.

stdlib-only.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys


def _real(path: str) -> str:
    return os.path.realpath(path)


def _run_git(cwd: str, args: list[str]) -> subprocess.CompletedProcess | None:
    """Run ``git *args`` with ``cwd=cwd``; ``None`` if git could not even start."""
    try:
        result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    except OSError:
        return None
    return result


def _fail(task_id: str, check: str, expected: str, actual: str) -> int:
    print(json.dumps({
        "task_id": task_id, "sha": None, "claimed": "aborted-cwd",
        "check": check, "expected": expected, "actual": actual,
    }))
    return 1


def _describe(result: subprocess.CompletedProcess | None) -> str:
    if result is None:
        return "git: command not found"
    if result.returncode != 0:
        return f"returncode {result.returncode}: {result.stderr.strip()}"
    return result.stdout.strip()


def run_checks(task_id: str, attempt_dir: str, branch: str, base_sha: str) -> int:
    """The five ordered checks; returns 0 (silent pass) or 1 (one JSON line)."""
    d_real = _real(attempt_dir)

    # 1. cwd
    cwd_real = _real(os.getcwd())
    if cwd_real != d_real:
        return _fail(task_id, "cwd", d_real, cwd_real)

    # 2. git: attempt_dir is inside a git work tree
    result = _run_git(attempt_dir, ["rev-parse", "--is-inside-work-tree"])
    if result is None or result.returncode != 0 or result.stdout.strip() != "true":
        return _fail(task_id, "git", "true", _describe(result))

    # 3. toplevel: attempt_dir IS the work tree's own toplevel
    result = _run_git(attempt_dir, ["rev-parse", "--show-toplevel"])
    if result is None or result.returncode != 0:
        return _fail(task_id, "toplevel", d_real, _describe(result))
    top_real = _real(result.stdout.strip())
    if top_real != d_real:
        return _fail(task_id, "toplevel", d_real, top_real)

    # 4. branch: HEAD is on the expected attempt branch (not detached)
    result = _run_git(attempt_dir, ["rev-parse", "--abbrev-ref", "HEAD"])
    if result is None or result.returncode != 0:
        return _fail(task_id, "branch", branch, _describe(result))
    actual_branch = result.stdout.strip()
    if actual_branch != branch:
        return _fail(task_id, "branch", branch, actual_branch)

    # 5. base: HEAD is still at the expected base SHA (no commit yet)
    result = _run_git(attempt_dir, ["rev-parse", "HEAD"])
    if result is None or result.returncode != 0:
        return _fail(task_id, "base", base_sha, _describe(result))
    actual_sha = result.stdout.strip()
    if actual_sha != base_sha:
        return _fail(task_id, "base", base_sha, actual_sha)

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--task", required=True, dest="task_id")
    parser.add_argument("--attempt-dir", required=True, dest="attempt_dir")
    parser.add_argument("--branch", required=True)
    parser.add_argument("--base", required=True, dest="base_sha")
    args = parser.parse_args(argv)

    return run_checks(args.task_id, args.attempt_dir, args.branch, args.base_sha)


if __name__ == "__main__":
    sys.exit(main())
