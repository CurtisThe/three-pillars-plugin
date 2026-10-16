"""test_scratch_root_readers.py — the readers that recognise `.tp-scratch/`.

design: launch-role-precedence 3.2

Four readers take the scratch base from `scratch_root`, so a `tp-attempt-*` worktree under
`.tp-scratch/` is never the default-branch root, never dirt, never a recorded baseline root,
and the cheap-watch orphan scan reads the new parent. The legacy `.claude/worktrees/` parent
keeps every behaviour it has today: agent isolation worktrees stay transient in the baseline
and stay excluded from the guard's default-branch classification.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import posthoc_rows  # noqa: E402
import scratch_root  # noqa: E402
import task_scope  # noqa: E402
from task_scope import _git_env as clean_git_env  # noqa: E402 — the shipped scrub

import cheap_route  # noqa: E402
import posthoc_baseline  # noqa: E402
from worktree_isolation_guard import (  # noqa: E402
    _is_default_branch_root,
    assert_own_worktree,
    is_shared_with_orchestrator,
)

_IDENTITY = {
    "GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture@test",
    "GIT_COMMITTER_NAME": "fixture", "GIT_COMMITTER_EMAIL": "fixture@test",
}
_DD = "three-pillars-docs/tp-designs/demo"
_UNTIL = "2026-10-01T22:00:00Z"
_TELEMETRY = "dispatch-telemetry.ndjson"


# --- worktree_isolation_guard: the path-shape fallback --------------------------------

@pytest.mark.parametrize("toplevel,branch,is_bare,expected", [
    # A tp-attempt worktree under the new scratch parent is its own isolated seat.
    ("/r/.tp-scratch/tp-attempt-s-1-ab", "", False, False),
    # The main checkout stays the seat, branchless or bare.
    ("/r", "", False, True),
    ("/r", "", True, True),
    # Agent isolation worktrees keep their legacy exclusion, unchanged.
    ("/r/.claude/worktrees/agent-a1", "", False, False),
    # The branch test runs first, as today: a default branch at a scratch path is the seat.
    ("/r/.tp-scratch/tp-attempt-s-1-ab", "master", False, True),
    # A tp-provisioned worktree is still not the seat.
    ("/r/repo-wt/demo", "", False, False),
])
def test_is_default_branch_root_knows_the_scratch_parent(toplevel, branch, is_bare, expected):
    assert _is_default_branch_root(toplevel, branch, is_bare) is expected


def test_assert_own_worktree_passes_a_scratch_attempt_worktree():
    """A commit from a `.tp-scratch/tp-attempt-*` worktree (branchless, so only the path
    shape classifies it) is NOT the shared default-branch root — the guard's case (5)."""
    porcelain = """\
worktree /home/user/repo
HEAD abc123
bare

worktree /home/user/repo-wt/x
HEAD def456
branch refs/heads/tp/x

worktree /home/user/repo/.tp-scratch/tp-attempt-x-1.1-abc
HEAD ghi789
detached

"""
    ok, msg = assert_own_worktree(
        cwd="/home/user/repo/.tp-scratch/tp-attempt-x-1.1-abc",
        worktree_porcelain=porcelain,
        current_branch="",
    )
    assert ok is True, f"scratch attempt worktree must PASS (not a default-branch root): {msg}"
    assert msg == ""


def test_is_shared_with_orchestrator_is_only_the_containment_check():
    """Untouched by the scratch move: the cwd-inside-worktree check, unchanged for a
    scratch path — inside its own toplevel is not shared, outside it is."""
    scratch = "/r/.tp-scratch/tp-attempt-s-1-ab"
    assert is_shared_with_orchestrator(cwd=scratch, worktree_toplevel=scratch) is False
    assert is_shared_with_orchestrator(cwd=scratch, worktree_toplevel="/r") is False
    assert is_shared_with_orchestrator(cwd="/r", worktree_toplevel=scratch) is True


# --- task_scope.dirty_outside ---------------------------------------------------------

def _git(*args: str, cwd: Path) -> str:
    env = clean_git_env(**_IDENTITY)
    out = subprocess.run(["git", *args], cwd=str(cwd), env=env,
                         capture_output=True, text=True, check=True)
    return out.stdout


def _write(root: Path, rel: str, text: str = "x\n") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_dirty_outside_ignores_the_scratch_parent_and_still_the_legacy_one(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git("init", "-q", "-b", "main", cwd=repo)
    _write(repo, "src/keep.py")
    _git("add", "-A", cwd=repo)
    _git("commit", "-q", "-m", "init", cwd=repo)

    _write(repo, ".tp-scratch/tp-attempt-demo-1.1-abc/skills/x.py")
    _write(repo, ".claude/worktrees/tp-attempt-demo-1.2-def/skills/y.py")
    _write(repo, "src/y.py")
    assert task_scope.dirty_outside(repo, _DD) == ["src/y.py"]


# --- posthoc_baseline: transient roots -----------------------------------------------

def _row(task_id) -> dict:
    return {"task_id": task_id, "role": "task", "rung": "local-medium", "outcome": "PASS",
            "served_by": "local", "started_at": "2026-10-01T10:00:00.000000Z"}


def _put(root, design, rows) -> None:
    path = Path(root) / "three-pillars-docs" / "tp-designs" / design
    path.mkdir(parents=True, exist_ok=True)
    with (path / _TELEMETRY).open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")


def test_manifest_drops_a_scratch_root_and_still_drops_an_agent_one(tmp_path):
    base = tmp_path.resolve()
    main = base / "main"
    scratch = main / scratch_root.SCRATCH_DIR / "tp-attempt-demo-1.1-abc"
    agent = main / ".claude" / "worktrees" / "agent-x"
    _put(main, "alpha", [_row("1.1")])
    _put(scratch, "attempt", [_row("3.3")])
    _put(agent, "nested", [_row("2.2")])
    roots = [main, scratch, agent]
    rows = posthoc_rows.load(main, until=_UNTIL, roots=roots,
                             env={"XDG_STATE_HOME": str(base / "state")})
    m = posthoc_baseline.manifest(rows, roots)
    assert m["roots"] == [str(main)]
    assert m["per_design"] == {"alpha": 1, "attempt": 1, "nested": 1}  # rows still read


# --- cheap_route: the cheap-watch scan ---------------------------------------------

def test_cheap_watch_is_under_the_scratch_parent():
    assert cheap_route.CHEAP_WATCH == Path(scratch_root.SCRATCH_DIR) / "cheap-watch"
    assert ".claude" not in cheap_route.CHEAP_WATCH.parts
