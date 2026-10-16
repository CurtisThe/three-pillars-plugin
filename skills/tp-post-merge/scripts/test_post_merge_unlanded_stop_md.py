"""Doc pins: the unlanded-commit backstop is wired end to end in SKILL.md.

design: review-log-survives-teardown. Step 5's cheap-tier block must STOP (not fall
back to steps c-h) on an `unlanded` refusal, and the inline path must run the same
check before step c, failing closed.

Run with: pytest skills/tp-post-merge/scripts/test_post_merge_unlanded_stop_md.py -q
"""
from __future__ import annotations

import re
from pathlib import Path

SKILL_MD = Path(__file__).resolve().parents[1] / "SKILL.md"


def _text() -> str:
    return SKILL_MD.read_text(encoding="utf-8")


def _cheap_block(text: str) -> str:
    match = re.search(r"<!-- cheap-tier:runbook -->.*?<!-- /cheap-tier -->", text, re.DOTALL)
    assert match, "cheap-tier:runbook block not found"
    return match.group(0)


def _inline_gate(text: str) -> str:
    match = re.search(r"Unlanded-commit check.*?(?=\n\s*c\.\s)", text, re.DOTALL)
    assert match, "inline unlanded check not found before step c"
    return match.group(0)


def test_cheap_tier_refusal_with_unlanded_stops_not_falls_back():
    block = _cheap_block(_text())
    assert re.search(r"`unlanded`.{0,200}\bSTOP", block, re.DOTALL)
    assert "deletes nothing" in block
    assert "not fall back" in block


def test_fallback_clause_excludes_unlanded_refusal():
    block = _cheap_block(_text())
    fallback = block[block.index("Anything else"):]
    assert "any other refusal" in fallback.split("runs today's steps c")[0]


def test_inline_path_runs_check_before_step_c():
    text = _text()
    gate = _inline_gate(text)
    assert text.index("Unlanded-commit check") < text.index("\n   c. **Detect and remove")
    assert "teardown.py --unlanded" in gate
    assert "--slug {name}" in gate


def test_inline_check_is_fail_closed_and_stops():
    gate = _inline_gate(_text())
    assert "STOP" in gate
    assert "fail-closed" in gate
    assert "delete nothing" in gate


def test_remedy_names_the_base_not_just_push():
    gate = _inline_gate(_text())
    assert "land" in gate and "{base}" in gate
