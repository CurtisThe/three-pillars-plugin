"""test_task_verify_edit_after_pass.py — no in-place repair after a PASS.

design: run-throughput (attempt-integrity, amendment 2, dd §A2)

Once an attempt's record holds a PASS ``check``, a commit that moves the attempt's
HEAD past the checked sha is never re-verified: the next ``check`` FAILs
``edited-after-pass`` without running any step, and ``land`` stays refused. A
re-check at the same sha (no new commit) is unaffected. Real tmp repos only.
"""
from __future__ import annotations

import json
from pathlib import Path

import task_attempts
import task_verify
from attempt_fixture import DD, commit, git, make_seat, task_row


def _open(tmp_path: Path):
    _seat, wt = make_seat(tmp_path)
    return wt, task_attempts.open_attempt(wt, "1.1", DD)


def _check(att):
    return task_verify.check(att, task_row(), None, rung="opus", timeout=60)


def test_edit_after_pass_fails_without_rerunning(tmp_path, monkeypatch):
    wt, att = _open(tmp_path)
    adir = Path(att["attempt_dir"])
    tip = commit(adir, {"skills/a.py": "A = 2\n"})
    assert _check(att)["verdict"] == "PASS"

    calls = []
    monkeypatch.setattr(task_verify, "_verdict", lambda *a: calls.append(1) or {})

    new_tip = commit(adir, {"skills/a.py": "A = 3\n"}, "sneaked in after the pass")
    res = _check(att)

    assert (res["verdict"], res["reason"], res["exit"]) == ("FAIL", "edited-after-pass", 1)
    assert calls == []  # verdict_fn never ran: no step was executed
    rec = json.loads(Path(task_attempts.record_path(att)).read_text(encoding="utf-8"))
    assert rec["check"] == {"verdict": "FAIL", "checked_sha": new_tip, "rung": "opus"}
    assert new_tip != tip

    out = task_verify.land(att)
    assert (out["exit"], out["reason"], out["sha"]) == (2, "not-passed: FAIL", None)
    assert git(wt, "rev-parse", "HEAD") != new_tip  # nothing landed


def test_same_sha_recheck_after_pass_is_unaffected(tmp_path):
    wt, att = _open(tmp_path)
    adir = Path(att["attempt_dir"])
    tip = commit(adir, {"skills/a.py": "A = 2\n"})
    assert _check(att)["verdict"] == "PASS"

    res = _check(att)  # no new commit: same HEAD, runs as normal

    assert res["verdict"] == "PASS"
    rec = json.loads(Path(task_attempts.record_path(att)).read_text(encoding="utf-8"))
    assert rec["check"] == {"verdict": "PASS", "checked_sha": tip, "rung": "opus"}

    out = task_verify.land(att)
    assert (out["exit"], out["sha"]) == (0, tip)
