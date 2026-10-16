"""test_explain_envelope.py — explain envelope kinds, sections and validation.

Covers explainer-agent plan Task 3.1 (detailed-design §Interfaces:
"explain_envelope.validate_envelope(env, kind) -> list[str] returns failure
codes. Shape: {schema:"explain-envelope/v1", kind, ste_summary:{text, refs},
sections:[{id, title, items:[{text, refs}]}], diagram_specs:[dict],
confidence_note:{text, refs}}"; design: "A pr-brief envelope without *Where it
sits in the whole system* or *Defaults and switches* fails the schema"):
  - KINDS and REQUIRED_SECTIONS equal the Interfaces values;
  - a minimal envelope of each kind validates with no codes;
  - removing each required section gives missing-section:<id> (guard for the
    pr-brief whole-system and defaults-switches sections);
  - bad-schema, kind-mismatch, raw-diagram, no-recommended and
    bad-shape:<path> each come from the one defect that causes them.

Every envelope is built here from the Interfaces shape (no repo docs read);
assertions are on the returned codes, never on message text
(skills/_shared/test-fragility.md).
"""
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SHARED_DIR = _HERE.parent
for _p in (_SHARED_DIR, _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import pytest  # noqa: E402

import explain_envelope as ee  # noqa: E402

# detailed-design.md §Interfaces, REQUIRED_SECTIONS per kind.
EXPECTED_SECTIONS = {
    "pr-brief": ("what-merging", "whole-system", "defaults-switches",
                 "risks-residuals", "review-outcome", "rulings-without-you"),
    "auto-ruling": ("decided", "why", "commits-to"),
    "human-escalation": ("question", "options", "pillar-analysis",
                         "recommendation"),
}
ALL_KINDS = ("auto-ruling", "human-escalation", "pr-brief")
SECTION_CASES = [(k, s) for k in ALL_KINDS for s in EXPECTED_SECTIONS[k]]


def _item(text, ref="design:problem"):
    return {"text": text, "refs": [ref]}


def _section(sid):
    items = [_item(f"This item states the {sid} part.")]
    if sid == "options":
        items = [
            _item("Keep the current flow.", "design:scope"),
            {**_item("Add the explainer step.", "design:scope"),
             "recommended": True},
        ]
    return {"id": sid, "title": sid.replace("-", " ").capitalize(),
            "items": items}


def _envelope(kind):
    return {
        "schema": "explain-envelope/v1",
        "kind": kind,
        "ste_summary": _item("The design adds one explainer step."),
        "sections": [_section(s) for s in EXPECTED_SECTIONS[kind]],
        "diagram_specs": [{"kind": "flow",
                           "nodes": ["request", "gate", "render"],
                           "edges": [["request", "gate"], ["gate", "render"]]}],
        "confidence_note": _item("The evidence covers the diff.", "diffstat"),
    }


def _without_section(env, sid):
    env["sections"] = [s for s in env["sections"] if s["id"] != sid]
    return env


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

def test_kinds_are_the_three_interface_kinds():
    assert ee.KINDS == ALL_KINDS


def test_required_sections_match_interfaces():
    assert ee.REQUIRED_SECTIONS == EXPECTED_SECTIONS


# ---------------------------------------------------------------------------
# Valid envelopes and required sections
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("kind", ALL_KINDS)
def test_minimal_envelope_of_each_kind_is_valid(kind):
    assert ee.validate_envelope(_envelope(kind), kind) == []


@pytest.mark.parametrize("kind,sid", SECTION_CASES)
def test_each_missing_required_section_is_reported(kind, sid):
    env = _without_section(_envelope(kind), sid)
    assert ee.validate_envelope(env, kind) == [f"missing-section:{sid}"]


@pytest.mark.parametrize("sid", ["whole-system", "defaults-switches"])
def test_guard_pr_brief_without_system_or_switches_fails(sid):
    env = _without_section(_envelope("pr-brief"), sid)
    codes = ee.validate_envelope(env, "pr-brief")
    assert codes and f"missing-section:{sid}" in codes


def test_unknown_kind_argument_raises():
    with pytest.raises(ValueError):
        ee.validate_envelope(_envelope("pr-brief"), "summary")


# ---------------------------------------------------------------------------
# Schema and kind
# ---------------------------------------------------------------------------

def test_wrong_schema_is_bad_schema():
    env = _envelope("auto-ruling")
    env["schema"] = "explain-envelope/v2"
    assert ee.validate_envelope(env, "auto-ruling") == ["bad-schema"]


def test_kind_not_matching_argument_is_kind_mismatch():
    env = _envelope("pr-brief")
    env["kind"] = "auto-ruling"
    assert ee.validate_envelope(env, "pr-brief") == ["kind-mismatch"]


# ---------------------------------------------------------------------------
# Raw diagrams and raw markup in text
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw", [
    "flowchart LR\n  a --> b",
    {"kind": "flow", "nodes": ["a"], "svg": "<svg></svg>"},
    {"kind": "flow", "nodes": ["a"], "mermaid": "flowchart LR"},
    {"kind": "flow", "nodes": ["a"], "html": "<div>a</div>"},
])
def test_raw_diagram_item_is_raw_diagram(raw):
    env = _envelope("pr-brief")
    env["diagram_specs"].append(raw)
    assert ee.validate_envelope(env, "pr-brief") == ["raw-diagram"]


def _set_item_text(env, text):
    env["sections"][0]["items"][0]["text"] = text


def _set_summary_text(env, text):
    env["ste_summary"]["text"] = text


def _set_note_text(env, text):
    env["confidence_note"]["text"] = text


@pytest.mark.parametrize("setter", [_set_item_text, _set_summary_text,
                                    _set_note_text])
@pytest.mark.parametrize("text", [
    "Run this:\n```\nflowchart LR\n```",
    "The flow is <svg viewBox='0 0 1 1'></svg> here.",
])
def test_text_holding_fence_or_svg_is_raw_diagram(setter, text):
    env = _envelope("auto-ruling")
    setter(env, text)
    assert ee.validate_envelope(env, "auto-ruling") == ["raw-diagram"]


# ---------------------------------------------------------------------------
# human-escalation options
# ---------------------------------------------------------------------------

def test_options_with_no_recommended_item_is_no_recommended():
    env = _envelope("human-escalation")
    options = next(s for s in env["sections"] if s["id"] == "options")
    for item in options["items"]:
        item.pop("recommended", None)
    assert ee.validate_envelope(env, "human-escalation") == ["no-recommended"]


# ---------------------------------------------------------------------------
# Shape
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("key", ["schema", "kind", "ste_summary", "sections",
                                 "diagram_specs", "confidence_note"])
def test_missing_top_level_field_is_bad_shape(key):
    env = _envelope("auto-ruling")
    del env[key]
    assert f"bad-shape:{key}" in ee.validate_envelope(env, "auto-ruling")


def test_wrongly_typed_item_refs_is_bad_shape_with_its_path():
    env = _envelope("auto-ruling")
    env["sections"][1]["items"][0]["refs"] = "design:problem"
    assert ee.validate_envelope(env, "auto-ruling") == [
        "bad-shape:sections[1].items[0].refs"]


def test_wrongly_typed_summary_text_is_bad_shape_with_its_path():
    env = _envelope("auto-ruling")
    env["ste_summary"]["text"] = 7
    assert ee.validate_envelope(env, "auto-ruling") == [
        "bad-shape:ste_summary.text"]


def test_non_dict_envelope_is_bad_shape():
    codes = ee.validate_envelope(["not", "an", "envelope"], "pr-brief")
    assert codes and all(c.startswith("bad-shape:") for c in codes)
