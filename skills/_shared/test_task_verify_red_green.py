"""test_task_verify_red_green.py — ``check`` and ``land`` on the red/green pair.

design: fragile-test-prevention (stages §Part C1, phase 4)

Step 3 of ``check`` is the pair rule (``targets_frozen.check_pair``): the first commit is
the red, and no later commit touches a Targets file. ``land`` carries both commits to the
dispatcher in order (``merge --ff-only`` or one range ``cherry-pick``), recording
``pre_land_head`` first; Red-at-base evidence is taken at the red commit and never gates.
Oracle: ``example`` — each case is a concrete commit shape from the detailed design,
built in a real tmp repo (``attempt_fixture``, M23).
"""
from __future__ import annotations

import json
import os
import shlex
import sys
from pathlib import Path

import pytest

import task_attempts
import task_verify
import tier_ladder
from attempt_fixture import IDENTITY, DD, commit, commit_pair, git, make_seat, task_row
from local_implement_config import DEFAULTS

RUNNER = f"{shlex.quote(sys.executable)} -m pytest -q -p no:cacheprovider"
TEST_A = "import a\n\n\ndef test_a():\n    assert a.A == 2\n"
WEAKER = "def test_a():\n    assert True\n"
TEST_B = "import b\n\n\ndef test_b():\n    assert b.B == 2\n"
ROW_A = task_row(("skills/a.py",), "`skills/test_a.py::test_a`")
ROW_B = task_row(("skills/b.py",), "`skills/test_b.py::test_b`", task_id="1.2")


@pytest.fixture
def identity(monkeypatch):
    """A committer identity for ``land``'s cherry-pick (the tmp repo has no config)."""
    for key, value in IDENTITY.items():
        monkeypatch.setenv(key, value)


def _dispatcher(tmp_path: Path) -> Path:
    _seat, wt = make_seat(tmp_path)
    commit(wt, {"skills/b.py": "B = 1\n"}, "b at base")
    return wt


def _check(att: dict, row: dict = ROW_A) -> dict:
    return task_verify.check(att, row, RUNNER, rung="local", timeout=120)


def _paths(repo: Path, sha: str) -> list[str]:
    return git(repo, "show", "--name-only", "--no-renames", "--format=", sha).split()


def _record(att: dict) -> dict:
    return json.loads(Path(task_attempts.record_path(att)).read_text(encoding="utf-8"))


def test_clean_pair_passes_with_red_sha_and_lands_by_ff(tmp_path):
    wt = _dispatcher(tmp_path)
    att = task_attempts.open_attempt(wt, "1.1", DD)
    red, green = commit_pair(Path(att["attempt_dir"]), {"skills/test_a.py": TEST_A},
                             {"skills/a.py": "A = 2\n"})
    res = _check(att)
    assert (res["verdict"], res["red_sha"]) == ("PASS", red), res["reason"]
    out = task_verify.land(att)
    assert (out["exit"], out["method"], out["sha"]) == (0, "ff", green)
    assert git(wt, "rev-list", "--reverse", f"{att['base_sha']}..HEAD").split() == [red, green]


def test_clean_pair_lands_in_order_by_range_cherry_pick(tmp_path, identity, monkeypatch):
    """The dispatcher moved by a disjoint landing: both commits are picked, in order."""
    wt = _dispatcher(tmp_path)
    one = task_attempts.open_attempt(wt, "1.1", DD)
    two = task_attempts.open_attempt(wt, "1.2", DD)
    commit_pair(Path(one["attempt_dir"]), {"skills/test_a.py": TEST_A},
                {"skills/a.py": "A = 2\n"})
    commit_pair(Path(two["attempt_dir"]), {"skills/test_b.py": TEST_B},
                {"skills/b.py": "B = 2\n"})
    assert [_check(a, r)["verdict"] for a, r in ((one, ROW_A), (two, ROW_B))] == ["PASS"] * 2
    first = task_verify.land(one)
    kept = []
    monkeypatch.setattr(task_attempts, "discard", lambda rec, **_kw: kept.append(rec))
    second = task_verify.land(two)
    assert (first["method"], second["method"], second["exit"]) == ("ff", "cherry-pick", 0)
    assert _record(two)["pre_land_head"] == first["sha"]  # written before the land
    monkeypatch.undo()
    task_attempts.discard(two)
    landed = git(wt, "rev-list", "--reverse", f"{first['sha']}..HEAD").split()
    assert [_paths(wt, sha) for sha in landed] == [["skills/test_b.py"], ["skills/b.py"]]


def test_green_editing_a_target_fails_and_the_ladder_counts_it(tmp_path):
    """Behavior 1: a green that weakens its red test is FAIL, naming the file."""
    wt = _dispatcher(tmp_path)
    att = task_attempts.open_attempt(wt, "1.1", DD)
    commit_pair(Path(att["attempt_dir"]), {"skills/test_a.py": TEST_A},
                {"skills/a.py": "A = 2\n", "skills/test_a.py": WEAKER})
    res = _check(att)
    assert (res["verdict"], res["reason"]) == (
        "FAIL", "targets edited after red: skills/test_a.py")
    assert task_verify.land(att)["reason"] == "not-passed: FAIL"
    _action, _rung, rec = tier_ladder.next_step(tier_ladder.start("1.1", "local"), "FAIL",
                                                DEFAULTS, reason=res["reason"])
    assert rec["attempts"][rec["tier_path"][0]] == 1
    assert (rec["verdicts"][-1]["outcome"], rec["verdicts"][-1]["reason"]) == (
        "FAIL", res["reason"])


@pytest.mark.parametrize("shape, want", [
    ("red-touches-impl", "red commit touches non-Targets file: skills/a.py"),
    ("one-mixed-commit", "targets changed without a red commit: skills/test_a.py"),
])
def test_a_broken_pair_fails_naming_the_file(tmp_path, shape, want):
    wt = _dispatcher(tmp_path)
    att = task_attempts.open_attempt(wt, "1.1", DD)
    adir = Path(att["attempt_dir"])
    both = {"skills/test_a.py": TEST_A, "skills/a.py": "A = 2\n"}
    if shape == "red-touches-impl":
        commit_pair(adir, both, {"skills/a.py": "A = 2  # green\n"})
    else:
        commit(adir, both)
    res = _check(att)
    assert (res["verdict"], res["reason"]) == ("FAIL", want)


@pytest.mark.parametrize("red_test, want", [(TEST_A, "meaningful"),
                                            (WEAKER, "green-at-base")])
def test_red_evidence_is_taken_at_red_sha_and_never_gates(tmp_path, monkeypatch,
                                                          red_test, want):
    wt = _dispatcher(tmp_path)
    att = task_attempts.open_attempt(wt, "1.1", DD)
    red, _green = commit_pair(Path(att["attempt_dir"]), {"skills/test_a.py": red_test},
                              {"skills/a.py": "A = 2\n"})
    at, real_run = [], task_verify.run

    def spy(argv, cwd, timeout):
        if os.path.realpath(cwd) != os.path.realpath(att["attempt_dir"]):
            at.append(git(Path(cwd), "rev-parse", "HEAD"))  # the scratch's commit
        return real_run(argv, cwd, timeout)

    monkeypatch.setattr(task_verify, "run", spy)
    res = _check(att)
    assert (res["verdict"], res["red_at_base"]) == ("PASS", want), res.get("red_at_base_tail")
    assert at and set(at) == {red}


def test_a_range_conflict_aborts_and_resets_to_pre_land_head(tmp_path, identity):
    """The red applies, the green conflicts: nothing of the range stays on the dispatcher."""
    wt = _dispatcher(tmp_path)
    one = task_attempts.open_attempt(wt, "1.1", DD)
    two = task_attempts.open_attempt(wt, "1.2", DD)
    commit_pair(Path(one["attempt_dir"]), {"skills/test_a.py": TEST_A},
                {"skills/a.py": "A = 2\n"})
    test_c = TEST_A.replace("test_a", "test_c").replace("== 2", "== 3")
    commit_pair(Path(two["attempt_dir"]), {"skills/test_c.py": test_c},
                {"skills/a.py": "A = 3\n"})
    row_c = task_row(("skills/a.py",), "`skills/test_c.py::test_c`", task_id="1.2")
    assert [_check(a, r)["verdict"] for a, r in ((one, ROW_A), (two, row_c))] == ["PASS"] * 2
    pre = task_verify.land(one)["sha"]
    out = task_verify.land(two)
    assert (out["exit"], out["reason"]) == (2, "land-conflict")
    assert git(wt, "rev-parse", "HEAD") == pre
    assert git(wt, "status", "--porcelain") == ""
    assert not (wt / "skills" / "test_c.py").exists()
    assert (_record(two)["status"], os.path.isdir(two["attempt_dir"])) == ("open", True)
