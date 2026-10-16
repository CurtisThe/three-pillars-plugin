"""certification-protocol.md prose pins: the note finding and once-per-design certifier.

design: review-convergence (detailed-design-phase-check.md §F2, Task 12.4). The verdict
join is unchanged — `not-binding`/`false-red` still fold NEEDS WORK and any `unverified`
claim still folds UNVERIFIED — but the *finding* those statuses emit is now a
`certification-note` of severity `minor`, so the post-patch `recheck` carries it as a PR
note. Step 2b also runs the certifier once per design (`cert_once.py should-run`), not on
every Slot 8 attempt. The agent/CLI pins live in `test_certifier_agent.py`; the orchestrator
wiring pins live in `test_certification_wiring_orchestrator.py`.
"""
from __future__ import annotations

from pathlib import Path

PROTOCOL = Path(__file__).resolve().parent / "certification-protocol.md"


def _text() -> str:
    return PROTOCOL.read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    start = text.index(f"\n## {heading}\n")
    end = text.find("\n## ", start + 1)
    return text[start:] if end == -1 else text[start:end]


def test_terminal_rule_says_the_result_is_a_note():
    body = _section(_text(), "Certifier contract")
    assert "`certification-note`" in body


def test_verdicts_section_names_the_note_finding():
    body = _section(_text(), "Verdicts")
    for needle in ("`certification-note`", "`minor`", "invalid:*", "guard-is-subject"):
        assert needle in body, needle


def test_step_2b_runs_the_certifier_once_per_design():
    body = _section(_text(), "Step 2b")
    assert "once per design" in body
    assert "cert_once.py should-run" in body
    assert "earlier records are never reused" not in body


def test_protocol_stays_within_its_line_cap():
    assert len(_text().splitlines()) <= 300
