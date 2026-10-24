"""Tests for task_shape: Red clauses, entry points, environment helpers."""
import sys
from pathlib import Path

_SCRIPTS = str(Path(__file__).resolve().parent)
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import sizing_limits  # noqa: E402
import task_shape  # noqa: E402

H = sizing_limits.TEST_HELPERS


def _clauses(n):
    return "; ".join(f"check thing{i}" for i in range(n))


def test_six_semicolon_clauses_ok():
    assert task_shape.shape_findings({"Red": _clauses(6)}, H) == []


def test_seven_semicolon_clauses_flagged():
    out = task_shape.shape_findings({"Red": _clauses(7)}, H)
    assert len(out) == 1 and "7 > 6" in out[0]


def test_seven_bullets_count_seven():
    red = "\n".join(f"- check thing{i}" for i in range(7))
    out = task_shape.shape_findings({"Red": red}, H)
    assert len(out) == 1 and "7 > 6" in out[0]


def test_two_entry_points_flagged_one_ok():
    two = {"Entry point": "`skills/a.py::f`, `skills/b.py::g`"}
    one = {"Entry point": "`skills/a.py::f`"}
    out = task_shape.shape_findings(two, H)
    assert len(out) == 1 and "entry points" in out[0]
    assert task_shape.shape_findings(one, H) == []


def test_environment_needs_helper():
    out = task_shape.shape_findings({"Red": "build a tmp git repo"}, H)
    assert len(out) == 1
    ok = task_shape.shape_findings(
        {"Red": "build a tmp git repo with clean_git_env"}, H)
    assert ok == []


def test_red_clauses_ignores_eg():
    text = "Use a fixture, e.g. a tmp dir. Run it. Check it."
    assert task_shape.red_clauses(text) == 3
