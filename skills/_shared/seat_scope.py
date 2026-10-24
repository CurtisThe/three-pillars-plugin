"""seat_scope.py — who is the seat, and the `seat-allow:` allow-list.

design: seat-escalate-first 2.1 (design.md Phase 2). Stdlib only.

`is_seat(cwd, env, run_git=None)` — True when the session is the orchestration seat:
  1. `TP_DESIGN_RUN=1` is never a seat, whatever its role (a direct launch on a launcher
     without the `run` role carries `CLAUDE_LAUNCHER_ROLE=seat` and keeps the run rules);
  2. `CLAUDE_LAUNCHER_ROLE=seat` is a seat anywhere;
  3. else the fallback: `cwd` is in the repo's base checkout (the main worktree), on the
     default branch, and another existing worktree on `tp/<slug>` holds a **live** run
     (`run_lock(path, slug)` is not None).

`run_lock(path, slug)` — the parsed design lock under `three-pillars-docs/tp-designs/<slug>/`
(else `completed-tp-designs/<slug>/`, where Tier 5.6 archives it), only when its `owner`
starts `orchestrator:` (the discriminator `escalate_first_hook._scope` uses); else None.

`ALLOW_KINDS` / `allowed(text)` — the audited `seat-allow: <kind>` tags that let a seat
card through with no ruling.

`worktree_of(cwd, slug, run_git=None)` — the linked worktree on `tp/<slug>`, else None
(design: fleet-seat-drive-gaps 1.7: the seat reads a run's ruling from there).

`run_git` is an injectable `(args, cwd) -> (returncode, stdout)` like `default_branch`'s.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

_SHARED = os.path.dirname(os.path.abspath(__file__))
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

import default_branch  # noqa: E402

ALLOW_KINDS = ("session-restore", "first-run-preflight", "fleet-scope", "promote-confirm",
               "session-clear", "post-merge-teardown", "worktree-confirm", "migrate-confirm")
_ALLOW = re.compile(r"(?m)^seat-allow: (%s)\s*$" % "|".join(map(re.escape, ALLOW_KINDS)))
_ORCHESTRATOR = "orchestrator:"
_TP_REF = "refs/heads/tp/"


def allowed(text) -> bool:
    """True when `text` carries a `seat-allow: <kind>` line of an allowed kind."""
    return isinstance(text, str) and _ALLOW.search(text) is not None


def run_lock(path, slug):
    """The parsed orchestrator-held lock of design `slug` under `path`, else None."""
    base = Path(path) / "three-pillars-docs"
    lock_path = base / "tp-designs" / slug / "lock.json"
    if not lock_path.is_file():
        lock_path = base / "completed-tp-designs" / slug / "lock.json"
    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(lock, dict):
        return None
    owner = lock.get("owner")
    if not (isinstance(owner, str) and owner.startswith(_ORCHESTRATOR)):
        return None
    return lock


def _clean_env():
    """os.environ minus the repo-local git env that would redirect `git -C <cwd>`."""
    from escalate_first_hook import _REPO_ENV  # lazy: that module imports this one

    return {k: v for k, v in os.environ.items() if k not in _REPO_ENV}


def _default_run_git(args, cwd):
    """The production `run_git`: `git <args>` under `cwd`; failure to run is rc 1."""
    try:
        proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                              stdin=subprocess.DEVNULL, env=_clean_env(), timeout=10)
    except (OSError, subprocess.SubprocessError):
        return 1, ""
    return proc.returncode, proc.stdout


def _dir(git, cwd, flag):
    """`git rev-parse <flag>` resolved against `cwd` (git prints it relative to cwd)."""
    rc, out = git(["rev-parse", flag], cwd)
    line = out.strip()
    if rc != 0 or not line:
        return None
    return os.path.realpath(os.path.join(str(cwd), line))


def _is_base_on_default(git, cwd) -> bool:
    """cwd is in the main worktree and on the resolved default branch."""
    git_dir, common = _dir(git, cwd, "--git-dir"), _dir(git, cwd, "--git-common-dir")
    if git_dir is None or git_dir != common:
        return False
    rc, out = git(["symbolic-ref", "--short", "-q", "HEAD"], cwd)
    branch = out.strip()
    if rc != 0 or not branch:
        return False
    try:
        return branch == default_branch.resolve_default_branch(cwd, run_git=git)
    except default_branch.DefaultBranchError:
        return False


def _design_worktrees(git, cwd):
    """(path, slug) of every linked worktree on `refs/heads/tp/<slug>`."""
    rc, out = git(["worktree", "list", "--porcelain"], cwd)
    if rc != 0:
        return
    blocks = out.split("\n\n")
    for block in blocks[1:]:  # the first entry is the main worktree itself
        path = branch = None
        for line in block.splitlines():
            if line.startswith("worktree "):
                path = line[len("worktree "):]
            elif line.startswith("branch " + _TP_REF):
                branch = line[len("branch " + _TP_REF):]
        if path and branch:
            yield path, branch


def is_seat(cwd, env, run_git=None) -> bool:
    """True when the session at `cwd` with `env` is the orchestration seat."""
    if env.get("TP_DESIGN_RUN") == "1":
        return False
    if env.get("CLAUDE_LAUNCHER_ROLE") == "seat":
        return True
    git = run_git or _default_run_git
    if not _is_base_on_default(git, cwd):
        return False
    return any(os.path.isdir(path) and run_lock(path, slug) is not None
               for path, slug in _design_worktrees(git, cwd))


def worktree_of(cwd, slug, run_git=None):
    """The path of the linked worktree on `refs/heads/tp/<slug>`, else None."""
    git = run_git or _default_run_git
    for path, branch in _design_worktrees(git, cwd):
        if branch == slug:
            return path
    return None
