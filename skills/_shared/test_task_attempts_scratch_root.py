"""Tests for task_attempts.py — attempt worktrees live under `.tp-scratch/`.

design: launch-role-precedence (Task 3.6). `ATTEMPT_PARENT` is the scratch base
(`scratch_root.SCRATCH_DIR`, no `.claude` component), so a new attempt dir is
`<root>/.tp-scratch/tp-attempt-<slug>-<task>-<nonce>`, and `EXCLUDE_LINE` is
`scratch_root.ignore_line()` — the local `info/exclude` line, written once however many
attempts open. The rm-safety check (`removable`) accepts a direct `tp-attempt-*` child of
either the new parent or the legacy `.claude/worktrees` one, so residue from before the
move is still reaped by the attempt sweep, while an agent worktree
(`.claude/worktrees/agent-x`) or a `tp-attempt-*` anywhere else is refused. Real tmp repos.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import scratch_root
import task_attempts
from attempt_fixture import DD, SLUG, git, make_seat

LEGACY_NAME = "tp-attempt-demo-1.1-0a0b0c0d"
LEGACY_BRANCH = "tp-attempt/demo/1.1-0a0b0c0d"


def _record(att: dict) -> dict:
    return json.loads(Path(task_attempts.record_path(att)).read_text(encoding="utf-8"))


def _legacy_attempt_wt(wt: Path) -> Path:
    """A hand-made `.claude/worktrees/tp-attempt-*` worktree, as before the move."""
    path = wt / scratch_root.LEGACY_DIR / LEGACY_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    git(wt, "worktree", "add", "-q", "-b", LEGACY_BRANCH, str(path), "HEAD")
    return path


def test_attempt_parent_is_the_scratch_base() -> None:
    assert task_attempts.ATTEMPT_PARENT == scratch_root.SCRATCH_DIR == ".tp-scratch"
    assert ".claude" not in Path(task_attempts.ATTEMPT_PARENT).parts
    assert task_attempts.EXCLUDE_LINE == scratch_root.ignore_line() == "/.tp-scratch/"


def test_open_attempt_dir_is_under_the_scratch_base(tmp_path) -> None:
    _seat, wt = make_seat(tmp_path)
    att = task_attempts.open_attempt(wt, "1.1", DD)
    adir = Path(att["attempt_dir"])
    assert adir.parent == wt / ".tp-scratch"
    assert adir.name.startswith(f"tp-attempt-{SLUG}-1.1-")
    assert adir.is_dir()
    assert _record(att)["attempt_dir"] == str(adir)


def test_info_exclude_writes_the_scratch_line_once(tmp_path) -> None:
    _seat, wt = make_seat(tmp_path)
    for task in ("1.1", "1.2"):
        task_attempts.open_attempt(wt, task, DD)
    common = Path(git(wt, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    lines = (common / "info" / "exclude").read_text(encoding="utf-8").splitlines()
    assert lines.count("/.tp-scratch/") == 1
    assert lines.count("/.claude/worktrees/") == 0


def test_removable_accepts_a_direct_child_of_either_parent(tmp_path) -> None:
    _seat, wt = make_seat(tmp_path)
    att = task_attempts.open_attempt(wt, "1.1", DD)
    assert task_attempts.removable(att) is True
    legacy = _legacy_attempt_wt(wt)
    assert task_attempts.removable({**_record(att), "attempt_dir": str(legacy)}) is True


def test_removable_refuses_any_other_path(tmp_path) -> None:
    _seat, wt = make_seat(tmp_path)
    att = task_attempts.open_attempt(wt, "1.1", DD)
    rec = _record(att)
    refused = [wt / scratch_root.LEGACY_DIR / "agent-x",              # agent isolation worktree
               wt / ".tp-scratch" / "child-spawn" / "tp-attempt-x",    # not a direct child
               wt / "src" / "tp-attempt-x",                            # not under a scratch parent
               wt.parent / "outside" / "tp-attempt-x"]                 # not under the owner
    for path in refused:
        path.mkdir(parents=True, exist_ok=True)
        assert task_attempts.removable({**rec, "attempt_dir": str(path)}) is False, path


def test_sweep_reaps_an_attempt_left_under_the_legacy_parent(tmp_path) -> None:
    """Residue from before the move: the record's `attempt_dir` is a direct `tp-attempt-*`
    child of `.claude/worktrees/`, so the attempt sweep still removes dir + branch."""
    _seat, wt = make_seat(tmp_path)
    att = task_attempts.open_attempt(wt, "1.1", DD)
    legacy = wt / scratch_root.LEGACY_DIR / Path(att["attempt_dir"]).name
    legacy.parent.mkdir(parents=True, exist_ok=True)
    git(wt, "worktree", "move", att["attempt_dir"], str(legacy))
    task_attempts._write_record({**_record(att), "attempt_dir": str(legacy)})
    out = task_attempts.sweep(wt, SLUG)
    assert out["discarded"] == [att["attempt_id"]] and out["log"] == []
    assert not legacy.exists()
    assert att["branch"] not in git(wt, "branch", "--list").split()
