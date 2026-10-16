"""Tests for finding_class escape/reproduction fields.

design: review-convergence (Task 1.2, detailed-design-pr-loop §D1)

`coerce` carries the Opus check's `escape` only when it is a dict whose
`disposition` is one of `kept|downgraded|opus-added`; an Opus-downgraded claim
never blocks, whatever its reproducer. `tally` counts `reproduced`. The
normalized-finding schema accepts `reproduction`, `escape` and `severity_note`.
Oracle: example + schema (test-fragility: exact values, no open-ended asserts).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).parent))

import finding_class  # noqa: E402
from finding_class import coerce  # noqa: E402

TEST_REPRO = {"kind": "test", "source": "def test_x():\n    assert 1 == 2\n"}
SCHEMA_PATH = (Path(__file__).resolve().parent.parent / "schemas"
               / "normalized-finding.v1.json")


def _claim(**extra) -> dict:
    base = {"file": "a.py", "class": "P", "blocking": True, "reproducer": TEST_REPRO}
    base.update(extra)
    return base


# ---------- coerce: escape kept ----------


@pytest.mark.parametrize("disposition", ["kept", "downgraded", "opus-added"])
def test_escape_kept_without_reason(disposition):
    out = coerce(_claim(escape={"disposition": disposition}))
    assert out["escape"] == {"disposition": disposition}


@pytest.mark.parametrize("disposition", ["kept", "downgraded", "opus-added"])
def test_escape_kept_with_reason(disposition):
    out = coerce(_claim(escape={"disposition": disposition, "reason": "why"}))
    assert out["escape"] == {"disposition": disposition, "reason": "why"}


def test_escape_non_str_reason_dropped_disposition_kept():
    out = coerce(_claim(escape={"disposition": "kept", "reason": 7}))
    assert out["escape"] == {"disposition": "kept"}


# ---------- coerce: escape dropped ----------


@pytest.mark.parametrize("bad", [
    {"disposition": "maybe"},
    {"disposition": "KEPT"},
    {"disposition": None},
    {"reason": "no disposition"},
    "downgraded",
    ["downgraded"],
    None,
    3,
])
def test_bad_escape_dropped(bad):
    out = coerce(_claim(escape=bad))
    assert "escape" not in out
    assert out["blocking"] is True
    assert out["verdict"] == "structural"


# ---------- coerce: blocking rule ----------


def test_downgraded_with_valid_reproducer_is_non_blocking():
    out = coerce(_claim(escape={"disposition": "downgraded", "reason": "style"}))
    assert out["blocking"] is False
    assert out["verdict"] == "minor"
    assert out["reproducer"] == TEST_REPRO
    assert "schema_note" not in out


@pytest.mark.parametrize("disposition", ["kept", "opus-added"])
def test_non_downgraded_with_valid_reproducer_blocks(disposition):
    out = coerce(_claim(escape={"disposition": disposition}))
    assert out["blocking"] is True
    assert out["verdict"] == "structural"


def test_bad_disposition_does_not_downgrade():
    out = coerce(_claim(escape={"disposition": "downgrade"}))
    assert out["blocking"] is True


def test_downgraded_without_reproducer_keeps_schema_note():
    raw = {"file": "a.py", "class": "P", "blocking": True,
           "escape": {"disposition": "downgraded"}}
    out = coerce(raw)
    assert out["blocking"] is False
    assert out["schema_note"] == "blocking-without-reproducer"


# ---------- tally: reproduced ----------


def test_tally_counts_reproduced_structural_only():
    findings = [
        {"file": "a.py", "class": "P", "verdict": "structural",
         "reproduction": "reproduced"},
        {"file": "b.py", "class": "P", "verdict": "structural",
         "reproduction": "inconclusive"},
        {"file": "c.py", "class": "T", "verdict": "minor",
         "reproduction": "reproduced"},
        {"file": "d.py", "class": "P", "verdict": "structural"},
        {"source": "no-angles", "file": "<review-output:x>", "verdict": "structural",
         "reproduction": "reproduced"},
    ]
    t = finding_class.tally(findings)
    assert t["reproduced"] == 1
    # `blocking` counts every structural non-sentinel finding.
    assert t["blocking"] == 3
    assert t["degraded"] == 1


def test_tally_empty_has_zero_reproduced():
    assert finding_class.tally([])["reproduced"] == 0


# ---------- schema ----------


def _validator() -> Draft202012Validator:
    return Draft202012Validator(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))


def _base() -> dict:
    return {"source": "code-review", "file": "a.py", "line_range": [1, 2],
            "summary": "x", "verdict": "minor"}


def test_schema_accepts_three_new_fields():
    f = dict(_base(), reproduction="reproduced",
             escape={"disposition": "downgraded", "reason": "style"},
             severity_note="opus-downgraded")
    assert _validator().is_valid(f)


@pytest.mark.parametrize("value", ["reproduced", "refuted", "inconclusive"])
def test_schema_reproduction_enum(value):
    assert _validator().is_valid(dict(_base(), reproduction=value))


@pytest.mark.parametrize("extra", [
    {"reproduction": "not-reproduced"},
    {"escape": {"disposition": "maybe"}},
    {"escape": {"reason": "no disposition"}},
    {"escape": {"disposition": "kept", "extra": 1}},
    {"escape": "downgraded"},
    {"severity_note": 3},
])
def test_schema_rejects_bad_new_fields(extra):
    assert not _validator().is_valid(dict(_base(), **extra))
