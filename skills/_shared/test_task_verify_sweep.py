"""test_task_verify_sweep.py — sweep ownership, crash recovery and crash-after-land.

design: local-implement-and-review (design-audit-3 #7)

``sweep(root, slug)`` discards only its own slug's records, and only when the owner is
dead (its root is no longer a registered worktree) or is this dispatcher. A ``landing``
record whose commit already reached the dispatcher is reported in ``landed``. Real tmp
repos only; the ambient repository is never read (M23).
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

import task_attempts
from attempt_fixture import DD, agent_worktree, branches, commit, git, make_seat


class _Crash(BaseException):
    """A simulated process death: not an ``Exception``, so no cleanup handler runs."""


def _dd(slug: str) -> str:
    return f"three-pillars-docs/tp-designs/{slug}"


def _intact(repo: Path, att: dict) -> bool:
    return (os.path.isdir(att["attempt_dir"]) and att["branch"] in branches(repo)
            and os.path.isfile(task_attempts.record_path(att)))


def _gone(repo: Path, att: dict) -> bool:
    return (not os.path.exists(att["attempt_dir"]) and att["branch"] not in branches(repo)
            and not os.path.exists(task_attempts.record_path(att)))


def _set_status(att: dict, status: str) -> None:
    rec = json.loads(Path(task_attempts.record_path(att)).read_text(encoding="utf-8"))
    rec["status"] = status
    task_attempts._write_record(rec)


def test_sweep_respects_slug_and_live_owner(tmp_path):
    seat, _wt = make_seat(tmp_path)
    da, db = agent_worktree(seat, "agent-a", "a"), agent_worktree(seat, "agent-b", "b")
    dc, dgone = agent_worktree(seat, "agent-c", "c"), agent_worktree(seat, "agent-d", "d")
    att_a = task_attempts.open_attempt(da, "1.1", _dd("a"))
    att_b = task_attempts.open_attempt(db, "1.1", _dd("b"))
    assert att_a["branch"].startswith("tp-attempt/a/1.1-")
    assert att_b["branch"].startswith("tp-attempt/b/1.1-")
    live_other = task_attempts.open_attempt(dc, "1.2", _dd("b"))
    dead = task_attempts.open_attempt(dgone, "1.3", _dd("b"))
    shutil.rmtree(dgone)  # the owner's worktree vanishes (e.g. a finished agent)

    out = task_attempts.sweep(db, "b")

    assert sorted(out["discarded"]) == sorted([att_b["attempt_id"], dead["attempt_id"]])
    assert out["landed"] == []
    assert _gone(seat, att_b) and _gone(seat, dead)
    assert _intact(seat, att_a)
    assert _intact(seat, live_other)
    assert task_attempts.sweep(db, "b")["discarded"] == []


def test_sweep_recovers_crash_states(tmp_path, monkeypatch):
    _seat, wt = make_seat(tmp_path)

    def crash_before_add(top, rec):
        raise _Crash()

    monkeypatch.setattr(task_attempts, "_add_worktree", crash_before_add)
    with pytest.raises(_Crash):
        task_attempts.open_attempt(wt, "1.1", DD)
    monkeypatch.undo()
    real_write = task_attempts._write_record

    def crash_before_open(rec):
        if rec["status"] == "open":
            raise _Crash()
        real_write(rec)

    monkeypatch.setattr(task_attempts, "_write_record", crash_before_open)
    with pytest.raises(_Crash):
        task_attempts.open_attempt(wt, "1.2", DD)
    monkeypatch.undo()

    recs = sorted((Path(task_attempts.common_dir(wt)) / "tp-attempts" / "demo").glob("*.json"))
    left = [json.loads(p.read_text(encoding="utf-8")) for p in recs]
    assert [r["status"] for r in left] == ["opening", "opening"]
    early = next(r for r in left if r["task_id"] == "1.1")
    late = next(r for r in left if r["task_id"] == "1.2")
    assert not os.path.exists(early["attempt_dir"]) and early["branch"] not in branches(wt)
    assert os.path.isdir(late["attempt_dir"]) and late["branch"] in branches(wt)

    out = task_attempts.sweep(wt, "demo")

    assert sorted(out["discarded"]) == sorted(r["attempt_id"] for r in left)
    assert _gone(wt, early) and _gone(wt, late)
    assert "tp-attempt-" not in git(wt, "worktree", "list", "--porcelain")


def _landing(wt: Path, task: str, *, land: str | None) -> tuple[dict, str]:
    """Open an attempt, commit in it, optionally land it (``ff``/``pick``), mark it
    ``landing`` and "crash" before discard → ``(record, attempt commit sha)``."""
    att = task_attempts.open_attempt(wt, task, DD)
    sha = commit(Path(att["attempt_dir"]), {f"skills/t{task}.py": "X = 1\n"}, f"task {task}")
    if land == "ff":
        git(wt, "merge", "-q", "--ff-only", att["branch"])
    elif land == "pick":
        git(wt, "cherry-pick", sha)
    _set_status(att, "landing")
    return att, sha


def test_sweep_reports_landed_after_crash(tmp_path):
    _seat, wt = make_seat(tmp_path)
    ff, ff_sha = _landing(wt, "1.1", land="ff")
    stray, _ = _landing(wt, "1.2", land=None)
    commit(wt, {"skills/other.py": "O = 1\n"}, "dispatcher moved on")
    picked, pick_sha = _landing(wt, "1.3", land="pick")
    unlanded_open = task_attempts.open_attempt(wt, "1.4", DD)
    _set_status(unlanded_open, "landing")  # no commit: base is an ancestor, not a landing

    out = task_attempts.sweep(wt, "demo")

    assert sorted(out["landed"], key=lambda r: r["task_id"]) == [
        {"attempt_id": ff["attempt_id"], "task_id": "1.1", "sha": ff_sha},
        {"attempt_id": picked["attempt_id"], "task_id": "1.3", "sha": pick_sha},
    ]
    assert sorted(out["discarded"]) == sorted(
        a["attempt_id"] for a in (ff, stray, picked, unlanded_open))
    for att in (ff, stray, picked, unlanded_open):
        assert _gone(wt, att)
    assert git(wt, "log", "--format=%s", "-3").splitlines()[0] == "task 1.3"


def test_sweep_reports_dead_owner_landing_on_its_branch(tmp_path):
    seat, wt = make_seat(tmp_path)
    worker = agent_worktree(seat, "agent-w")  # on candidate/demo/single
    att, sha = _landing(worker, "2.1", land="ff")
    shutil.rmtree(worker)  # the worker's agent worktree is gone by Cleanup time

    out = task_attempts.sweep(wt, "demo")

    assert out["landed"] == [{"attempt_id": att["attempt_id"], "task_id": "2.1", "sha": sha}]
    assert out["discarded"] == [att["attempt_id"]]
    assert _gone(seat, att)
    assert git(seat, "rev-parse", "candidate/demo/single") == sha
