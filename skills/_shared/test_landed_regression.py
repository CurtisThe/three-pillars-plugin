"""test_landed_regression.py — unit tests for ``landed_regression`` (Task 2.10)."""
from __future__ import annotations

import pytest

import landed_regression as lr
from attempt_fixture import task_row


def _task(tid, files, targets, status=None):
    lines = [f"### Task {tid}: t", f"**File**: {files}", "**Test**: x",
             f"**Targets**: {targets}", "**Red**: r", "**Green**: g", "**Done when**: d"]
    if status:
        lines.append(f"**Status**: {status}")
    return "\n".join(lines) + "\n"


def _plan():
    p1 = "\n".join([_task("1.1", "`a.py`", "`test_a.py::test_x`"),
                    _task("1.2", "`b.py`", "`test_b.py`", status="Blocked"),
                    _task("1.3", "`c.py`", "`test_c.py`"),
                    _task("1.4", "`d.py`", "`test_d.py`"),
                    _task("1.5", "`e.py`", "`test_e.py`")])
    p2 = _task("2.1", "`f.py`", "`test_f.py`")
    return f"# P\n\n## Phase 1: A\n\n{p1}\n## Phase 2: B\n\n{p2}"


def test_landed_rows_order_excluded_and_not_landed():
    landed = {"test_a.py", "test_b.py", "test_d.py", "test_e.py", "test_f.py"}
    rows = lr.landed_rows(_plan(), 2, "2.1", max_files=3, at_base=lambda p: p in landed)
    # 1.2 excluded, 1.3 not landed (test_c.py absent at base); 2.1 itself never
    assert [r["task_id"] for r in rows] == ["1.1", "1.4", "1.5"]
    rows = lr.landed_rows(_plan(), 1, "1.4", max_files=3, at_base=lambda p: p in landed)
    assert [r["task_id"] for r in rows] == ["1.1"]


def test_landed_rows_admits_done_but_skips_blocked():
    p1 = "\n".join([_task("1.1", "`a.py`", "`test_a.py::test_x`", status="Done ✓"),
                    _task("1.2", "`b.py`", "`test_b.py`", status="Blocked"),
                    _task("1.3", "`c.py`", "`test_c.py`")])
    p2 = _task("2.1", "`f.py`", "`test_f.py`")
    plan = f"# P\n\n## Phase 1: A\n\n{p1}\n## Phase 2: B\n\n{p2}"
    landed = {"test_a.py", "test_b.py", "test_c.py", "test_f.py"}
    rows = lr.landed_rows(plan, 2, "2.1", max_files=3, at_base=lambda p: p in landed)
    # 1.1 Done ✓ is admitted; 1.2 Blocked stays skipped; 1.3 normal lands too.
    assert [r["task_id"] for r in rows] == ["1.1", "1.3"]


def test_overlapping_intersection_and_own_dedup():
    a = task_row(("a.py",), "`test_a.py::test_x`", task_id="1.1")
    b = task_row(("b.py",), "`test_b.py`", task_id="1.2")
    a2 = task_row(("a.py", "z.py"), "`test_a.py::test_x`, `test_z.py`", task_id="1.3")
    assert lr.overlapping([a, b, a2], ["a.py"], []) == [
        "test_a.py::test_x", "test_a.py", "test_z.py"]
    assert lr.overlapping([a, b, a2], ["a.py"], ["test_a.py"]) == [
        "test_a.py::test_x", "test_z.py"]
    assert lr.overlapping([a, b], ["q.py"], []) == []


class _Fail(Exception):
    pass


def _fake(red):
    """A ``run`` that writes a junit report; the node is failed when ``red``."""
    def run(argv, cwd, timeout):
        report = next(a.split("=", 1)[1] for a in argv if a.startswith("--junitxml="))
        body = ('<testcase classname="test_a" name="test_x" file="test_a.py">'
                + ("<failure message='m'/>" if red else "") + "</testcase>")
        with open(report, "w", encoding="utf-8") as fh:
            fh.write(f'<testsuites><testsuite tests="1">{body}</testsuite></testsuites>')
        return (1 if red else 0), "tail"
    return run


def _step(tmp_path, red, base_green):
    (tmp_path / "test_a.py").write_text("def test_x():\n    pass\n")
    res = {"commands": [], "logged": []}
    lr.step(str(tmp_path), ["test_a.py::test_x"], "python -m pytest", 5, res,
            run=_fake(red), base_green=base_green, fail=_Fail)
    return res


def test_step_green_no_fail(tmp_path):
    res = _step(tmp_path, False, lambda n: 1 / 0)
    assert res["landed_targets"] == ["test_a.py::test_x"] and not res["logged"]


def test_step_red_green_at_base_is_regression(tmp_path):
    with pytest.raises(_Fail) as exc:
        _step(tmp_path, True, lambda n: True)
    assert str(exc.value) == "regression test_a.py::test_x"


def test_step_red_at_base_is_logged_only(tmp_path):
    res = _step(tmp_path, True, lambda n: False)
    assert res["logged"] == ["pre-existing red test_a.py::test_x"]
