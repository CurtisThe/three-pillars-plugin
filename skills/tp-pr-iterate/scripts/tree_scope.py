"""tree_scope — what the /tp-pr-iterate loop counts as its tree.

design: iterate-convergence-budget (Task 5.1, Q1)

The single home of the loop-excluded pathspecs. The loop's own bookkeeping — the
design docs (`three-pillars-docs/**`, where a terminal flush leaves
`decisions.md` modified) and the repo config (`.three-pillars/config.json`, where
the operator raises a budget limit before a re-run) — never counts as dirty
tracked code and never lands in a fix commit's paths.

- `tracked_dirty(cwd)`: tracked code differs from HEAD (untracked files ignored).
- `untracked_snapshot(cwd)` / `derive_fix_paths(cwd, before)`: the mechanically
  derived paths of an inline fix — modified tracked code plus untracked files not
  in the pre-edit snapshot.
- `check_fix_paths(derived, claimed)`: `"ok"` iff the derived set equals the
  fixer's own claimed list, else `"fix-paths-mismatch"`.

Stdlib only; git runs as an argv list, never through a shell.
"""

from __future__ import annotations

import subprocess

LOOP_EXCLUDES = (":(exclude)three-pillars-docs", ":(exclude).three-pillars/config.json")

OK = "ok"
MISMATCH = "fix-paths-mismatch"


class TreeScopeError(RuntimeError):
    """git could not be run, or exited non-zero."""


def _git(cwd, *args) -> str:
    argv = ["git", "-C", str(cwd), *args]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                              timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise TreeScopeError(f"git {args[0]} failed: {exc}") from exc
    if proc.returncode != 0:
        raise TreeScopeError(f"git {args[0]} exited {proc.returncode}: "
                             f"{proc.stderr.strip()[:200]}")
    return proc.stdout


def _split_z(out: str) -> list[str]:
    return [p for p in out.split("\0") if p]


def tracked_dirty(cwd) -> bool:
    """True iff tracked code (outside the loop excludes) differs from HEAD."""
    out = _git(cwd, "status", "--porcelain", "--untracked-files=no", "--", ".", *LOOP_EXCLUDES)
    return bool(out.strip())


def untracked_snapshot(cwd) -> set[str]:
    """Untracked, non-ignored files outside the loop excludes (paths relative to `cwd`)."""
    return set(_split_z(_git(cwd, "ls-files", "--others", "--exclude-standard", "-z",
                             "--", ".", *LOOP_EXCLUDES)))


def derive_fix_paths(cwd, untracked_before) -> list[str]:
    """Modified tracked code plus untracked files new since `untracked_before`, sorted."""
    modified = set(_split_z(_git(cwd, "diff", "--name-only", "--relative", "-z", "HEAD",
                                 "--", ".", *LOOP_EXCLUDES)))
    new = untracked_snapshot(cwd) - set(untracked_before or ())
    return sorted(modified | new)


def check_fix_paths(derived, claimed) -> str:
    """`"ok"` iff the derived and claimed path sets are equal (order-insensitive)."""
    return OK if set(derived) == set(claimed) else MISMATCH
