"""Doc pins for the issue-id placeholder convention and the resolution boundary
(design: basesync-autoresolve-coverage, task 3.2)."""
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[1]
CLI = 'python3 "$TP_ROOT"/skills/_shared/number_issues.py'
SEVEN = [
    "tp-merge-from-main",
    "tp-design-complete",
    "tp-merge",
    "tp-design-learn",
    "tp-implementation-audit",
    "tp-docs-update",
    "tp-spike-learn",
]


def _skill(name: str) -> str:
    return (SKILLS / name / "SKILL.md").read_text(encoding="utf-8")


def test_convention_doc():
    text = (SKILLS / "_shared" / "issue-id-placeholders.md").read_text(encoding="utf-8")
    assert CLI in text
    assert "<S>-new-<slug>" in text
    assert len(text.splitlines()) <= 80


def test_each_skill_points_at_convention():
    for name in SEVEN:
        assert "issue-id-placeholders.md" in _skill(name), name


def test_pr_iterate_points_at_convention():
    assert "issue-id-placeholders.md" in _skill("tp-pr-iterate")


def test_numbering_skills_name_cli():
    for name in ("tp-merge-from-main", "tp-design-complete"):
        assert "number_issues.py --base" in _skill(name), name
        assert CLI in _skill(name), name


def _step(text: str, label: str) -> str:
    start = text.index(label)
    end = text.find("\n\n", start)
    return text[start:end]


def test_numbering_steps_use_fetched_origin_base():
    step_2b = _step(_skill("tp-merge-from-main"), "2b. **Number placeholder")
    assert "origin/<base>" in step_2b
    b2 = _step(_skill("tp-design-complete"), "b2. **Number placeholder")
    assert "git fetch origin {base}" in b2
    assert "origin/{base}" in b2
    assert "step 6g" in b2  # names which base, before 6g defines it
    convention = (SKILLS / "_shared" / "issue-id-placeholders.md").read_text(encoding="utf-8")
    assert "git fetch origin <base>" in convention
    assert "origin/<base>" in convention


def test_merge_from_main_step_2b_is_plan_only_under_dry_run():
    step_2b = _step(_skill("tp-merge-from-main"), "2b. **Number placeholder")
    assert "--dry-run" in step_2b
    assert "drop `--commit`" in step_2b
    assert "plan-only" in step_2b


def test_merge_names_refusal():
    assert "unnumbered issue IDs" in _skill("tp-merge")


def test_resolution_boundary_in_merge_from_main():
    text = _skill("tp-merge-from-main")
    for phrase in (
        "**Resolution boundary.**",
        "the one supported way",
        "never hand-rolls conflict-marker parsing",
        "never rewrites a conflicted living doc in place",
        "stays deferred to the human",
    ):
        assert phrase in text, phrase
    assert text.index("**Resolution boundary.**") < text.index("## Steps")


def test_pr_iterate_bullet_has_resolution_boundary():
    text = _skill("tp-pr-iterate")
    start = text.index("**Base moved under the PR")
    end = text.find("\n- **", start + 1)
    assert "Resolution boundary" in text[start:end]
