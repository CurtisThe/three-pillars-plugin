"""Pins the step-7d Security paragraph and the `## Security` template row.

The doc contract for design review-convergence task 9.7: step 7d runs
`trust_boundary.py --base <base> --head HEAD`, reads the brief and applies the
security bar; the step-8 template gains a `## Security` row between
`## Shipped Promises` and `## Cross-Phase Drift`.

Run with: pytest skills/tp-implementation-audit/scripts/test_impl_audit_security_md.py -q
"""
from __future__ import annotations

import re
from pathlib import Path

SKILL_MD = Path(__file__).resolve().parents[1] / "SKILL.md"


def _text() -> str:
    return SKILL_MD.read_text(encoding="utf-8")


def test_step_7d_security_paragraph_exists():
    assert "**7d. Security.**" in _text()


def test_step_7d_paragraph_cites_cli_and_bar():
    para = re.search(
        r"\*\*7d\. Security\.\*\*.*?(?=### 8\.)", _text(), re.S
    )
    assert para is not None
    body = para.group(0)
    assert "trust_boundary.py --base" in body
    assert "demonstrated exploit path" in body


def test_step_7d_is_between_7c_and_step_8():
    text = _text()
    fragility = text.index("**7c. Fragility.**")
    security = text.index("**7d. Security.**")
    step8 = text.index("### 8. Compile findings")
    assert fragility < security < step8


def _template_lines() -> list:
    text = _text()
    return text[text.index("### 8. Compile findings"):].splitlines()


def test_template_has_security_row():
    lines = _template_lines()
    assert "## Security" in lines


def test_template_security_row_placement():
    lines = _template_lines()
    security = lines.index("## Security")
    assert lines.index("## Shipped Promises") < security
    assert security < lines.index("## Cross-Phase Drift")


def test_template_security_row_text():
    lines = _template_lines()
    row = lines[lines.index("## Security") + 1]
    assert "demonstrated exploit path" in row
    assert "No findings." in row
