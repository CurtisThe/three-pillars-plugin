"""test_task_verify_land_gate.py — ``land`` lands only a PASS-checked commit.

design: local-implement-and-review (impl-audit-1 #3)

``check`` records ``{verdict, checked_sha}`` in the attempt's owner record; ``land``
refuses (exit 2, ``recover`` kept, nothing merged) without a check, after a non-PASS
verdict, or when the attempt's HEAD moved after the check. Real tmp repos only.
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


def _refused(wt: Path, att: dict, reason: str) -> None:
    head = git(wt, "rev-parse", "HEAD")
    out = task_verify.land(att)
    assert (out["exit"], out["reason"], out["sha"]) == (2, reason, None)
    assert out["recover"].endswith(f"discard --attempt {att['attempt_id']}")
    assert git(wt, "rev-parse", "HEAD") == head  # nothing landed
    rec = json.loads(Path(task_attempts.record_path(att)).read_text(encoding="utf-8"))
    assert rec["status"] == "open"


def test_land_without_check_refused(tmp_path):
    wt, att = _open(tmp_path)
    commit(Path(att["attempt_dir"]), {"skills/a.py": "A = 2\n"})
    _refused(wt, att, "not-checked")


def test_land_after_fail_refused(tmp_path):
    wt, att = _open(tmp_path)
    assert _check(att)["reason"] == "no commit"
    commit(Path(att["attempt_dir"]), {"skills/a.py": "A = 2\n"})
    _refused(wt, att, "not-passed: FAIL")


def test_land_after_post_check_commit_refused(tmp_path):
    wt, att = _open(tmp_path)
    adir = Path(att["attempt_dir"])
    tip = commit(adir, {"skills/a.py": "A = 2\n"})
    assert _check(att)["verdict"] == "PASS"
    rec = json.loads(Path(task_attempts.record_path(att)).read_text(encoding="utf-8"))
    assert rec["check"] == {"verdict": "PASS", "checked_sha": tip, "rung": "opus"}
    git(adir, "commit", "-q", "--amend", "-m", "sneaked in after the check")
    _refused(wt, att, "moved-after-check")


def test_commit_during_check_is_fail_and_records_the_verified_sha(tmp_path, monkeypatch):
    """impl-audit-2 #6: ``checked_sha`` is the HEAD steps 1-6 verified, sampled before
    they ran; a commit that lands mid-check turns the PASS into FAIL."""
    wt, att = _open(tmp_path)
    adir = Path(att["attempt_dir"])
    tip = commit(adir, {"skills/a.py": "A = 2\n"})
    real = task_verify._verdict

    def _racing(*args):
        res = real(*args)
        git(adir, "commit", "-q", "--amend", "-m", "landed during the check")
        return res

    monkeypatch.setattr(task_verify, "_verdict", _racing)
    res = _check(att)
    assert (res["verdict"], res["reason"], res["exit"]) == ("FAIL", "moved-during-check", 1)
    rec = json.loads(Path(task_attempts.record_path(att)).read_text(encoding="utf-8"))
    assert rec["check"] == {"verdict": "FAIL", "checked_sha": tip, "rung": "opus"}
    _refused(wt, att, "not-passed: FAIL")


def test_land_reads_the_record_not_the_callers_dict(tmp_path):
    """The CLI reloads the record per call; a stale in-memory dict cannot bypass it."""
    wt, att = _open(tmp_path)
    tip = commit(Path(att["attempt_dir"]), {"skills/a.py": "A = 2\n"})
    assert _check(dict(att))["verdict"] == "PASS"  # a copy: only the record learns it
    out = task_verify.land(att)
    assert (out["exit"], out["sha"]) == (0, tip)
