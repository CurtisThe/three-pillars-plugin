"""normalize_codereview carries the reviewer-tagged finding bar.

design: iterate-convergence-budget (Task 1.4)

A tagged finding normalizes with `class`/`blocking`/`reproducer` and a verdict
derived from them; the legacy shape keeps its fail-closed `structural` default.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import review_merge  # noqa: E402

_SCHEMA = json.loads((HERE.parent / "schemas" / "normalized-finding.v1.json").read_text(encoding="utf-8"))
_REPRO = {"kind": "test", "source": "def test_bug():\n    assert False\n"}


def test_normalize_carries_class_and_blocking():
    out = review_merge.normalize_codereview(
        {"file": "a.py", "line": 3, "summary": "crash", "class": "p",
         "blocking": True, "reproducer": _REPRO, "verdict": "minor"})
    assert out["class"] == "P"
    assert out["blocking"] is True
    assert out["reproducer"] == _REPRO
    assert out["verdict"] == "structural"
    Draft202012Validator(_SCHEMA).validate(out)


def test_normalize_blocking_without_reproducer_is_minor_note():
    out = review_merge.normalize_codereview(
        {"file": "a.py", "summary": "tighten", "class": "T", "blocking": True})
    assert (out["blocking"], out["verdict"]) == (False, "minor")
    assert out["schema_note"] == "blocking-without-reproducer"
    Draft202012Validator(_SCHEMA).validate(out)


def test_legacy_shape_stays_structural():
    out = review_merge.normalize_codereview({"file": "a.py", "summary": "x"})
    assert out["verdict"] == "structural"
    assert "class" not in out and "blocking" not in out


def test_unparseable_angle_sentinel_stays_structural():
    merged = review_merge.merge_codereview_angles(["not json at all"])
    assert len(merged) == 1
    assert merged[0]["verdict"] == "structural"
    assert "blocking" not in merged[0]
