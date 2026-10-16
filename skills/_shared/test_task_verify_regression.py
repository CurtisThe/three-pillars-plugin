"""test_task_verify_regression.py — the 1.5/1.6 replay: ``check`` re-runs overlapping landed
Targets (Task 2.10). Each attempt commits the red/green pair (``commit_pair``). Real tmp
repos only (``attempt_fixture``)."""
from __future__ import annotations

import shlex
import sys
from pathlib import Path

import landed_regression
import task_attempts
import task_verify
from attempt_fixture import DD, commit, commit_pair, make_seat, task_row

RUNNER = f"{shlex.quote(sys.executable)} -m pytest -q"
MOD = "L1 = 1\nL2 = 2\n"
PIN = ("def test_pin():\n    n = len(open('skills/mod.py').read().splitlines())\n"
       "    assert n <= 3\n")
PIN_B = "def test_pin_b():\n    assert True\n"
LANDED_A = task_row(("skills/mod.py",), "`skills/test_pin.py::test_pin`", task_id="1.5")
LANDED_C = task_row(("skills/other.py",), "`skills/test_other.py`", task_id="1.4")
ROW_B = task_row(("skills/mod.py", "skills/b.py"), "`skills/test_b.py::test_pin_b`",
                 task_id="1.6")
BAD = "def test_bad():\n    assert False\n"


def _attempt(tmp_path: Path, mod: str, extra: dict | None = None):
    _seat, wt = make_seat(tmp_path)
    commit(wt, {"skills/mod.py": MOD, "skills/test_pin.py": PIN,
                "skills/other.py": "O = 1\n",
                "skills/test_other.py": "def test_o():\n    assert False\n"}, "landed")
    att = task_attempts.open_attempt(wt, "1.6", DD)
    commit_pair(Path(att["attempt_dir"]), {"skills/test_b.py": PIN_B},
                {"skills/mod.py": mod, "skills/b.py": "B = 1\n", **(extra or {})})
    return att


def _check(att, landed, rung="local"):
    return task_verify.check(att, ROW_B, RUNNER, rung=rung, timeout=120, landed=landed)


def test_growing_a_pinned_module_is_a_regression(tmp_path):
    att = _attempt(tmp_path, MOD + "L3 = 3\nL4 = 4\n")
    res = _check(att, [LANDED_A, LANDED_C])
    assert res["verdict"] == "FAIL", res
    assert res["reason"] == "regression skills/test_pin.py::test_pin"
    assert "skills/test_pin.py::test_pin" in res["failing_tests"]


def test_non_overlapping_landed_target_is_not_run(tmp_path):
    att = _attempt(tmp_path, "L1 = 1\n")  # shrinks: within the pin
    res = _check(att, [LANDED_A, LANDED_C])
    assert res["verdict"] == "PASS", res
    assert "skills/test_pin.py::test_pin" in res["landed_targets"]
    assert "skills/test_other.py" not in res["landed_targets"]  # red, but never run


def test_landed_none_is_unchanged(tmp_path):
    att = _attempt(tmp_path, MOD + "L3 = 3\nL4 = 4\n")
    res = _check(att, None)
    assert res["verdict"] == "PASS" and "landed_targets" not in res


def _plan_task(tid, files, targets, status=None):
    lines = [f"### Task {tid}: t", f"**File**: {files}", "**Test**: x",
             f"**Targets**: {targets}", "**Red**: r", "**Green**: g", "**Done when**: d"]
    if status:
        lines.append(f"**Status**: {status}")
    return "\n".join(lines) + "\n"


def test_growing_a_pinned_module_is_a_regression_when_landed_task_is_done(tmp_path):
    """A's row comes from a real plan where it is marked ``Done ✓`` (Task 2.12):
    ``landed_rows`` must still admit it, so B's overlapping growth is still caught."""
    plan = "# P\n\n## Phase 1: A\n\n" + "\n".join([
        _plan_task("1.4", "`skills/other.py`", "`skills/test_other.py`"),
        _plan_task("1.5", "`skills/mod.py`", "`skills/test_pin.py::test_pin`",
                   status="Done ✓"),
        _plan_task("1.6", "`skills/mod.py`, `skills/b.py`",
                   "`skills/test_b.py::test_pin_b`"),
    ])
    landed = landed_regression.landed_rows(plan, 1, "1.6", max_files=3,
                                           at_base=lambda p: True)
    assert [r["task_id"] for r in landed] == ["1.4", "1.5"]  # Done ✓ still admitted
    att = _attempt(tmp_path, MOD + "L3 = 3\nL4 = 4\n")
    res = _check(att, landed)
    assert res["verdict"] == "FAIL", res
    assert res["reason"] == "regression skills/test_pin.py::test_pin"


def test_node_red_at_base_too_is_logged_not_failed(tmp_path):
    """The landed node is red at base as well (its file is only in the attempt)."""
    att = _attempt(tmp_path, "L1 = 1\n", {"skills/test_bad.py": BAD})
    broken = task_row(("skills/mod.py",), "`skills/test_bad.py::test_bad`", task_id="1.3")
    res = _check(att, [broken], rung="opus")
    assert res["verdict"] == "PASS", res
    assert "pre-existing red skills/test_bad.py::test_bad" in res["logged"]
