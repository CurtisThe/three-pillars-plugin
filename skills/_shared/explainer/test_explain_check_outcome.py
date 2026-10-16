"""test_explain_check_outcome.py — the Opus check outcome, measured by diff ratio.

Covers explainer-agent plan Task 5.3 (detailed-design §Interfaces,
explain_degrade.check_outcome; decisions.md "Opus-check outcome is measured,
not self-reported"):
  - identical prose gives "accepted"; a change only to refs is still
    "accepted";
  - a difflib.SequenceMatcher ratio of exactly 0.6 gives "edited", and a
    ratio just below 0.6 gives "rewritten";
  - prose is every text field (summary, each section item, note) joined in
    envelope order, so a change to any one of them counts;
  - a light edit through long prose is "edited": difflib's autojunk
    heuristic (strings of 200+ chars) must not turn it into "rewritten".

The exact-0.6 and just-below pairs are asserted on the ratio first, so the
boundary is pinned by the measure, not by the wording of the texts
(skills/_shared/test-fragility.md).
"""
import copy
import difflib
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SHARED_DIR = _HERE.parent
for _p in (_SHARED_DIR, _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import pytest  # noqa: E402

import explain_degrade as ed  # noqa: E402

DRAFT_TEXTS = ("The run keeps the old lock file.", "Keep the lock file.",
               "Two runs share one branch.",
               "The next run reads the lock first.", "Medium confidence.")

# Same envelope, other texts: the prose ratio against DRAFT_TEXTS is exactly
# 0.6, and just under it once only the commits-to item differs.
EXACT_TEXTS = ("The run drops the old lock.", "Remove it.",
               "Branches are not shared.", "The next run starts clean.",
               "High confidence.")
BELOW_TEXTS = EXACT_TEXTS[:3] + ("Each run writes a lock.",) + EXACT_TEXTS[4:]

LONG_SENTENCES = (
    "The run keeps the old lock file.",
    "Two runs share one branch, so the lock stops a second run.",
    "The next run reads the lock first and waits for the owner.",
    "A stale lock names its owner and the time it was taken.",
    "The operator can release the lock with one command.",
    "No run deletes a lock that another run holds.",
)


def _envelope(texts, refs=("decision:1",)):
    """An auto-ruling envelope: (summary, decided, why, commits-to, note)."""
    summary, decided, why, commits, note = texts
    sections = [
        {"id": sid, "title": sid.capitalize(),
         "items": [{"text": text, "refs": list(refs)}]}
        for sid, text in (("decided", decided), ("why", why),
                          ("commits-to", commits))
    ]
    return {
        "schema": "explain-envelope/v1",
        "kind": "auto-ruling",
        "ste_summary": {"text": summary, "refs": list(refs)},
        "sections": sections,
        "diagram_specs": [],
        "confidence_note": {"text": note, "refs": list(refs)},
    }


def _ratio(draft, checked) -> float:
    return difflib.SequenceMatcher(None, ed.prose(draft),
                                   ed.prose(checked)).ratio()


def test_identical_prose_is_accepted():
    draft = _envelope(DRAFT_TEXTS)
    assert ed.check_outcome(draft, copy.deepcopy(draft)) == "accepted"


def test_change_only_to_refs_is_accepted():
    draft = _envelope(DRAFT_TEXTS)
    checked = _envelope(DRAFT_TEXTS, refs=("decision:2", "design:problem"))
    assert checked != draft
    assert ed.check_outcome(draft, checked) == "accepted"


def test_ratio_of_exactly_point_six_is_edited():
    draft, checked = _envelope(DRAFT_TEXTS), _envelope(EXACT_TEXTS)
    assert _ratio(draft, checked) == 0.6
    assert ed.check_outcome(draft, checked) == "edited"


def test_ratio_below_point_six_is_rewritten():
    draft, checked = _envelope(DRAFT_TEXTS), _envelope(BELOW_TEXTS)
    assert 0.59 < _ratio(draft, checked) < 0.6
    assert ed.check_outcome(draft, checked) == "rewritten"


def test_one_word_edit_is_edited():
    texts = list(DRAFT_TEXTS)
    texts[2] = "Two runs share a branch."
    draft, checked = _envelope(DRAFT_TEXTS), _envelope(tuple(texts))
    assert 0.6 < _ratio(draft, checked) < 1.0
    assert ed.check_outcome(draft, checked) == "edited"


def test_prose_is_every_text_field_in_envelope_order():
    env = _envelope(DRAFT_TEXTS)
    assert ed.prose(env) == "\n".join(DRAFT_TEXTS)


@pytest.mark.parametrize("index", range(len(DRAFT_TEXTS)))
def test_a_change_to_any_text_field_counts(index):
    texts = list(DRAFT_TEXTS)
    texts[index] = "Nothing here matches the draft at all, xyz."
    outcome = ed.check_outcome(_envelope(DRAFT_TEXTS), _envelope(tuple(texts)))
    assert outcome in ("edited", "rewritten")


def test_light_edit_of_long_prose_is_edited():
    edited = tuple(s.replace("lock", "claim").replace("run", "job")
                   for s in LONG_SENTENCES)
    draft = _envelope(("Summary.", " ".join(LONG_SENTENCES), "Why.",
                       "Commits.", "Note."))
    checked = _envelope(("Summary.", " ".join(edited), "Why.",
                         "Commits.", "Note."))
    assert len(ed.prose(draft)) >= 200
    assert ed.check_outcome(draft, checked) == "edited"
