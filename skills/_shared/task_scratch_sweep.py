"""task_scratch_sweep.py — sweep one design's leftover re-run and red-at-base scratch.

design: local-implement-and-review (impl-audit-1 #5)

The Tier 3.5 re-run (``tp-rerun-<slug>-<sha8>-<hex6>`` on ``tp-rerun/<slug>-<sha8>-<hex6>``)
and red-at-base (``tp-redbase-<slug>-<task>-<hex8>`` on ``tp-redbase/<slug>/<task>-<hex8>``)
remove their scratch worktree and branch in ``finally`` — which a SIGKILL (a Bash
timeout) skips. ``task_verify.py sweep`` runs this after the attempt sweep, so the
dispatcher preflight, the orchestrator's Cleanup and the ``/tp-design-complete``
preflight clear them too.

Only this slug's names are touched; a worktree is removed only when it sits directly
under a scratch parent (``scratch_root.scan_parents``: ``.tp-scratch/``, then the legacy
``.claude/worktrees/``); a branch still checked out elsewhere survives
(``git branch -D`` refuses). Stdlib only.

**Assumes no live re-run or red-at-base for the slug** (impl-audit-2 #8). Unlike the
attempt sweep, which never touches a live owner, it removes every matching scratch
without checking whether its run is still going. That holds only because its callers
are serial with those runs: the dispatcher preflight runs before any attempt (red-at-base
runs inside ``check``), the orchestrator's Cleanup runs after Tier 3.5 returned, the
``/tp-design-complete`` preflight runs after the run, and one lock holder owns a design.
A new caller that can overlap a live run must not call it.
"""
from __future__ import annotations

import os
import re
import shutil

import scratch_root
import task_attempts


def _patterns(slug: str) -> tuple[re.Pattern, re.Pattern]:
    """The branch and folder names for ``slug``. A red-at-base task part never holds a
    ``-`` (``task_verify_red_base.task_part``), so the folder pattern cannot read another
    slug that only shares the prefix (``demo`` vs ``demo-x``) as this one (impl-audit-2 #9)."""
    s = re.escape(slug)
    branch = re.compile(rf"^(?:tp-rerun/{s}-[0-9a-f]{{8}}-[0-9a-f]{{6}}"
                        rf"|tp-redbase/{s}/[\w.]+-[0-9a-f]{{8}})$")
    dirname = re.compile(rf"^(?:tp-rerun-{s}-[0-9a-f]{{8}}-[0-9a-f]{{6}}"
                         rf"|tp-redbase-{s}-[\w.]+-[0-9a-f]{{8}})$")
    return branch, dirname


def _registered(top: str) -> list[tuple[str, str]]:
    """``(realpath, branch short name)`` for every registered worktree."""
    out, path = [], None
    for line in task_attempts._out(top, "worktree", "list", "--porcelain").splitlines():
        if line.startswith("worktree "):
            path = os.path.realpath(line[len("worktree "):])
        elif line.startswith("branch refs/heads/") and path:
            out.append((path, line[len("branch refs/heads/"):]))
    return out


def sweep(root, slug: str) -> dict:
    """Remove this slug's leftover scratch → ``{worktrees: [...], branches: [...]}``.
    Only when no re-run / red-at-base of the slug is live (see the module docstring)."""
    top = task_attempts.toplevel(root)
    parents = [os.path.realpath(p) for p in scratch_root.scan_parents(top)]
    branch_re, dir_re = _patterns(task_attempts._safe(slug))
    removed: list[str] = []
    task_attempts._git(top, "worktree", "prune", check=False)
    for path, branch in _registered(top):
        if os.path.dirname(path) in parents and branch_re.match(branch):
            task_attempts._git(top, "worktree", "remove", "--force", "--force", path,
                               check=False)
            removed.append(path)
    live = {p for p, _b in _registered(top)}
    for parent in parents:
        for name in sorted(os.listdir(parent)) if os.path.isdir(parent) else []:
            path = os.path.join(parent, name)
            if dir_re.match(name) and path not in live and os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
                removed.append(path)
    task_attempts._git(top, "worktree", "prune", check=False)
    deleted: list[str] = []
    listed = task_attempts._out(top, "branch", "--list", "--format=%(refname:short)",
                                "tp-rerun/*", "tp-redbase/*").split()
    for branch in listed:
        if branch_re.match(branch) and task_attempts._git(
                top, "branch", "-D", branch, check=False).returncode == 0:
            deleted.append(branch)
    return {"worktrees": sorted(set(removed)), "branches": deleted}
