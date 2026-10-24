#!/usr/bin/env python3
"""seat_commit_guard.py — refuse a Claude session's commit mid-merge in a run's worktree.

design: seat-escalate-first 3.4 (B11, B13). `check(repo, env)` returns a one-line refusal, or
None to let the commit through. It refuses when ALL of these hold:

  1. `TP_DESIGN_RUN` is not `1` (the design run itself always passes);
  2. the committer is a Claude session: `CLAUDE_LAUNCHER_ROLE=seat` or `CLAUDECODE=1`
     (the operator's own terminal sets neither);
  3. `repo` is on `tp/<slug>` and that design's lock is orchestrator-held
     (`seat_scope.run_lock`; a human-owned worktree passes);
  4. a merge is in progress there (`MERGE_HEAD` exists) with something left to decide: a
     clean merge (no unmerged paths, and `git merge-tree --write-tree HEAD MERGE_HEAD`
     exits 0 with the tree the index holds, as `/tp-merge-from-main`'s `--no-commit
     --no-ff` leaves it) passes; a conflict the seat resolved by hand still makes
     merge-tree exit 1, and an old git or a merge-tree error keeps the refusal;
  5. no answered ruling unlocks this merge: kind `base-sync-hunk` or `scope-growth`, slug
     `<slug>`, front `at` not older than `MERGE_HEAD`'s mtime, and `ruling_file.answer_of`
     set and not the `stop-run` card pad. Rulings are read in the worktree and in the main
     checkout (the seat writes them there). One answer never turns the guard off for good:
     a merge aborted and redone after the answer starts a newer `MERGE_HEAD`.

`main` is the command line: exit 1 and one stderr line on a refusal, else 0; it fails open
(exit 0, one stderr line) on any internal error. The guard never merges, pushes or
writes (its `git write-tree` / `merge-tree` leave only unreferenced objects).
Stdlib only.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_SHARED = os.path.dirname(os.path.abspath(__file__))
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

import ruling_cli  # noqa: E402
import ruling_file  # noqa: E402
import seat_scope  # noqa: E402

UNLOCK_KINDS = ("base-sync-hunk", "scope-growth")
_BRANCH_PREFIX = "tp/"


def _git(repo, *args) -> str:
    """Stripped stdout of `git <args>` under `repo`; empty on any failure."""
    rc, out = seat_scope._default_run_git(list(args), repo)
    return out.strip() if rc == 0 else ""


def _run_git(top, *args):
    """(rc, stdout) of `git <args>` under `top`."""
    return seat_scope._default_run_git(list(args), top)


def _nothing_to_decide(top) -> bool:
    """True for a merge with no conflict left: no unmerged paths and a clean merge-tree
    whose tree is the index's. Fails closed: any git error or old git (merge-tree
    --write-tree needs 2.38) is False, so the caller keeps refusing."""
    rc, unmerged = _run_git(top, "ls-files", "-u")
    if rc != 0 or unmerged.strip():
        return False
    rc, merged = _run_git(top, "merge-tree", "--write-tree", "HEAD", "MERGE_HEAD")
    if rc != 0 or not merged.strip():
        return False
    rc, tree = _run_git(top, "write-tree")
    return rc == 0 and merged.split()[0] == tree.strip()


def _is_claude_session(env) -> bool:
    return env.get("CLAUDE_LAUNCHER_ROLE") == "seat" or env.get("CLAUDECODE") == "1"


def _merge_started(top):
    """The mtime of this worktree's `MERGE_HEAD` (when the merge started), else None."""
    line = _git(top, "rev-parse", "--git-path", "MERGE_HEAD")
    if not line:
        return None
    try:
        return os.path.getmtime(os.path.join(top, line))
    except OSError:
        return None


def _main_checkout(top):
    """The main checkout: the parent of the repository's common git dir, else None."""
    common = _git(top, "rev-parse", "--git-common-dir")
    if not common:
        return None
    return os.path.dirname(os.path.realpath(os.path.join(top, common)))


def _epoch(at):
    """A ruling front `at` (ISO 8601, `Z` for UTC) as epoch seconds, else None."""
    try:
        stamp = datetime.fromisoformat(str(at).replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.timestamp()


def _unlocks(root, slug, started) -> bool:
    """True when a ruling under `root` is answered (not `stop-run`) for `slug`'s merge."""
    for path in sorted((Path(root) / ruling_file.RULINGS_REL).glob("*.md")):
        try:
            parsed = ruling_file.parse(path)
        except (OSError, ValueError):
            continue  # an unreadable ruling file unlocks nothing
        front = parsed.get("front") or {}
        if front.get("kind") not in UNLOCK_KINDS or front.get("slug") != slug:
            continue
        at = _epoch(front.get("at"))
        # `at` has whole-second resolution, so compare it to the merge's whole second
        if at is None or at < int(started):
            continue
        label = ruling_file.answer_of(parsed)
        if label and label != ruling_cli.STOP_RUN["label"]:
            return True
    return False


def _refusal(slug) -> str:
    return (f"seat-commit-guard: refused — a merge is in progress in the design run's worktree "
            f"(tp/{slug}, orchestrator-held) and a Claude session that is not the run may not "
            "commit it; route the conflict through /tp-escalate (--kind base-sync-hunk for a "
            "deferred living-doc hunk, --kind scope-growth for a code conflict) and commit once "
            "its ruling is answered with a choice other than stop-run; a merge aborted and "
            "redone after the answer needs a new ruling; the design run itself passes "
            "(see skills/tp-run-full-design/run-safety.md)")


def check(repo, env):
    """The refusal line for a commit at `repo` under `env`, or None to allow it."""
    if env.get("TP_DESIGN_RUN") == "1":
        return None
    top = _git(repo, "rev-parse", "--show-toplevel")
    if not top:
        return None
    branch = _git(top, "symbolic-ref", "--short", "-q", "HEAD")
    slug = branch[len(_BRANCH_PREFIX):] if branch.startswith(_BRANCH_PREFIX) else ""
    if not slug or seat_scope.run_lock(top, slug) is None:
        return None
    started = _merge_started(top)
    if started is None or not _is_claude_session(env):
        return None
    if _nothing_to_decide(top):
        return None
    roots = [top]
    main_checkout = _main_checkout(top)
    if main_checkout and main_checkout != top:
        roots.append(main_checkout)
    if any(_unlocks(root, slug, started) for root in roots):
        return None
    return _refusal(slug)


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError(message)  # main reports it as one fail-open line


def main(argv=None, env=None) -> int:
    """0 to allow, 1 on a refusal (one stderr line); fail-open on any error."""
    try:
        parser = _Parser(prog="seat_commit_guard.py",
                         description="Refuse a seat commit mid-merge in a run worktree.")
        parser.add_argument("--repo", default=None, help="the repository (default: cwd)")
        args = parser.parse_args(argv)
        refusal = check(args.repo or os.getcwd(), os.environ if env is None else env)
    except Exception as exc:
        print("seat-commit-guard: %s: %s" % (type(exc).__name__, " ".join(str(exc).split())),
              file=sys.stderr)
        return 0
    if refusal:
        print(refusal, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
