"""test_evidence_refs.py — envelope refs checked against the request evidence.

Covers explainer-agent plan Task 3.2 (detailed-design §Interfaces:
"evidence_refs.check_refs(env, request) -> {"unknown": [...], "unsupported":
[paths]}, where supported(item, ids) -> bool needs at least one ref and every
ref known. The check is syntactic: a ref proves provenance, not truth."):
  - supported: one known ref is True; no ref is False; a known ref next to an
    unknown one is False;
  - check_refs: an unknown ref is rejected under "unknown"; every failing
    sentence-bearing field is named under "unsupported" as ste_summary,
    sections[<i>].items[<j>] or confidence_note;
  - the check is syntactic: an item whose text the cited evidence does not
    back is still supported.

The request uses the §Interfaces request shape ({schema:"explain-request/v1",
kind, slug, subject, evidence:[{ref, label, text}], evidence_head}) with the
evidence ids from the plan's Red text. Everything is built here; no repo docs
are read (skills/_shared/test-fragility.md).
"""
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SHARED_DIR = _HERE.parent
for _p in (_SHARED_DIR, _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import evidence_refs as er  # noqa: E402

IDS = {"design:problem", "diffstat", "ruling:r1"}


def _request():
    return {
        "schema": "explain-request/v1",
        "kind": "auto-ruling",
        "slug": "demo",
        "subject": {},
        "evidence": [
            {"ref": "design:problem", "label": "Problem",
             "text": "Reviewers cannot see the whole system in a PR."},
            {"ref": "diffstat", "label": "Diffstat",
             "text": "3 files changed, 40 insertions(+)"},
            {"ref": "ruling:r1", "label": "Ruling r1",
             "text": "Keep the gate deterministic."},
        ],
        "evidence_head": "abc1234",
    }


def _item(text, refs):
    return {"text": text, "refs": list(refs)}


def _envelope():
    """An auto-ruling envelope whose every field cites known evidence."""
    return {
        "schema": "explain-envelope/v1",
        "kind": "auto-ruling",
        "ste_summary": _item("The ruling keeps the gate.", ["ruling:r1"]),
        "sections": [
            {"id": "decided", "title": "Decided",
             "items": [_item("The gate stays deterministic.", ["ruling:r1"])]},
            {"id": "why", "title": "Why",
             "items": [_item("Reviewers need the whole system.",
                             ["design:problem"]),
                       _item("The change is small.", ["diffstat"])]},
            {"id": "commits-to", "title": "Commits to",
             "items": [_item("No model call in the gate.", ["ruling:r1"])]},
        ],
        "diagram_specs": [],
        "confidence_note": _item("The evidence covers the diff.", ["diffstat"]),
    }


# ---------------------------------------------------------------------------
# supported
# ---------------------------------------------------------------------------

def test_item_with_one_known_ref_is_supported():
    assert er.supported({"text": "x", "refs": ["design:problem"]}, IDS) is True


def test_item_with_no_ref_is_unsupported():
    assert er.supported({"text": "x", "refs": []}, IDS) is False


def test_item_with_a_known_and_an_unknown_ref_is_unsupported():
    item = {"text": "x", "refs": ["design:problem", "decision:9"]}
    assert er.supported(item, IDS) is False


def test_item_with_every_ref_known_is_supported():
    item = {"text": "x", "refs": ["design:problem", "diffstat", "ruling:r1"]}
    assert er.supported(item, IDS) is True


# ---------------------------------------------------------------------------
# check_refs
# ---------------------------------------------------------------------------

def test_fully_cited_envelope_has_no_unknown_and_no_unsupported():
    assert er.check_refs(_envelope(), _request()) == {
        "unknown": [], "unsupported": []}


def test_unknown_ref_is_rejected_and_its_item_named_unsupported():
    env = _envelope()
    env["sections"][1]["items"][1]["refs"] = ["diffstat", "decision:9"]
    assert er.check_refs(env, _request()) == {
        "unknown": ["decision:9"], "unsupported": ["sections[1].items[1]"]}


def test_failing_summary_items_and_note_are_named_by_path():
    env = _envelope()
    env["ste_summary"]["refs"] = []
    env["sections"][0]["items"][0]["refs"] = ["design:problem", "decision:9"]
    env["sections"][2]["items"][0]["refs"] = []
    env["confidence_note"]["refs"] = ["decision:9"]
    assert er.check_refs(env, _request()) == {
        "unknown": ["decision:9"],
        "unsupported": ["ste_summary", "sections[0].items[0]",
                        "sections[2].items[0]", "confidence_note"],
    }


def test_ref_known_only_to_another_request_is_unknown():
    env = _envelope()
    request = _request()
    request["evidence"] = [e for e in request["evidence"]
                           if e["ref"] != "ruling:r1"]
    result = er.check_refs(env, request)
    assert result["unknown"] == ["ruling:r1"]
    assert result["unsupported"] == ["ste_summary", "sections[0].items[0]",
                                     "sections[2].items[0]"]


def test_check_is_syntactic_provenance_not_truth():
    # The cited evidence says reviewers cannot see the whole system; the item
    # claims the opposite. A known ref proves provenance only, so it passes.
    env = _envelope()
    env["sections"][1]["items"][0]["text"] = (
        "Reviewers already see the whole system.")
    assert er.check_refs(env, _request()) == {
        "unknown": [], "unsupported": []}
