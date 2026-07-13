"""Invariants for skills/tp-implementation-audit/SKILL.md.

Enforces the interactive-path docs-currency contract added by the
parallel-design-worktrees Phase 9: step 10 prompts to invoke
/tp-design-learn (default yes); the prompt is interactive-only and
must not fire in --auto.

Run with: pytest skills/tp-implementation-audit/scripts/test_implementation_audit_skill_md.py -q
"""

from __future__ import annotations

import re
from pathlib import Path

SKILL_MD = Path(__file__).resolve().parents[1] / "SKILL.md"


def _read() -> str:
    return SKILL_MD.read_text(encoding="utf-8")


def test_step_10_prompts_to_invoke_learn() -> None:
    text = _read()
    assert "/tp-design-learn" in text, "step 10 must reference /tp-design-learn"
    assert re.search(
        r"Run\s+`?/tp-design-learn[^`]*`?\s+now[^?]*\?\s*\(yes\s*/\s*no",
        text,
    ), "step 10 must contain a yes/no prompt to invoke /tp-design-learn"


def test_step_10_yes_default_documented() -> None:
    text = _read()
    assert re.search(
        r"default\s+yes",
        text,
        re.IGNORECASE,
    ), "step 10 prompt must document 'default yes' so empty response = invoke"


def test_auto_mode_unchanged_no_prompt() -> None:
    text = _read()
    auto_section = text.split("## Auto Mode", 1)
    assert len(auto_section) == 2, "Auto Mode section must exist"
    body = auto_section[1]
    assert (
        "/tp-run-full-design" in body and "Tier 5" in body
    ), "Auto Mode block must name /tp-run-full-design Tier 5 as the autonomous learn-chain owner"
    assert re.search(
        r"prompt-to-invoke-`?/tp-design-learn`?",
        body,
    ), "Auto Mode block must explicitly state the step-10 prompt is skipped in --auto"


def test_auto_mode_contract_intact() -> None:
    text = _read()
    assert re.search(
        r"in\s+`--auto`,\s*this\s+skill\s+writes\s+a\s+verdict\s+and\s+never\s+edits\s+code",
        text,
        re.IGNORECASE,
    ), "Shape C verdict-only contract sentence must be preserved verbatim"
    auto_body = text.split("## Auto Mode", 1)[1]
    assert (
        "must NOT invoke" in auto_body or "must not invoke" in auto_body
    ), "Auto Mode block must explicitly forbid invoking /tp-design-learn from --auto"
