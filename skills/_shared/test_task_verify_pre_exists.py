"""test_task_verify_pre_exists.py — a task whose Test already passes needs no commit.

design: local-implement-and-review (impl-audit-1 #10, narrowed by impl-audit-2 #0)

Today's rule (`/tp-phase-implement`: "a task's test already passes → Skipped
(pre-exists)") has a ladder path: zero commits, a clean tree and the row's Test green
at base → ``check`` PASS with ``pre_exists``; ``land`` merges nothing. Only on the
``opus`` rung and only for a ``pytest-node`` Test whose named nodes all exist and pass:
a cheap rung or a file-level Test with zero commits stays FAIL ``no commit``, so a worker
that drops its work is never waved through. Real tmp repos only.
"""
from __future__ import annotations

import sys
from pathlib import Path

import task_attempts
import task_verify
from attempt_fixture import DD, branches, commit, git, make_seat, task_row

RUNNER = f"{sys.executable} -m pytest -q"
ROW = {"files": ["skills/a.py"], "targets": "`skills/test_a.py::test_a`"}


def _seat_with_test(tmp_path: Path, body: str) -> Path:
    _seat, wt = make_seat(tmp_path)
    commit(wt, {"skills/test_a.py": f"def test_a():\n    assert {body}\n"}, "test")
    return wt


def _check(att, runner=RUNNER, rung="opus", test=ROW["targets"]):
    return task_verify.check(att, task_row(ROW["files"], test), runner, rung=rung, timeout=60)


def test_green_at_base_with_no_commit_is_pre_exists(tmp_path):
    wt = _seat_with_test(tmp_path, "True")
    head = git(wt, "rev-parse", "HEAD")
    att = task_attempts.open_attempt(wt, "1.1", DD)
    res = _check(att)
    assert (res["verdict"], res["exit"], res["pre_exists"]) == ("PASS", 0, True)
    assert res["reason"].startswith("pre-exists")
    out = task_verify.land(att)
    assert (out["exit"], out["method"], out["sha"]) == (0, "none", head)
    assert git(wt, "rev-parse", "HEAD") == head and branches(wt) == []
    assert not Path(att["attempt_dir"]).exists()


def test_red_or_unrunnable_with_no_commit_stays_no_commit(tmp_path):
    wt = _seat_with_test(tmp_path, "False")
    att = task_attempts.open_attempt(wt, "1.1", DD)
    res = _check(att)
    assert (res["verdict"], res["reason"], res["pre_exists"]) == ("FAIL", "no commit", False)
    assert _check(att, runner=None)["reason"] == "no commit"
    assert task_verify.land(att)["reason"] == "not-passed: FAIL"


def test_cheap_rung_file_level_green_is_no_commit(tmp_path):
    """(a) local/sonnet, zero commits, a file-level Test green at base → FAIL."""
    wt = _seat_with_test(tmp_path, "True")
    for rung in ("local", "sonnet"):
        att = task_attempts.open_attempt(wt, "1.1", DD)
        res = _check(att, rung=rung, test="`skills/test_a.py`")
        assert (res["verdict"], res["reason"], res["pre_exists"]) == (
            "FAIL", "no commit", False), rung
        assert res["commands"] == [], rung  # never judged against the base Test
        task_attempts.discard(att)


def test_cheap_rung_existing_green_node_is_no_commit(tmp_path):
    """(b) local, zero commits, an existing node green at base → FAIL."""
    wt = _seat_with_test(tmp_path, "True")
    att = task_attempts.open_attempt(wt, "1.1", DD)
    res = _check(att, rung="local")
    assert (res["verdict"], res["reason"], res["pre_exists"]) == ("FAIL", "no commit", False)
    assert task_verify.land(att)["reason"] == "not-passed: FAIL"


def test_opus_file_level_green_is_no_commit(tmp_path):
    """(c) opus, a pytest-file Test green at base, zero commits → FAIL."""
    wt = _seat_with_test(tmp_path, "True")
    att = task_attempts.open_attempt(wt, "1.1", DD)
    res = _check(att, test="`skills/test_a.py`")
    assert (res["verdict"], res["reason"], res["pre_exists"]) == ("FAIL", "no commit", False)


def test_opus_nodes_all_green_is_pre_exists_and_missing_node_is_not(tmp_path):
    """(d) opus, every named node exists and is green → PASS; one missing → FAIL."""
    wt = _seat_with_test(tmp_path, "True")
    commit(wt, {"skills/test_a.py": "def test_a():\n    pass\n\n\ndef test_b():\n    pass\n"})
    att = task_attempts.open_attempt(wt, "1.1", DD)
    res = _check(att, test="`skills/test_a.py::test_b`, `skills/test_a.py::test_a`")
    assert (res["verdict"], res["pre_exists"]) == ("PASS", True)
    task_attempts.discard(att)
    att = task_attempts.open_attempt(wt, "1.1", DD)
    res = _check(att, test="`skills/test_a.py::test_a`, `skills/test_a.py::test_gone`")
    assert (res["verdict"], res["reason"], res["pre_exists"]) == ("FAIL", "no commit", False)


def test_one_commit_is_not_pre_exists(tmp_path):
    wt = _seat_with_test(tmp_path, "True")
    att = task_attempts.open_attempt(wt, "1.1", DD)
    commit(Path(att["attempt_dir"]), {"skills/a.py": "A = 2\n"})
    res = _check(att)
    assert (res["verdict"], res["pre_exists"]) == ("PASS", False)

