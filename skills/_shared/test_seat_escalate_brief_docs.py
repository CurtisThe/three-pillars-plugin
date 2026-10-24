"""Token pins for the run brief's question rule (seat-escalate-first Task 2.4).

A question the seed, docs and code cannot settle goes through
`skills/_shared/escalation.md` and is never asked as prose in the run's window.
Token pins on the template's `## Decisions` section only (test-fragility.md).
"""
from __future__ import annotations

import re
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent / "seat-brief-template.md"


def _decisions() -> str:
    text = TEMPLATE.read_text(encoding="utf-8")
    start = text.index("## Decisions")
    nxt = text.find("\n## ", start + 1)
    section = text[start:] if nxt == -1 else text[start:nxt]
    return re.sub(r"\s+", " ", section)


def test_decisions_section_forbids_prose_questions():
    section = _decisions()
    assert "never as prose" in section
    assert "Ask in this window" not in section


def test_decisions_section_routes_questions_through_escalation():
    assert "skills/_shared/escalation.md" in _decisions()
