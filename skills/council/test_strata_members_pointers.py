"""Every council fan-out site points at strata-members.md; Slot 8 does not."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "_shared"))

import skill_text  # noqa: E402

SKILLS = Path(__file__).resolve().parent.parent
POINTER = "strata-members.md"


def _read(rel: str) -> str:
    if rel == "tp-run-full-design/SKILL.md":
        return skill_text.read_skill_text("tp-run-full-design")
    return (SKILLS / rel).read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    start = text.index(heading)
    rest = start + len(heading)
    m = re.search(r"^#{1,6} ", text[rest:], re.M)
    end = rest + m.start() if m else len(text)
    return text[start:end]


def test_council_skill_points_at_strata_members():
    assert POINTER in _read("council/SKILL.md")


def test_run_full_design_points_at_strata_members():
    assert POINTER in _read("tp-run-full-design/SKILL.md")


def test_plan_audit_points_at_strata_members():
    assert POINTER in _read("tp-plan-audit/SKILL.md")


def test_plan_audit_step3_says_serial_when_local():
    step3 = _section(_read("tp-plan-audit/SKILL.md"), "### Step 3: Council")
    assert POINTER in step3
    assert "serial" in step3 and "council_member" in step3 and "local" in step3


def test_slot8_sections_have_no_pointer():
    text = _read("tp-run-full-design/SKILL.md")
    for heading in ("### Slot 8 — `impl-audit`", "### Step 2 — `impl-audit` slot"):
        assert POINTER not in _section(text, heading)
