"""Docs-coherence: the Tier-7 / convergence prose names converge.py (Task 3.2).

Asserts the POSITIVE (audit f4): `converge.py` is named as the canonical
clean-round finisher in each consumer's Tier-7/convergence section, AND
`proof-of-review.md` affirms the post-before-run_round ordering. No literal
"post LAST" phrase exists in any target file today, so this is naming +
ordering-affirmation, never phrase-removal.
"""
from __future__ import annotations

from pathlib import Path

# scripts/ -> tp-pr-iterate/ -> skills/
SKILLS = Path(__file__).resolve().parent.parent.parent
PROOF_OF_REVIEW = SKILLS / "tp-pr-iterate" / "proof-of-review.md"
TP_PR_ITERATE_SKILL = SKILLS / "tp-pr-iterate" / "SKILL.md"
TP_RUN_FULL_DESIGN_SKILL = SKILLS / "tp-run-full-design" / "SKILL.md"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_proof_of_review_names_converge_py():
    assert "converge.py" in _read(PROOF_OF_REVIEW)


def test_proof_of_review_affirms_post_before_run_round_ordering():
    """The converge.py contract section affirms: post the proof comment BEFORE
    run_round.py, as the LAST head-binding action."""
    text = _read(PROOF_OF_REVIEW)
    # locate the converge.py finisher section and assert ordering within it.
    idx = text.find("converge.py")
    assert idx != -1
    section = text[idx:idx + 800]
    low = section.lower()
    assert "before" in low
    assert "run_round" in low
    assert "last head-binding action" in low


def test_tp_pr_iterate_skill_names_converge_py():
    assert "converge.py" in _read(TP_PR_ITERATE_SKILL)


def test_tp_run_full_design_skill_names_converge_py():
    text = _read(TP_RUN_FULL_DESIGN_SKILL)
    assert "converge.py" in text
    # named within the Tier-7 convergence region (near the two-stable terminal).
    idx = text.find("converge.py")
    region = text[max(0, idx - 600):idx + 200]
    assert "two-stable" in region or "reviewed-stable" in region
