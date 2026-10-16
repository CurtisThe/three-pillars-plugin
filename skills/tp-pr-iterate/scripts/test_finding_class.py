"""Tests for finding_class — the reviewer-tagged finding bar.

design: iterate-convergence-budget (Tasks 1.1, 1.2)

A finding blocks only when the reviewer says `blocking: true` AND ships a valid
reproducer; everything else is a non-blocking note (`verdict="minor"`). The
legacy shape (no `class`, no `blocking`) and degraded sentinels pass through
untouched so `normalize_codereview` keeps its fail-closed `structural` default.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import finding_class  # noqa: E402
from finding_class import coerce, valid_reproducer  # noqa: E402

TEST_REPRO = {"kind": "test", "source": "def test_x():\n    assert 1 == 2\n"}
CMD_REPRO = {"kind": "command", "argv": ["python3", "-c", "print(1)"],
             "expect": {"exit": 0, "stdout_contains": "1"}}


# ---------- valid_reproducer ----------


def test_valid_reproducer_test_kind():
    assert valid_reproducer(TEST_REPRO) is True


def test_valid_reproducer_test_kind_empty_source_invalid():
    assert valid_reproducer({"kind": "test", "source": "  "}) is False
    assert valid_reproducer({"kind": "test", "source": 3}) is False


def test_valid_reproducer_command_kind():
    assert valid_reproducer(CMD_REPRO) is True
    assert valid_reproducer({"kind": "command", "argv": ["true"], "expect": {"exit": 1}}) is True
    assert valid_reproducer(
        {"kind": "command", "argv": ["x"], "expect": {"stdout_contains": "boom"}}) is True


def test_valid_reproducer_command_empty_expect_invalid():
    assert valid_reproducer({"kind": "command", "argv": ["true"], "expect": {}}) is False
    assert valid_reproducer({"kind": "command", "argv": ["true"]}) is False
    assert valid_reproducer({"kind": "command", "argv": ["true"], "expect": {"other": 1}}) is False


def test_valid_reproducer_command_bad_argv_or_expect_types_invalid():
    assert valid_reproducer({"kind": "command", "argv": [], "expect": {"exit": 0}}) is False
    assert valid_reproducer({"kind": "command", "argv": "true", "expect": {"exit": 0}}) is False
    assert valid_reproducer({"kind": "command", "argv": ["a", 1], "expect": {"exit": 0}}) is False
    assert valid_reproducer({"kind": "command", "argv": ["a"], "expect": {"exit": True}}) is False
    assert valid_reproducer({"kind": "command", "argv": ["a"], "expect": {"exit": "0"}}) is False


def test_valid_reproducer_rejects_non_dicts_and_unknown_kind():
    assert valid_reproducer(None) is False
    assert valid_reproducer("pytest -k x") is False
    assert valid_reproducer({"kind": "shell", "source": "echo"}) is False


# ---------- coerce ----------


def test_coerce_legacy_shape_returns_empty():
    assert coerce({"file": "a.py", "summary": "x", "verdict": "structural"}) == {}


def test_coerce_blocking_with_valid_test_reproducer_is_structural():
    out = coerce({"class": "P", "blocking": True, "reproducer": TEST_REPRO})
    assert out["blocking"] is True
    assert out["verdict"] == "structural"
    assert out["class"] == "P"
    assert out["reproducer"] == TEST_REPRO
    assert "schema_note" not in out


def test_coerce_blocking_with_valid_command_reproducer_is_structural():
    out = coerce({"class": "X", "blocking": True, "reproducer": CMD_REPRO})
    assert (out["blocking"], out["verdict"]) == (True, "structural")


def test_coerce_blocking_without_reproducer_downgrades():
    out = coerce({"class": "P", "blocking": True})
    assert out["blocking"] is False
    assert out["verdict"] == "minor"
    assert out["schema_note"] == "blocking-without-reproducer"


def test_coerce_blocking_with_invalid_reproducer_downgrades():
    bad = {"kind": "command", "argv": ["true"], "expect": {}}
    out = coerce({"class": "P", "blocking": True, "reproducer": bad})
    assert (out["blocking"], out["verdict"]) == (False, "minor")
    assert out["schema_note"] == "blocking-without-reproducer"
    assert "reproducer" not in out


def test_coerce_lowercase_class_uppercased():
    assert coerce({"class": "t", "blocking": False})["class"] == "T"
    assert coerce({"class": " x "})["class"] == "X"


def test_coerce_unknown_class_becomes_c():
    assert coerce({"class": "Z", "blocking": False})["class"] == "C"
    assert coerce({"class": 7})["class"] == "C"
    assert coerce({"blocking": False})["class"] == "C"


def test_coerce_blocking_string_true_is_non_blocking():
    out = coerce({"class": "P", "blocking": "true", "reproducer": TEST_REPRO})
    assert out["blocking"] is False
    assert out["verdict"] == "minor"


def test_coerce_non_blocking_is_minor_without_schema_note():
    out = coerce({"class": "C", "blocking": False, "verdict": "structural"})
    assert (out["blocking"], out["verdict"]) == (False, "minor")
    assert "schema_note" not in out


def test_coerce_sentinel_passthrough_returns_empty():
    no_angles = {"source": "no-angles", "file": "<review-output:no-angles>",
                 "verdict": "structural", "class": "C", "blocking": True}
    unparseable = {"source": "angle-2", "file": "<review-output:angle-2>",
                   "verdict": "structural", "blocking": False}
    assert coerce(no_angles) == {}
    assert coerce(unparseable) == {}


def test_coerce_non_dict_returns_empty():
    assert coerce(None) == {}
    assert coerce(["class", "P"]) == {}


def test_classes_constant():
    assert finding_class.CLASSES == ("P", "X", "T", "C")


# ---------- tally / class_line / note_line (Task 1.2) ----------

_SENTINEL = {"source": "no-angles", "file": "<review-output:no-angles>",
             "line_range": [0, 0], "summary": "x", "verdict": "structural"}


_NO_FRAG = {"open-ended": 0, "change-detector": 0, "blocklist": 0}


def test_tally_sentinels_count_only_as_degraded():
    t = finding_class.tally([_SENTINEL, dict(_SENTINEL, source="angle-1",
                                             file="<review-output:angle-1>")])
    assert t == {"P": 0, "X": 0, "T": 0, "C": 0, "blocking": 0, "degraded": 2,
                 "frag": _NO_FRAG, "regression": 0, "reproduced": 0}


def test_tally_per_class_counts_and_blocking():
    findings = [
        {"file": "a.py", "class": "P", "blocking": True, "verdict": "structural"},
        {"file": "b.py", "class": "T", "blocking": False, "verdict": "minor"},
        {"file": "c.py", "class": "T", "blocking": False, "verdict": "minor"},
        {"file": "d.py", "class": "c", "verdict": "minor"},
        _SENTINEL,
    ]
    assert finding_class.tally(findings) == {
        "P": 1, "X": 0, "T": 2, "C": 1, "blocking": 1, "degraded": 1,
        "frag": _NO_FRAG, "regression": 0, "reproduced": 0}


def test_tally_legacy_structural_counts_blocking_without_class():
    t = finding_class.tally([{"file": "a.py", "verdict": "structural"}])
    assert t["blocking"] == 1
    assert (t["P"], t["X"], t["T"], t["C"]) == (0, 0, 0, 0)


def test_tally_empty():
    assert finding_class.tally([]) == {
        "P": 0, "X": 0, "T": 0, "C": 0, "blocking": 0, "degraded": 0,
        "frag": _NO_FRAG, "regression": 0, "reproduced": 0}


def test_class_line_exact():
    t = {"P": 1, "X": 0, "T": 2, "C": 0, "blocking": 1, "degraded": 0,
         "frag": _NO_FRAG, "regression": 0}
    assert finding_class.class_line(3, "abc1234deadbeef", t) == (
        "[tp-pr-iterate] round 3 head=abc1234 P1 X0 T2 C0 blocking=1 "
        "frag=open-ended:0,change-detector:0,blocklist:0 regression=0")


def test_note_line_format():
    f = {"file": "scripts/x.py", "line_range": [42, 50], "class": "T",
         "summary": "tighten the assert"}
    assert finding_class.note_line(2, f) == (
        "[tp-pr-iterate/note] round 2 T origin=unclassified frag=unclassified "
        "scripts/x.py:42 — tighten the assert")


def test_note_line_truncates_summary_to_160():
    f = {"file": "a.py", "line_range": [1, 1], "class": "C", "summary": "y" * 400}
    line = finding_class.note_line(1, f)
    assert line.endswith(" — " + "y" * 160)


def test_note_line_single_line_and_defaults():
    f = {"file": "a.py", "summary": "one\ntwo"}
    line = finding_class.note_line(4, f)
    assert "\n" not in line
    assert line == (
        "[tp-pr-iterate/note] round 4 C origin=unclassified frag=unclassified "
        "a.py:0 — one two")
