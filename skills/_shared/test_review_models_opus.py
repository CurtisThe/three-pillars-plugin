"""Guard: reviews and audits always run on Opus (operator ruling 2026-09-23).

Every council persona and the read-only auditor declare `model: opus`, and the
review/audit dispatch sites pin `model="opus"` instead of inheriting a default.
The one allow-listed exception is the borderline comment classifier
(`claude-sonnet-4-6` in tp-pr-fix §3 / tp-pr-iterate step 5), which classifies
existing comments rather than reviewing code — an open question on the
`reviews-always-opus` seed.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
AGENTS = sorted((ROOT / "agents").glob("council-*.md")) + [
    ROOT / "agents" / "tp-readonly-auditor.md", ROOT / "agents" / "tp-certifier.md"]
CLASSIFIER_ALLOW = {"skills/tp-pr-fix/SKILL.md", "skills/tp-pr-iterate/SKILL.md"}


def _model(path: Path) -> str | None:
    m = re.search(r"^model:\s*(\S+)", path.read_text(encoding="utf-8"), flags=re.M)
    return m.group(1) if m else None


@pytest.mark.parametrize("path", AGENTS, ids=lambda p: p.stem)
def test_review_agents_declare_opus(path):
    assert _model(path) == "opus", f"{path.name} must declare model: opus"


def test_council_table_lists_no_sonnet():
    text = (ROOT / "skills" / "council" / "SKILL.md").read_text(encoding="utf-8")
    assert "| sonnet |" not in text


def test_pr_iterate_angles_pin_opus():
    text = (ROOT / "skills" / "tp-pr-iterate" / "SKILL.md").read_text(encoding="utf-8")
    # The angle fan-out step of the round-dir flow (iterate-convergence-budget Task 8.2).
    block = text[text.index("round_scratch.py prepare"):text.index("reproduce.py --round-dir")]
    assert 'model="opus"' in block


@pytest.mark.parametrize("needle", [
    "`ANGLES` set as N top-level `general-purpose` sub-agents, each pinned `model=\"opus\"`",
    "dispatch one `general-purpose` subagent (`model=\"opus\"`)",
    "`general-purpose` subagent, `model=\"opus\"`",
])
def test_orchestrator_review_dispatches_pin_opus(needle):
    text = (ROOT / "skills" / "tp-run-full-design" / "SKILL.md").read_text(encoding="utf-8")
    assert needle in text


def test_design_audit_explorers_pin_opus():
    text = (ROOT / "skills" / "tp-design-audit" / "SKILL.md").read_text(encoding="utf-8")
    assert 'launch exploration agents (pinned `model="opus"`' in text
    assert '### 3. Architecture feasibility (launch parallel agents, pinned `model="opus"`)' in text
    assert 'independent verification tasks, each pinned `model="opus"`' in text


def test_sonnet_only_in_classifier_allow_list():
    review_skills = ["council", "tp-design-audit", "tp-plan-audit", "tp-implementation-audit",
                     "tp-phase-review", "tp-run-full-design", "tp-pr-iterate", "tp-pr-fix"]
    for skill in review_skills:
        rel = f"skills/{skill}/SKILL.md"
        text = (ROOT / rel).read_text(encoding="utf-8")
        if rel in CLASSIFIER_ALLOW:
            continue
        assert "claude-sonnet" not in text and 'model="sonnet"' not in text, rel


def test_pr_iterate_angles_module_pins_opus():
    """The angles-as-data module: every default angle is Opus; no Sonnet/Haiku literal."""
    path = ROOT / "skills" / "tp-pr-iterate" / "scripts" / "angles.py"
    text = path.read_text(encoding="utf-8")
    block = text[text.index("DEFAULT_ANGLES = ["):text.index("def tier(")]
    assert block.count('"model": "opus"') == block.count('"model":') >= 3
    assert "claude-sonnet" not in text and '"model": "sonnet"' not in text
    assert '"model": "haiku"' not in text
