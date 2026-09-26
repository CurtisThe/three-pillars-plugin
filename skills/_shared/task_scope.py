"""task_scope.py — the one shared plan-field predicate module.

design: local-implement-and-review

Used by the per-task eligibility table, `task_verify`, and the Tier 3.5 re-run so all
three agree on what a plan task's **Targets** field runs, which files its **File** field
allows, and which runner a repo resolves to. This module is the one entry point for
field grammar; the task block splitter is `tp-plan-audit/scripts/audit_plan.extract_tasks`.
The **Test** field is prose for humans and is never parsed (operator rulings on #165).

Split by responsibility, re-exported here: the Targets grammar in `task_targets`,
File-field parsing and `classify_path` in `task_scope_files`, runner resolution in
`task_scope_runner`, the archived-plan report in `task_scope_corpus`. Stdlib only: every
import is stdlib or a stdlib-only sibling.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

_SHARED = str(Path(__file__).resolve().parent)
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

from task_scope_files import (  # noqa: E402,F401 — re-exported public API
    classify_path,
    norm_path,
    parse_files,
)
from task_targets import NON_CANONICAL, parse_targets  # noqa: E402,F401 — re-exported
from task_scope_runner import (  # noqa: E402,F401 — re-exported public API
    RUNNER_BROKEN_RCS,
    pytest_config,
    resolve_runner,
    run_capture,
    runner_argv,
)

# --- Task blocks and status --------------------------------------------------------

# Never dispatched by the eligibility table.
EXCLUDED = frozenset({"Blocked", "Skipped", "Reversed"})
_STATUS_RE = re.compile(r"^\*\*Status\*\*:\s*(.*)$", re.M)
_PLAN_AUDIT_SCRIPTS = Path(__file__).resolve().parent.parent / "tp-plan-audit" / "scripts"


def _status_text(block) -> str:
    if isinstance(block, dict):
        status = (block.get("fields") or {}).get("Status")
        if status:
            return status.strip()
        block = block.get("raw") or ""
    m = _STATUS_RE.search(block or "")
    return m.group(1).strip() if m else ""


def task_status(block) -> str:
    """Leading word of a task's ``**Status**:`` line (``Done``, ``Blocked``, …) or ""."""
    m = re.match(r"[A-Za-z]+", _status_text(block))
    return m.group(0) if m else ""


def rerun_excluded(block) -> bool:
    """``EXCLUDED`` minus ``Skipped (pre-exists)``, whose "already passes" claim the
    Tier 3.5 re-run verifies rather than trusts."""
    if task_status(block) not in EXCLUDED:
        return False
    return not re.match(r"Skipped\s*\(pre-exists\)", _status_text(block))


def plan_tasks(plan_text: str) -> list[dict]:
    """The one task-block splitter: `audit_plan.extract_tasks` (not edited here)."""
    path = str(_PLAN_AUDIT_SCRIPTS)
    if path not in sys.path:
        sys.path.insert(0, path)
    import audit_plan  # noqa: E402 — in-repo, imported lazily

    return audit_plan.extract_tasks(plan_text)


def phase_tasks(plan_text: str, phase: int) -> list[dict]:
    """Task blocks of plan phase ``phase`` as split by `audit_plan.extract_tasks`."""
    return [t for t in plan_tasks(plan_text) if t.get("phase") == int(phase)]


def corpus_report(pattern: str) -> dict:
    """Parser counts over every plan matching ``pattern`` (see `task_scope_corpus`)."""
    import task_scope_corpus  # noqa: E402 — lazy: it imports this module

    return task_scope_corpus.corpus_report(pattern)


# --- Target files and the dirty-tree probe -----------------------------------------

# The repo-local git env a hook exports; dropped so `git -C <root>` targets <root>.
# A shipped mirror of the dev-only `git_env.GIT_REPO_ENV_VARS` (exactly `git rev-parse
# --local-env-vars`); parity pinned by test_task_scope_git_env_parity.py (dev-only).
_GIT_LOCAL_ENV = (
    "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_CONFIG", "GIT_CONFIG_PARAMETERS",
    "GIT_CONFIG_COUNT", "GIT_OBJECT_DIRECTORY", "GIT_DIR", "GIT_WORK_TREE",
    "GIT_IMPLICIT_WORK_TREE", "GIT_GRAFT_FILE", "GIT_INDEX_FILE", "GIT_NO_REPLACE_OBJECTS",
    "GIT_REPLACE_REF_BASE", "GIT_PREFIX", "GIT_SHALLOW_FILE", "GIT_COMMON_DIR",
)
_WORKTREES_PREFIX = ".claude/worktrees/"


def row_test_paths(row: dict) -> list[str]:
    """Every declared target file of an eligibility row (its ``test_paths``)."""
    return [str(p) for p in row.get("test_paths") or []]


def _git_env(**extra: str) -> dict:
    """``os.environ`` minus the repo-local git env, then ``extra``: the one scrub every
    shipped helper uses (``git_env`` itself is dev-only and never ships)."""
    env = {k: v for k, v in os.environ.items() if k not in _GIT_LOCAL_ENV}
    env.update(extra)
    return env


def dirty_outside(root, design_dir_rel: str) -> list[str]:
    """Uncommitted paths (``git status --porcelain -uall``) outside the design dir and
    outside ``.claude/worktrees/`` — the dispatcher's own lock/decisions writes and
    nested attempt dirs are not dirt."""
    out = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain", "-uall", "-z"],
        capture_output=True, text=True, check=True, env=_git_env(),
    ).stdout
    entries = out.split("\0")
    paths: list[str] = []
    i = 0
    while i < len(entries):
        entry = entries[i]
        i += 1
        if len(entry) < 4:
            continue
        paths.append(entry[3:])
        if entry[0] in "RC" or entry[1] in "RC":
            paths.append(entries[i])  # the rename/copy source follows its target
            i += 1
    design = norm_path(design_dir_rel or "").strip("/")
    keep = [p for p in paths
            if not p.startswith(_WORKTREES_PREFIX)
            and not (design and (p == design or p.startswith(design + "/")))]
    return sorted(set(keep))

