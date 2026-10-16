"""Prose-pin tests for the consumer-repo rule's audit/learn touchpoints.

Task 9.4: the design and plan audits ask the consumer-repo question per
enforcement, the implementation audit has the shipped-promises dimension
and report row, and design-learn records consumer-repo behaviour in
`architecture.md`.

Run with: python3 -m pytest skills/_shared/test_consumer_rule_citations.py

Design refs:
  design: consumer-repo-parity
"""

from __future__ import annotations

from pathlib import Path

_SKILLS = Path(__file__).resolve().parents[1]

DESIGN_AUDIT_MD = _SKILLS / "tp-design-audit" / "SKILL.md"
PLAN_AUDIT_MD = _SKILLS / "tp-plan-audit" / "SKILL.md"
IMPL_AUDIT_MD = _SKILLS / "tp-implementation-audit" / "SKILL.md"
DESIGN_LEARN_MD = _SKILLS / "tp-design-learn" / "SKILL.md"

CONSUMER_RULE_TOKEN = "consumer-repo-rule.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _section(text: str, heading: str, next_marker: str = "\n### ") -> str:
    """Slice out the paragraph/section starting at `heading` up to the next
    `### `-level heading (or end of file)."""
    idx = text.index(heading)
    rest = text[idx:]
    end = rest.find(next_marker, len(heading))
    if end == -1:
        return rest
    return rest[:end]


# ------------------------------------------------------------------ #
# tp-design-audit/SKILL.md — Consumer-repo enforcement section
# ------------------------------------------------------------------ #


def test_design_audit_has_consumer_repo_enforcement_heading():
    text = _read(DESIGN_AUDIT_MD)
    assert "Consumer-repo enforcement" in text


def test_design_audit_consumer_repo_section_cites_rule_and_question():
    text = _read(DESIGN_AUDIT_MD)
    section = _section(text, "Consumer-repo enforcement")
    assert "skills/_shared/consumer-repo-rule.md" in section
    assert CONSUMER_RULE_TOKEN in section
    assert "shipped file" in section
    assert "dev-only" in section


def test_design_audit_consumer_repo_section_precedes_compile_findings():
    text = _read(DESIGN_AUDIT_MD)
    enforcement_idx = text.index("Consumer-repo enforcement")
    compile_idx = text.index("Compile findings")
    assert enforcement_idx < compile_idx


# ------------------------------------------------------------------ #
# tp-plan-audit/SKILL.md — Map-check angle paragraph
# ------------------------------------------------------------------ #


def test_plan_audit_map_check_angle_cites_consumer_repo_rule():
    text = _read(PLAN_AUDIT_MD)
    idx = text.index("Map-check angle (every mode):")
    end = text.find("\n\n", idx)
    paragraph = text[idx:end] if end != -1 else text[idx:]
    assert "skills/_shared/consumer-repo-rule.md" in paragraph
    assert "shipped file" in paragraph


def test_plan_audit_stays_within_line_cap():
    lines = _read(PLAN_AUDIT_MD).splitlines()
    assert len(lines) <= 328


# ------------------------------------------------------------------ #
# tp-implementation-audit/SKILL.md — §7b Shipped promises
# ------------------------------------------------------------------ #


def test_implementation_audit_has_7b_shipped_promises_heading():
    text = _read(IMPL_AUDIT_MD)
    assert "### 7b. Shipped promises" in text


def test_implementation_audit_7b_names_devonly_script_run_if_present():
    text = _read(IMPL_AUDIT_MD)
    section = _section(text, "### 7b. Shipped promises")
    assert "devonly_citation.py" in section
    assert "run-if-present" in section
    scoping_phrases = (
        "in the three-pillars dev repo",
        "this dev repo",
        "the framework's own repo",
        "dev-repo only",
        "framework repo only",
    )
    assert any(phrase in section for phrase in scoping_phrases)


def test_implementation_audit_7b_cites_consumer_repo_rule():
    text = _read(IMPL_AUDIT_MD)
    section = _section(text, "### 7b. Shipped promises")
    assert "skills/_shared/consumer-repo-rule.md" in section


def test_implementation_audit_report_template_has_shipped_promises_row():
    text = _read(IMPL_AUDIT_MD)
    idx = text.index("### 8. Compile findings")
    end = text.find("### 8b.", idx)
    template = text[idx:end] if end != -1 else text[idx:]
    assert "## Shipped Promises" in template


# ------------------------------------------------------------------ #
# tp-design-learn/SKILL.md — step 7 Consumer-repo behaviour sub-bullet
# ------------------------------------------------------------------ #


def test_design_learn_step7_names_consumer_repo_behaviour():
    text = _read(DESIGN_LEARN_MD)
    idx = text.index("7. **Propose updates**")
    end = text.find("\n8. ", idx)
    step7 = text[idx:end] if end != -1 else text[idx:]
    assert "Consumer-repo behaviour" in step7
    assert "architecture.md" in step7
    assert "## Consumer-repo behaviour" in step7


# ------------------------------------------------------------------ #
# forge-parity rule — cited beside the consumer-repo rule in each audit
# (design: forge-interface, Task 2.2)
# ------------------------------------------------------------------ #

FORGE_RULE_TOKEN = "forge-parity-rule.md"


def test_forge_parity_rule_cited_beside_consumer_rule():
    design = _section(_read(DESIGN_AUDIT_MD), "Consumer-repo enforcement")
    assert "skills/_shared/" + FORGE_RULE_TOKEN in design

    plan_text = _read(PLAN_AUDIT_MD)
    idx = plan_text.index("Map-check angle (every mode):")
    end = plan_text.find("\n\n", idx)
    plan = plan_text[idx:end] if end != -1 else plan_text[idx:]
    assert CONSUMER_RULE_TOKEN in plan
    assert "skills/_shared/" + FORGE_RULE_TOKEN in plan

    impl = _section(_read(IMPL_AUDIT_MD), "### 7b. Shipped promises")
    assert CONSUMER_RULE_TOKEN in impl
    assert "skills/_shared/" + FORGE_RULE_TOKEN in impl
