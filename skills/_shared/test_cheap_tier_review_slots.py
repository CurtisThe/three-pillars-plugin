"""Tests for the four review-prep slots in cheap_tier.py and the config schema.

design: cheap-tier-review-prep (Task 1.2).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cheap_tier as ct  # noqa: E402
import model_policy  # noqa: E402

SHARED = Path(__file__).resolve().parent
PREP = ("review_slice", "review_refs", "ci_log_triage", "repro_scaffold")
MEDIUM = ("local-medium", "sonnet-medium")
XHIGH = ("local-xhigh", "sonnet-xhigh")
ORACLES = {"review_slice": "hunk_bytes", "review_refs": "path_line",
           "ci_log_triage": "log_substring", "repro_scaffold": "observed_red"}


def test_review_slice_refs_and_triage_rows():
    for name in ("review_slice", "review_refs", "ci_log_triage"):
        assert ct.SLOTS[name] == ct.Slot(4, "model", "pure", ORACLES[name], MEDIUM,
                                         "drop", "local-medium"), name


def test_repro_scaffold_row_is_xhigh():
    assert ct.SLOTS["repro_scaffold"] == ct.Slot(4, "model", "pure", "observed_red", XHIGH,
                                                 "drop", "local-xhigh")


def test_review_prep_slots_tuple():
    assert ct.REVIEW_PREP_SLOTS == PREP
    assert set(ct.REVIEW_PREP_SLOTS) <= set(ct.SLOTS)


def test_excluded_keeps_digest_post_and_is_otherwise_unchanged():
    assert "digest_post" in ct.EXCLUDED
    assert not set(PREP) & ct.EXCLUDED
    assert ct.EXCLUDED == frozenset({
        "review", "impl-audit", "certify", "phase-check", "generator", "phase-worker", "reader",
        "council", "design", "plan", "orchestrator", "merge_gate", "land",
        "ci_local", "ci_local_stamp", "finalizer", "severity", "confirm", "digest_post"})


def test_finalizer_agent_role_is_excluded():  # the portable #188 fact (D1)
    role = model_policy.AGENTS["tp-finalizer"][0]
    assert role in ct.EXCLUDED


def test_loader_accepts_a_legal_prep_rung():
    cfg = {"models": {"review_slice": "sonnet-medium"}}
    shipped = {s: r.default for s, r in ct.SLOTS.items() if r.default is not None}
    assert ct.load_slots(cfg) == {**shipped, "review_slice": "sonnet-medium"}


@pytest.mark.parametrize("models,needle", [
    ({"review_slice": "opus-xhigh"}, "rung"),
    ({"review_slice": "local-xhigh"}, "rung"),
    ({"repro_scaffold": "sonnet-medium"}, "rung"),
    ({"digest_post": "sonnet-medium"}, "excluded"),
])
def test_loader_refuses(models, needle):
    with pytest.raises(ValueError, match=needle):
        ct.load_slots({"models": models})


@pytest.mark.parametrize("slot", PREP)
def test_two_key_silence(slot):
    rung = ct.SLOTS[slot].rungs[-1]
    # key unset: the shipped default (A/B close-out) applies once the flag is on
    assert ct.slot_rung(slot, {"models": {}}, cheap_flag="on") == ct.SLOTS[slot].default
    assert ct.slot_rung(slot, {"models": {}}, cheap_flag=None) is None  # flag off
    assert ct.slot_rung(slot, {"models": {slot: rung}}, cheap_flag=None) is None  # flag off
    assert ct.slot_rung(slot, {"models": {slot: rung}}, cheap_flag="on") == rung


def _models_schema() -> dict:
    schema = json.loads((SHARED / "repo-config.schema.json").read_text(encoding="utf-8"))
    return schema["properties"]["models"]


def _validate(models: dict) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.Draft202012Validator(_models_schema()).validate(models)


def test_schema_accepts_a_legal_rung():
    _validate({"review_refs": "local-medium"})
    _validate({"repro_scaffold": "sonnet-xhigh"})


def test_schema_rejects_an_alias_and_an_unknown_key():
    jsonschema = pytest.importorskip("jsonschema")
    with pytest.raises(jsonschema.ValidationError):
        _validate({"review_refs": "opus"})
    with pytest.raises(jsonschema.ValidationError):
        _validate({"digest_post": "sonnet-medium"})


def test_schema_entries_match_the_rows():
    models = _models_schema()
    assert models["additionalProperties"] is False
    for slot in PREP:
        entry = models["properties"][slot]
        assert tuple(entry["enum"]) == (*ct.SLOTS[slot].rungs, "off"), slot
        assert entry.get("description"), slot


def test_repo_config_md_lists_the_prep_keys():
    text = (SHARED / "repo-config.md").read_text(encoding="utf-8")
    for slot in PREP:
        assert f"`{slot}`" in text, slot
