"""Doc pins: a just-do-it design's per-phase check runs before its completion PR.

design: review-convergence 9.6 (Behavior 3, detailed-design-phase-check.md §Consumer
behaviour). `skills/tp-design-complete/SKILL.md` step 6g must run
`skills/_shared/phase-check.md` §Just-do-it, then the `phase_check.py jdi-warn` backstop,
and only then open the PR; `skills/_shared/weight-class.md` §The four classes points at the
check from the `just-do-it` bullet. Every assertion is anchored to a slice: step 6g (its
heading line to step 6h's) or one class bullet, so a mention elsewhere in the file cannot
satisfy it.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SKILL_MD = REPO_ROOT / "skills" / "tp-design-complete" / "SKILL.md"
WEIGHT_CLASS_MD = REPO_ROOT / "skills" / "_shared" / "weight-class.md"

STEP_G = "   g. **Offer to open a PR**"
STEP_H = "   h. **Report success**"
CHECK_BULLET = "Just-do-it check"
ASK = "Otherwise, ask:"
CREATE = "If `gh` is installed and authenticated"


def _skill() -> str:
    return SKILL_MD.read_text(encoding="utf-8")


def _step_g() -> str:
    """Step 6g: from its heading line up to step 6h's."""
    text = _skill()
    start = text.index(STEP_G)
    return text[start:text.index(STEP_H, start)]


def _bullet(text: str, start: str, end: str) -> str:
    i = text.index(start)
    return text[i:text.index(end, i)]


def test_step_g_names_the_check_the_warn_and_the_pr_create():
    g = _step_g()
    assert "phase-check.md" in g and "Just-do-it" in g, "step 6g must run phase-check.md §Just-do-it"
    assert "jdi-warn" in g, "step 6g must run the jdi-warn backstop"
    assert "pr-create" in g, "step 6g opens the PR through pr-create"


def test_check_and_warn_precede_the_pr_create():
    g = _step_g()
    assert g.index("phase-check.md") < g.index("jdi-warn") < g.index("pr-create"), (
        "the check, then the jdi-warn backstop, then the PR — in that order inside step 6g")


def test_check_runs_before_the_window_is_asked_about_the_pr():
    g = _step_g()
    assert g.index(CHECK_BULLET) < g.index(ASK), (
        "the just-do-it check must run before the push/PR question is asked")


def test_warn_runs_before_the_forge_create_call():
    g = _step_g()
    assert g.index("jdi-warn") < g.index(CREATE), (
        "jdi-warn must run inside the yes-path, right before the forge pr-create block")


def test_weight_class_bullet_points_at_the_check():
    text = WEIGHT_CLASS_MD.read_text(encoding="utf-8")
    jdi = _bullet(text, "- `just-do-it`", "- `light`")
    assert "phase-check.md" in jdi, "the just-do-it bullet must name skills/_shared/phase-check.md"
    assert "jdi" in jdi, "the just-do-it bullet must name the check's phase, jdi"
