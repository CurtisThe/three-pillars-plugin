"""test_audit_oracle.py — Behavior 4: the **Oracle** and **Entry point** checks,
gated by the ``plan-schema`` marker.

design: fragile-test-prevention (detailed-design-stages Part C2)

The plan inputs are structured task dicts (never a real plan file): with the
marker (``plan-schema: 2``), standard and light modes give an ERROR for a
missing or malformed Oracle or Entry point (the message from ``task_oracle``),
for a ``validate_pair`` break, and through ``check_targets(..., require=True)``
for a missing Targets; without the marker the same gaps are NOTEs; spike mode
returns nothing; ``plan_schema(text)`` reads the marker through
``weight_class.parse_frontmatter`` and gives 1 when it is absent.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from audit_oracle import check_oracle, plan_schema  # noqa: E402
from audit_targets import check_targets  # noqa: E402


def task(**fields) -> dict:
    """A structured task dict in ``extract_tasks`` shape."""
    return {"id": "1.1", "name": "the task", "phase": 1, "fields": fields}


@pytest.mark.parametrize("mode", ["standard", "light"])
def test_missing_oracle_and_entry_point_are_errors_when_marked(mode):
    issues, _ = check_oracle([task(**{"Test": "prose"})], mode, schema=2)
    assert {typ for typ, _, _ in issues} == {"ERROR"}
    msgs = " | ".join(m for _, _, m in issues)
    assert "Oracle" in msgs and "Entry point" in msgs


def test_malformed_fields_carry_the_parser_message():
    t = task(**{"Oracle": "bogus", "Entry point": "not-backticked"})
    issues, _ = check_oracle([t], "standard", schema=2)
    msgs = " | ".join(m for typ, _, m in issues if typ == "ERROR")
    assert "unknown Oracle type 'bogus'" in msgs
    assert "is not a single backticked item" in msgs


def test_none_oracle_with_real_targets_breaks_the_pair():
    t = task(**{"Oracle": "none",
                "Entry point": "`pkg/a.py::test_x`",
                "Targets": "`pkg/a.py::test_x`"})
    issues, _ = check_oracle([t], "standard", schema=2)
    assert [m for typ, _, m in issues if typ == "ERROR"] == [
        "Oracle is none: the task's Targets field must be none"]


def test_missing_targets_is_an_error_when_required():
    t = task(**{"Oracle": "example", "Entry point": "`pkg/a.py::test_x`"})
    issues, _ = check_targets([t], require=True)
    assert {typ for typ, _, _ in issues} == {"ERROR"}
    assert any("Targets" in m for _, _, m in issues)


def test_missing_targets_stays_a_note_by_default():
    issues, notes = check_targets([task(**{"Test": "prose"})])
    assert issues == []
    assert {typ for typ, _, _ in notes} == {"NOTE"}


def test_same_gaps_are_notes_without_the_marker():
    issues, notes = check_oracle([task(**{"Test": "prose"})], "standard", schema=1)
    assert issues == []
    msgs = " | ".join(m for _, _, m in notes)
    assert "Oracle" in msgs and "Entry point" in msgs


def test_spike_mode_is_exempt():
    assert check_oracle([task(**{"Test": "prose"})], "spike", schema=2) == ([], [])


def test_complete_task_is_clean():
    t = task(**{"Oracle": "example",
                "Entry point": "`pkg/a.py::test_x`",
                "Targets": "`pkg/test_a.py` (new)"})
    assert check_oracle([t], "standard", schema=2) == ([], [])


def test_plan_schema_reads_the_marker():
    text = "---\nplan-schema: 2\n---\n\n# Plan: x\n"
    assert plan_schema(text) == 2


def test_plan_schema_is_1_when_absent():
    assert plan_schema("# Plan: x\n\n## Phase 1: do it (~50k)\n") == 1
