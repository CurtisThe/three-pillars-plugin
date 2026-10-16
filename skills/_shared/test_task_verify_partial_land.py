"""test_task_verify_partial_land.py — ``sweep`` undoes a range land that died mid-range.

design: fragile-test-prevention (stages §Part C1, "A crash mid-range"; phase 4)

``land`` cherry-picks ``base..sha`` (the red, then the green), so a crash between the two
leaves a red-only commit on the dispatcher, with or without sequencer state behind it.
``sweep`` of an own ``landing`` record whose tip is not reached aborts a cherry-pick left in
progress, resets the dispatcher to ``pre_land_head`` and discards the attempt, so the task
re-runs and the next land is not refused. A dead owner's partial land is only logged.
Oracle: ``example`` — each case is a concrete crash shape built in a real tmp repo
(``attempt_fixture``, M23); every assertion reads git state or the sweep result fields.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

import task_attempts
import task_verify
from attempt_fixture import DD, IDENTITY, agent_worktree, branches, commit, commit_pair, \
    git, make_seat

RED = {"skills/test_a.py": "def test_a():\n    assert True\n"}
GREEN = {"skills/a.py": "A = 2\n"}


@pytest.fixture
def identity(monkeypatch):
    """A committer identity for the cherry-picks the tests (and ``land``) run."""
    for key, value in IDENTITY.items():
        monkeypatch.setenv(key, value)


def _head(repo: Path) -> str:
    return git(repo, "rev-parse", "HEAD")


def _git_path(repo: Path, name: str) -> Path:
    return Path(git(repo, "rev-parse", "--path-format=absolute", "--git-path", name))


def _in_progress(repo: Path) -> bool:
    return any(_git_path(repo, name).exists() for name in ("CHERRY_PICK_HEAD", "sequencer"))


def _landing(att: dict, sha: str, pre: str) -> None:
    """The record ``task_verify.land`` writes before it lands the range."""
    task_attempts._write_record({**att, "status": "landing", "commit_sha": sha,
                                 "pre_land_head": pre})


def _crashed(wt: Path, task: str = "1.1", files=(RED, GREEN), *,
             dispatcher_moves: bool = False) -> tuple:
    """An own attempt with a red/green pair, ``landing``, and the dispatcher at ``pre``
    → ``(att, red, green, pre)``. The land itself is left to the caller (the crash)."""
    att = task_attempts.open_attempt(wt, task, DD)
    red, green = commit_pair(Path(att["attempt_dir"]), *files)
    if dispatcher_moves:
        commit(wt, {"skills/other.py": "O = 1\n"}, "dispatcher moved on")
    pre = _head(wt)
    _landing(att, green, pre)
    return att, red, green, pre


def _assert_clean_and_gone(wt: Path, att: dict, pre: str, out: dict) -> None:
    assert _head(wt) == pre
    assert not _in_progress(wt)
    assert git(wt, "status", "--porcelain") == ""
    assert f"partial-land reset: {att['attempt_id']}" in out["log"]
    assert out["discarded"] == [att["attempt_id"]] and out["landed"] == []
    assert att["branch"] not in branches(wt) and not os.path.exists(att["attempt_dir"])
    assert not os.path.exists(task_attempts.record_path(att))


def _following_land_succeeds(wt: Path) -> None:
    """A new attempt lands by range cherry-pick after the dispatcher moved on: it is
    refused while a cherry-pick is in progress, and lands both commits in order."""
    att = task_attempts.open_attempt(wt, "1.2", DD)
    red, green = commit_pair(Path(att["attempt_dir"]), {"skills/test_b.py": "T = 1\n"},
                             {"skills/b.py": "B = 2\n"})
    commit(wt, {"skills/moved.py": "M = 1\n"}, "dispatcher moved on")
    task_attempts._write_record({**att, "check": {"verdict": "PASS", "checked_sha": green,
                                                  "rung": "opus"}})
    out = task_verify.land(att)
    assert (out["exit"], out["method"]) == (0, "cherry-pick"), out["reason"]
    landed = git(wt, "rev-list", "--reverse", "-2", "HEAD").split()
    assert [git(wt, "show", "--name-only", "--format=", sha) for sha in landed] == [
        "skills/test_b.py", "skills/b.py"]


def test_sweep_resets_a_red_only_land(tmp_path, identity):
    """Crash after the red cherry-pick, no sequencer state: no red-only commit remains."""
    _seat, wt = make_seat(tmp_path)
    att, red, _green, pre = _crashed(wt, dispatcher_moves=True)
    git(wt, "cherry-pick", red)
    assert _head(wt) != pre and not _in_progress(wt)

    out = task_attempts.sweep(wt, "demo")

    _assert_clean_and_gone(wt, att, pre, out)
    _following_land_succeeds(wt)


def test_sweep_aborts_a_cherry_pick_left_in_progress(tmp_path, identity):
    """The green conflicts mid-range: the red is committed, ``CHERRY_PICK_HEAD`` and the
    sequencer are left behind, and only an abort lets the next land run."""
    _seat, wt = make_seat(tmp_path)
    att = task_attempts.open_attempt(wt, "1.1", DD)
    _red, green = commit_pair(Path(att["attempt_dir"]), RED, GREEN)
    commit(wt, {"skills/a.py": "A = 3\n"}, "dispatcher edits a")  # the green conflicts
    pre = _head(wt)
    _landing(att, green, pre)
    git(wt, "cherry-pick", f"{att['base_sha']}..{green}", check=False)
    assert _in_progress(wt) and _head(wt) != pre

    out = task_attempts.sweep(wt, "demo")

    _assert_clean_and_gone(wt, att, pre, out)
    _following_land_succeeds(wt)


def test_sweep_quits_a_sequencer_it_cannot_abort(tmp_path, identity):
    """A sequencer whose state ``--abort`` cannot use is dropped (``--quit``) and the
    red-only commit is still reset."""
    _seat, wt = make_seat(tmp_path)
    att, red, _green, pre = _crashed(wt, dispatcher_moves=True)
    git(wt, "cherry-pick", red)
    seq = _git_path(wt, "sequencer")
    seq.mkdir()
    (seq / "head").write_text("not-a-commit\n", encoding="utf-8")
    (seq / "todo").write_text("pick 0000000 lost\n", encoding="utf-8")

    out = task_attempts.sweep(wt, "demo")

    _assert_clean_and_gone(wt, att, pre, out)


def test_sweep_only_logs_a_dead_owners_partial_land(tmp_path, identity):
    """A dead owner's dispatcher branch keeps the red-only commit: logged, never reset."""
    seat, wt = make_seat(tmp_path)
    dead_root = agent_worktree(seat, "agent-dead")
    att = task_attempts.open_attempt(dead_root, "1.1", DD)
    red, green = commit_pair(Path(att["attempt_dir"]), RED, GREEN)
    commit(dead_root, {"skills/other.py": "O = 1\n"}, "dispatcher moved on")
    _landing(att, green, _head(dead_root))
    git(dead_root, "cherry-pick", red)
    tip = _head(dead_root)
    shutil.rmtree(dead_root)  # the owner's worktree is gone; its branch keeps the land

    out = task_attempts.sweep(wt, "demo")

    assert f"partial-land: {att['branch']}" in out["log"]
    assert not any(line.startswith("partial-land reset") for line in out["log"])
    assert git(seat, "rev-parse", "candidate/demo/single") == tip  # never reset
    assert out["discarded"] == [att["attempt_id"]] and out["landed"] == []
    assert att["branch"] not in branches(seat)


def test_sweep_leaves_a_completed_land_and_an_unstarted_one_alone(tmp_path, identity):
    """Only a partial range is undone: a fully landed pair is reported ``landed`` with
    both commits kept, and a land that never began resets nothing and logs nothing."""
    _seat, wt = make_seat(tmp_path)
    done, _red, green, _pre = _crashed(wt, dispatcher_moves=True)
    git(wt, "cherry-pick", f"{done['base_sha']}..{green}")
    landed_head = _head(wt)
    other = ({"skills/test_c.py": "T = 1\n"}, {"skills/c.py": "C = 1\n"})
    unstarted, _r, _g, _p = _crashed(wt, "1.2", other)  # pre_land_head == HEAD, none picked

    out = task_attempts.sweep(wt, "demo")

    assert _head(wt) == landed_head
    assert [hit["task_id"] for hit in out["landed"]] == ["1.1"]
    assert sorted(out["discarded"]) == sorted([done["attempt_id"], unstarted["attempt_id"]])
    assert not any("partial-land" in line for line in out["log"])
    assert git(wt, "log", "--format=%s", "-2").splitlines() == ["green", "red"]
