"""Wiring pins: the four consumers cite skills/_shared/state-space-protocol.md."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

SKILLS = Path(__file__).resolve().parent.parent
PROTOCOL = "skills/_shared/state-space-protocol.md"
LINT = 'python3 "$TP_ROOT"/skills/_shared/state_space_lint.py'

CONSUMERS = ["tp-design", "tp-design-audit", "tp-plan-audit", "tp-promote"]


def _text(skill: str) -> str:
    return (SKILLS / skill / "SKILL.md").read_text(encoding="utf-8")


def _line_count(text: str) -> int:
    return len(text.splitlines())


def _step(text: str, marker: str) -> str:
    """The numbered step (or ### subsection) starting at the first line matching marker."""
    lines = text.splitlines()
    start = next(i for i, ln in enumerate(lines) if re.match(marker, ln))
    fenced = False
    for j in range(start + 1, len(lines)):
        if lines[j].lstrip().startswith("```"):
            fenced = not fenced
        elif not fenced and re.match(r"^(\d+[a-z]?\.\s|#{2,3}\s)", lines[j]):
            return "\n".join(lines[start:j])
    return "\n".join(lines[start:])


@pytest.mark.parametrize("skill", CONSUMERS)
def test_cites_protocol(skill):
    assert PROTOCOL in _text(skill)


@pytest.mark.parametrize("skill", CONSUMERS)
def test_under_file_size_cap(skill):
    # The per-design line budget was a one-time plan check; the lasting limit
    # is the framework's 500-line hard cap (invariant #34).
    assert _line_count(_text(skill)) < 500


@pytest.mark.parametrize("skill,marker", [
    ("tp-design", r"^7\. "),
    ("tp-promote", r"^8\. "),
])
def test_lint_invocation_is_advisory_in_step(skill, marker):
    step = _step(_text(skill), marker)
    assert LINT in step
    assert "advisory" in step or "warn-only" in step


def test_promote_persists_section_and_html_format():
    text = _text("tp-promote")
    assert "## State space" in _step(text, r"^7\. ")
    assert re.search(r"HTML briefing[^\n]*same (question )?format", _step(text, r"^5\. "))


@pytest.mark.parametrize("skill", ["tp-design-audit", "tp-plan-audit"])
def test_audits_name_map_check_angle(skill):
    assert "dismissed without evidence" in _text(skill)


def test_map_check_never_misalignment():
    assert "MEDIUM finding (not MISALIGNMENT" in _text("tp-design-audit")
    assert "never MISALIGNMENT" in _text("tp-plan-audit")
    for skill in ("tp-design-audit", "tp-plan-audit"):
        assert "never auto-applied" in _text(skill) or "never applied to plan.md" in _text(skill)


def test_design_auto_lint_runs_before_pass_entry():
    auto = _text("tp-design").split("## Auto Mode", 1)[1]
    assert LINT in auto
    assert auto.index(LINT) < auto.index("**PASS (exit 0)**")
    assert "never changes this skill's exit code" in auto


ESCALATION_TOKENS = {"retry-exhausted", "certification-unverified", "map-check-escalated"}


def _escalation_tokens(text: str) -> set[str]:
    """The `[orchestrator/<audit-slot>] <token>` decision-log entries the orchestrator's
    `## Retry-with-advice escalation` section appends: one per escalation trigger."""
    start = text.index("\n## Retry-with-advice escalation\n")
    section = text[start:text.index("\n## ", start + 1)]
    return set(re.findall(r"\[orchestrator/<audit-slot>\] ([a-z][a-z-]*)", section))


def test_orchestrator_exempts_map_check_from_retry_advice():
    sys.path.insert(0, str(SKILLS / "tp-run-full-design" / "scripts"))
    from build_synth_prompt import MAP_CHECK_CATEGORY
    text = (SKILLS / "tp-run-full-design" / "SKILL.md").read_text(encoding="utf-8")
    assert f'category: "{MAP_CHECK_CATEGORY}"' in text
    assert "**Map-check exemption:**" in text
    assert "never** re-spawn advice" in text
    # the trigger fires under any verdict and is a named escalation trigger
    assert "under **any** verdict" in text
    # the audit loop's escalation triggers are a closed set of three, read as the
    # decision-log tokens its section appends (wording and order of the prose are free)
    assert _escalation_tokens(text) == ESCALATION_TOKENS
    assert "map-check-escalated" in text
    assert "exactly one escalation trigger" not in text


def test_plan_audit_auto_never_applies_map_check():
    assert "map-check — escalated to operator" in _text("tp-plan-audit")
