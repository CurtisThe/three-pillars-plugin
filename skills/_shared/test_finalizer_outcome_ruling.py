"""`validate` carries the ruling and routes the resolved check by source.

design: fable-escalation 1.4 — the six ruling keys are reply-envelope keys on
every source; a `resolved` on a `question` stop is pillar-checked
(`finalizer_ruling.check`, no citation rule), every other source keeps today's
`cites_grounding` rule and resolves with no pillar docs. The PILLARS fixture
and the valid basis mirror `test_finalizer_ruling_check.py`.
Run with: python3 -m pytest skills/_shared/test_finalizer_outcome_ruling.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import finalizer_outcome as fo  # noqa: E402
import finalizer_ruling as fr  # noqa: E402

PILLARS = {
    "vision.md": ("## Fleet operation\n"
                  "A run reaches a reviewable PR unattended.\n"),
    "architecture.md": "## Decisions\nOne agent per stop.\n",
}
OPT = {"id": "a", "label": "Alpha", "description": "first way", "recommended": True}
BASIS = {"option": "a", "doc": "vision.md", "section": "Fleet operation",
         "quote": "a reviewable PR   unattended", "stance": "serves"}


def _reply(**kw) -> dict:
    """A full reply whose reasoning cites nothing: only a question may resolve on it."""
    base = {"outcome": "resolved", "actions": ["answer-question"], "diagnosis": "d",
            "reasoning": "the recommended option follows the pillar text",
            "demoted": [], "blocked": [],
            "options": [OPT], "pillar_basis": [BASIS], "tie_breaker": None,
            "commits_to": [], "confidence": "high", "lesson_proposal": None}
    base.update(kw)
    return base


@pytest.mark.parametrize("source", ["pr-iterate", "audit-gate", "halt", "question"])
def test_missing_ruling_key_escalates_every_source(source):
    reply = {k: v for k, v in _reply().items() if k != "options"}
    result = fo.validate(reply, PILLARS, "decision", source)
    assert result["outcome"] == "escalate", result
    assert any(p.startswith("finalizer-errored: missing keys") and "options" in p
               for p in result["problems"]), result


def test_ruling_is_carried():
    reply = _reply()
    result = fo.validate(reply, PILLARS, "decision", "question")
    assert result["outcome"] == "resolved", result
    assert result["ruling"] == {k: reply[k] for k in fr.RULING_KEYS}
    for bad in (None, "", "{not json", json.dumps([1, 2])):  # missing / unparseable / not object
        assert fo.validate(bad)["ruling"] == fr.EMPTY_RULING


@pytest.mark.parametrize("source", ["pr-iterate", "audit-gate", "halt"])
def test_mechanical_source_resolves_without_pillars(source):
    result = fo.validate(_reply(reasoning="scope in design.md", **fr.EMPTY_RULING),
                         None, None, source)
    assert result["outcome"] == "resolved", result


@pytest.mark.parametrize("source", ["pr-iterate", "audit-gate", "halt", None])
def test_mechanical_uncited_is_ungrounded(source):
    result = fo.validate(_reply(reasoning="the loop just needs another round",
                                **fr.EMPTY_RULING), None, None, source)
    assert result["outcome"] == "escalate", result
    assert any(p.startswith("ungrounded:") for p in result["problems"]), result


def test_resolved_question_fabricated_quote_escalates():
    fabricated = dict(BASIS, quote="no such text anywhere")
    result = fo.validate(_reply(pillar_basis=[fabricated]), PILLARS, "decision", "question")
    assert result["outcome"] == "escalate", result
    assert ("pillar-basis-missing: quote not under vision.md § Fleet operation"
            in result["problems"]), result


def test_resolved_question_without_pillars_is_no_pillar_basis():
    result = fo.validate(_reply(), None, "decision", "question")
    assert result["outcome"] == "escalate", result
    assert "no-pillar-basis" in result["problems"], result


def test_operator_only_kind_with_verbatim_quote_still_escalates():
    # 8.3: an operator-only kind escalates first, even with a perfect basis.
    result = fo.validate(_reply(), PILLARS, "merge", "question")
    assert result["outcome"] == "escalate", result
    assert "operator-only: merge" in result["problems"], result


def test_bad_shape_escalates():
    result = fo.validate(_reply(confidence="certain"), None, None, "halt")
    assert result["outcome"] == "escalate", result
    assert "finalizer-errored: bad confidence" in result["problems"], result


# --- decision_entry and the ruling id (design: fable-escalation 1.5) --------------------

STOP = {"source": "halt", "signal": "env-error"}
RESULT = {"outcome": "resolved", "reasoning": "r", "diagnosis": "d", "problems": []}


def test_decision_entry_names_ruling_id():
    entry = fo.decision_entry(STOP, RESULT, ruling_id="demo-20261011-abcdef")
    lines = entry.splitlines()
    assert "- **Ruling**: demo-20261011-abcdef" in lines, entry
    i = lines.index("- **Diagnosis**: d")
    assert lines[i + 1] == "- **Ruling**: demo-20261011-abcdef", entry


def test_decision_entry_without_ruling_id_unchanged():
    # The exact pre-change rendering for the same stop/result, written out literally.
    assert fo.decision_entry(STOP, RESULT) == (
        "### [finalizer] resolved — halt/env-error\n"
        "- **Decided**: resolved\n"
        "- **Reasoning**: r\n"
        "- **Confidence**: high\n"
        "- **Model**: fable\n"
        "- **Diagnosis**: d\n"
    )


# --- phase 1 check fixes (design: fable-escalation 1.6 — C1, C3) -----------------------

@pytest.mark.parametrize("kw,key", [
    ({"commits_to": 5}, "commits_to"),
    ({"pillar_basis": None}, "pillar_basis"),
    ({"options": [{"label": "A", "description": "x",
                   "recommended": True}]}, "options"),
])
def test_malformed_ruling_key_escalates_without_raising(kw, key):
    # C1: a shape problem must escalate on its own and never reach `fr.check`
    # (today the malformed value raises TypeError / KeyError inside the check).
    result = fo.validate(_reply(**kw), PILLARS, "decision", "question")
    assert result["outcome"] == "escalate", result
    assert f"finalizer-errored: bad {key}" in result["problems"], result


def test_results_never_share_empty_ruling_lists():
    # C3: mutating one result's ruling lists must not corrupt EMPTY_RULING
    # for every later call (today both results alias its lists).
    res = fo.validate(None)
    res2 = fo.validate({"outcome": "resolved", "actions": [], "diagnosis": "d",
                        "reasoning": "r", "demoted": [], "blocked": []})
    for r in (res, res2):
        for key in ("options", "pillar_basis", "commits_to"):
            r["ruling"][key].append("mutated")
    assert fr.EMPTY_RULING == {"options": [], "pillar_basis": [],
                               "tie_breaker": None, "commits_to": [],
                               "confidence": "low", "lesson_proposal": None}
