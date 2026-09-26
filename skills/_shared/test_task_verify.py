"""test_task_verify.py — ``check`` steps 3-6, the Opus-rung policy, and ``land``.

design: local-implement-and-review (design-audit-3 #1, #2)

Real tmp repos only (``attempt_fixture``); the ambient repository is never read (M23).
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
from attempt_fixture import IDENTITY, DD, branches, commit, git, make_seat, task_row, write


@pytest.fixture
def identity(monkeypatch):
    """A committer identity for ``land``'s cherry-pick (the tmp repo has no config)."""
    for key, value in IDENTITY.items():
        monkeypatch.setenv(key, value)


def _open(tmp_path: Path, task: str = "1.1"):
    _seat, wt = make_seat(tmp_path)
    return wt, task_attempts.open_attempt(wt, task, DD)


def _check(att, row, *, rung="local", runner=None):
    return task_verify.check(att, row, runner, rung=rung, timeout=60)


def test_check_commit_count_and_porcelain(tmp_path):
    wt, att = _open(tmp_path)
    adir = Path(att["attempt_dir"])
    res = _check(att, task_row())
    assert (res["verdict"], res["reason"]) == ("FAIL", "no commit")

    commit(adir, {"skills/a.py": "A = 2\n"})
    commit(adir, {"skills/a.py": "A = 3\n"})
    assert _check(att, task_row())["reason"] == "2 commits"

    att2 = task_attempts.open_attempt(wt, "1.2", DD)
    adir2 = Path(att2["attempt_dir"])
    commit(adir2, {"skills/a.py": "A = 2\n"})
    write(adir2, "skills/leftover.py")
    res = _check(att2, task_row())
    assert (res["verdict"], res["reason"]) == ("FAIL", "uncommitted changes")
    assert res["attempt_branch"] == att2["branch"] and res["task_id"] == "1.2"


def test_check_unlisted_and_design_dir(tmp_path):
    wt, att = _open(tmp_path)
    commit(Path(att["attempt_dir"]), {"skills/a.py": "A = 2\n", "skills/b.py": "B = 1\n"})
    res = _check(att, task_row(), rung="sonnet")
    assert (res["verdict"], res["reason"]) == ("FAIL", "unlisted file: skills/b.py")
    assert res["changed_files"] == ["skills/a.py", "skills/b.py"]

    att2 = task_attempts.open_attempt(wt, "1.2", DD)
    commit(Path(att2["attempt_dir"]), {"skills/a.py": "A = 2\n", f"{DD}/plan.md": "p\n"})
    res = _check(att2, task_row())
    assert (res["verdict"], res["reason"]) == ("FAIL", f"design-dir touched: {DD}/plan.md")

    att3 = task_attempts.open_attempt(wt, "1.3", DD)
    commit(Path(att3["attempt_dir"]), {"skills/a.py": "A = 2\n"})
    res = _check(att3, task_row())  # step 5 passes; no Test, so no oracle on a cheap rung
    assert (res["verdict"], res["reason"]) == (
        "FAIL", "no oracle (a cheap rung needs a runnable Test)")
    res = _check(att3, task_row(), rung="opus")
    assert res["verdict"] == "PASS" and res["unverified"] is True


def test_check_opus_rung_logs_unlisted(tmp_path):
    wt, att = _open(tmp_path)
    commit(Path(att["attempt_dir"]), {"skills/a.py": "A = 2\n", "skills/__init__.py": ""})
    res = _check(att, task_row(), rung="sonnet")
    assert res["reason"] == "unlisted file: skills/__init__.py"
    res = _check(att, task_row(), rung="opus")
    assert res["verdict"] == "PASS"
    assert res["logged"] == ["unlisted-logged: skills/__init__.py"]
    assert "unlisted-logged" in res["reason"]

    att2 = task_attempts.open_attempt(wt, "1.2", DD)
    commit(Path(att2["attempt_dir"]), {"skills/a.py": "A = 2\n", f"{DD}/decisions.md": "d\n"})
    res = _check(att2, task_row(), rung="opus")
    assert (res["verdict"], res["reason"]) == ("FAIL", f"design-dir touched: {DD}/decisions.md")

    att3 = task_attempts.open_attempt(wt, "1.3", DD)
    commit(Path(att3["attempt_dir"]), {"skills/a.py": "A = 2\n", "skills/odd path.py": "x\n"})
    res = _check(att3, task_row(unparsed=["skills/odd*"]), rung="local")
    assert res["reason"].startswith("no oracle")  # step 5 passed leniently; no Test (#12)
    assert res["logged"] == ["unlisted-logged: skills/odd path.py"]


@pytest.mark.parametrize("rung", ["local", "opus"])
@pytest.mark.parametrize("entry", [f"{DD}/decisions.md", f"{DD}/"])
def test_check_listed_design_dir_path_still_fails(tmp_path, rung, entry):
    """A File/Targets entry naming a design-dir path does not license the write."""
    _wt, att = _open(tmp_path)
    commit(Path(att["attempt_dir"]), {"skills/a.py": "A = 2\n", f"{DD}/decisions.md": "w\n"})
    res = _check(att, task_row(files=("skills/a.py", entry)), rung=rung)
    assert (res["verdict"], res["reason"]) == ("FAIL", f"design-dir touched: {DD}/decisions.md")


RUNNER = f"{shlex.quote(sys.executable)} -m pytest -q"  # the interpreter with pytest (#21)
RED = "def test_a():\n    assert 1 == 2\n"
GREEN = "def test_a():\n    assert 1 == 1\n"
NODE_ROW = {"files": ["skills/a.py"], "targets": "`skills/test_a.py::test_a`"}


def test_check_red_test_fails(tmp_path):
    wt, att = _open(tmp_path)
    commit(Path(att["attempt_dir"]), {"skills/a.py": "A = 2\n", "skills/test_a.py": RED})
    res = _check(att, task_row(**NODE_ROW), runner=RUNNER)
    assert (res["verdict"], res["reason"]) == ("FAIL", "red test")
    assert "assert 1 == 2" in res["test_output_tail"]

    att2 = task_attempts.open_attempt(wt, "1.2", DD)
    commit(Path(att2["attempt_dir"]), {"skills/a.py": "A = 2\n", "skills/test_a.py": GREEN})
    res = _check(att2, task_row(**NODE_ROW), runner=RUNNER)
    assert res["verdict"] == "PASS" and res["unverified"] is False
    width = len(shlex.split(RUNNER))  # the runner, the one target, then the report flags
    assert [c[width] for c in res["commands"]] == ["skills/test_a.py::test_a",
                                                   "skills/test_a.py"]
    assert all(c[width + 1].startswith("--junitxml=") for c in res["commands"])


def test_check_skips_step6_when_not_runnable(tmp_path):
    _wt, att = _open(tmp_path)
    commit(Path(att["attempt_dir"]), {"skills/a.py": "A = 2\n", "skills/test_a.py": RED})
    both = ["skills/a.py", "skills/test_a.py"]
    malformed = task_row(both, "`bash framework-check.sh` exits 0")
    missing = task_row(both)  # no Targets field: non-canonical
    rows = ((malformed, RUNNER), (task_row(**NODE_ROW), None), (missing, RUNNER),
            (task_row(both, "none"), RUNNER))
    for row, runner in rows:  # the opus rung may pass unverified …
        res = _check(att, row, runner=runner, rung="opus")
        assert (res["verdict"], res["unverified"], res["commands"]) == ("PASS", True, [])
    for row, runner in rows:  # … a cheap rung never passes without an oracle (#12)
        for rung in ("local", "sonnet"):
            res = _check(att, row, runner=runner, rung=rung)
            assert (res["verdict"], res["reason"], res["unverified"]) == (
                "FAIL", "no oracle (a cheap rung needs a runnable Test)", False)


def _gone(repo: Path, att: dict) -> bool:
    return (not os.path.exists(att["attempt_dir"]) and att["branch"] not in branches(repo)
            and not os.path.exists(task_attempts.record_path(att)))


def test_land_fast_forward_then_discard(tmp_path):
    wt, att = _open(tmp_path)
    tip = commit(Path(att["attempt_dir"]), {"skills/a.py": "A = 2\n"})
    assert _check(att, task_row(), rung="opus")["verdict"] == "PASS"
    out = task_verify.land(att)
    assert (out["exit"], out["method"], out["sha"]) == (0, "ff", tip)
    assert git(wt, "rev-parse", "HEAD") == tip
    assert _gone(wt, att)


def test_disjoint_batch_lands_ff_then_cherry_pick(tmp_path, identity, monkeypatch):
    wt, one = _open(tmp_path)
    two = task_attempts.open_attempt(wt, "1.2", DD)
    commit(Path(one["attempt_dir"]), {"skills/a.py": "A = 2\n"})
    commit(Path(two["attempt_dir"]), {"skills/b.py": "B = 2\n"})
    write(wt, f"{DD}/lock.json", '{"owner": "me"}\n')
    rows = [task_row(), task_row(["skills/b.py"], task_id="1.2")]
    assert [_check(a, r, rung="opus")["verdict"] for a, r in zip((one, two), rows)] == ["PASS"] * 2

    first = task_verify.land(one)
    kept = []
    monkeypatch.setattr(task_attempts, "discard", lambda rec, **_kw: kept.append(rec))
    second = task_verify.land(two)
    assert (first["method"], second["method"], second["exit"]) == ("ff", "cherry-pick", 0)
    rec = json.loads(Path(task_attempts.record_path(two)).read_text(encoding="utf-8"))
    assert rec["status"] == "landing" and rec["commit_sha"] == git(
        Path(two["attempt_dir"]), "rev-parse", "HEAD")
    monkeypatch.undo()
    task_attempts.discard(two)
    assert git(wt, "rev-list", "--count", f"{one['base_sha']}..HEAD") == "2"
    assert (wt / "skills/a.py").read_text(encoding="utf-8") == "A = 2\n"
    assert (wt / "skills/b.py").read_text(encoding="utf-8") == "B = 2\n"
    assert (wt / DD / "lock.json").read_text(encoding="utf-8") == '{"owner": "me"}\n'
    assert _gone(wt, one) and _gone(wt, two)


def test_land_conflict_is_env_error(tmp_path, identity):
    wt, one = _open(tmp_path)
    two = task_attempts.open_attempt(wt, "1.2", DD)
    commit(Path(one["attempt_dir"]), {"skills/a.py": "A = 2\n"})
    commit(Path(two["attempt_dir"]), {"skills/a.py": "A = 3\n"})
    assert [_check(a, task_row(), rung="opus")["verdict"] for a in (one, two)] == ["PASS"] * 2
    landed = task_verify.land(one)["sha"]
    out = task_verify.land(two)
    assert (out["exit"], out["reason"]) == (2, "land-conflict")
    assert out["recover"].endswith(f"discard --attempt {two['attempt_id']}")
    assert git(wt, "rev-parse", "HEAD") == landed
    assert git(wt, "status", "--porcelain") == ""
    assert os.path.isdir(two["attempt_dir"])  # never auto-undone
    rec = json.loads(Path(task_attempts.record_path(two)).read_text(encoding="utf-8"))
    assert rec["status"] == "open" and "commit_sha" not in rec


_MULTI_PLAN = """# Plan

## Phase 1: demo

### Task 1.1: change A
**File**: `skills/a.py`
**Test**: prose only.
**Targets**: {targets}
**Red**: test_two fails until A is right.
**Green**: set A.
"""


def _multi_check(tmp_path, targets):
    import task_eligibility

    plan = _MULTI_PLAN.format(targets=targets)
    _seat, wt = make_seat(tmp_path)
    commit(wt, {
        "skills/test_one.py": "def test_one():\n    assert True\n",
        "skills/test_two.py": ("from pathlib import Path\n\n\ndef test_two():\n"
                               "    assert Path('skills/a.py').read_text(encoding='utf-8')"
                               " == 'A = 1\\n'\n"),
        f"{DD}/plan.md": plan,
    }, "tests")
    [row] = task_eligibility.classify_phase(
        plan, 1, runner_ok=True, exists=lambda p: (wt / p).exists())
    assert row["tier"] == "local"
    att = task_attempts.open_attempt(wt, "1.1", DD)
    commit(Path(att["attempt_dir"]), {"skills/a.py": "A = 2\n"})  # turns test_two red
    runner = f"{shlex.quote(sys.executable)} -m pytest -q -p no:cacheprovider"
    return task_verify.check(att, row, runner, rung="local", timeout=120)


@pytest.mark.parametrize("targets", [
    "`skills/test_one.py::test_one`, `skills/test_two.py::test_two`",
    "`skills/test_two.py::test_two`, `skills/test_one.py::test_one`",
    "`skills/test_two.py`, `skills/test_one.py::test_one`",
], ids=["nodes", "nodes-reordered", "file-first"])
def test_check_runs_every_declared_target(tmp_path, targets):
    """A red declared target fails the check wherever it sits in the field."""
    res = _multi_check(tmp_path, targets)
    assert (res["verdict"], res["reason"]) == ("FAIL", "red test")
    assert any("skills/test_two.py" in arg for argv in res["commands"] for arg in argv)


def test_check_runs_only_declared_targets(tmp_path):
    """An undeclared red test is not this task's oracle: the check stays green."""
    res = _multi_check(tmp_path, "`skills/test_one.py::test_one`")
    assert res["verdict"] == "PASS", res["reason"]
    assert not any("two" in arg for argv in res["commands"] for arg in argv)
