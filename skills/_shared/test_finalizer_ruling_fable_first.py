"""Tests for the FABLE_FIRST kinds in finalizer_ruling (design escalation-threshold 1.1).

`standing-order` and `base-sync-hunk` are ruled by Fable; `low` (or missing /
unknown) confidence escalates them. OPERATOR_ONLY kinds always escalate.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import finalizer_ruling as fr  # noqa: E402

PILLARS = {"vision.md": "## Fleet operation\nA run reaches a reviewable PR unattended.\n"}
OPT_A = {"id": "a", "label": "Alpha", "description": "first", "recommended": True}


def ruling(confidence="high", stance="serves"):
    data = {
        "options": [OPT_A],
        "pillar_basis": [{"option": "a", "doc": "vision.md",
                          "section": "Fleet operation",
                          "quote": "reviewable PR unattended", "stance": stance}],
        "tie_breaker": None, "commits_to": [],
        "lesson_proposal": None,
    }
    if confidence is not None:
        data["confidence"] = confidence
    return data


@pytest.mark.parametrize("kind", fr.FABLE_FIRST)
@pytest.mark.parametrize("conf", ["high", "medium"])
def test_fable_first_resolves_at_high_or_medium(kind, conf):
    assert fr.check(ruling(conf), PILLARS, kind) == []


@pytest.mark.parametrize("kind", fr.FABLE_FIRST)
def test_fable_first_low_escalates(kind):
    assert fr.check(ruling("low"), PILLARS, kind) == [f"low-confidence: {kind}"]


@pytest.mark.parametrize("kind", fr.FABLE_FIRST)
@pytest.mark.parametrize("conf", [None, "bogus"])
def test_fable_first_missing_or_unknown_confidence_fails_closed(kind, conf):
    assert f"low-confidence: {kind}" in fr.check(ruling(conf), PILLARS, kind)


@pytest.mark.parametrize("kind", fr.FABLE_FIRST)
def test_fable_first_violates_also_low(kind):
    problems = fr.check(ruling("low", "violates"), PILLARS, kind)
    assert any(p.startswith("pillar-conflict:") for p in problems)
    assert f"low-confidence: {kind}" in problems
    high = fr.check(ruling("high", "violates"), PILLARS, kind)
    assert any(p.startswith("pillar-conflict:") for p in high)
    assert f"low-confidence: {kind}" not in high


@pytest.mark.parametrize("kind", fr.OPERATOR_ONLY)
def test_operator_only_always_escalates(kind):
    assert fr.check(ruling("high"), PILLARS, kind) == [f"operator-only: {kind}"]


def test_leave_for_human_on_a_base_sync_hunk_escalates():
    data = ruling()
    data["options"] = [dict(OPT_A, id="leave-for-human")]
    data["pillar_basis"][0]["option"] = "leave-for-human"
    assert fr.check(data, PILLARS, "base-sync-hunk") == ["leave-for-human: base-sync-hunk"]
    assert fr.check(data, PILLARS, "standing-order") == []


def test_no_pillars_unchanged():
    assert fr.check(ruling(), {}, "base-sync-hunk") == ["no-pillar-basis"]


def test_brief_names_both_lists(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "empty-config"))
    lines = fr.brief_lines("run", tmp_path, tmp_path / "decisions.md")
    always = [l for l in lines if "always escalate" in l.lower()]
    assert len(always) == 1
    assert all(f"`{k}`" in always[0] for k in fr.OPERATOR_ONLY)
    fable = [l for l in lines if "`low` confidence escalates" in l]
    assert len(fable) == 1
    assert all(f"`{k}`" in fable[0] for k in fr.FABLE_FIRST)
