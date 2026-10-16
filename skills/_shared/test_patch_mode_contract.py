"""Patch-mode contract: audit retries edit the artifact, never regenerate it.

design: run-throughput (design.md Behavior 7; detailed-design-part-c.md §Interfaces "Patch
mode"). Task 5.5 pins the generator side: `/tp-design-detail` and `/tp-plan` take
`--patch <findings.json>`, edit in place with Edit (never Write), log one
`patch finding <k> → <section>` Decision Entry per finding, and refuse (BLOCKED) with no
artifact rather than regenerate. `tp-plan` also documents the optional `**Kind**`,
`**Split**` and `**Growth**` task fields. Task 5.6 pins the orchestrator side: an audit
retry dispatches `tp-generator` with `--patch` and never re-runs either generator without it.
Task 5.8 pins the Slot 6 `plan_couplings.py` precheck wiring. Prose checks only.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

import skill_text

SKILLS = Path(__file__).resolve().parent.parent
GENERATORS = ("tp-design-detail", "tp-plan")
GENERATOR_MAX_LINES = 150
ORCH = SKILLS / "tp-run-full-design"
# A backticked generator command span: `/tp-design-detail …` or `/tp-plan …` (not `/tp-plan-audit`).
_GEN_SPAN = re.compile(r"`(/tp-(?:design-detail|plan)(?![\w-])[^`]*)`")


def _text(skill: str) -> str:
    return skill_text.read_skill_text(skill)


def _flat(text: str) -> str:
    return " ".join(text.split())


def _section(text: str, head: str) -> str:
    start = text.index(f"\n## {head}\n")
    end = text.find("\n## ", start + 1)
    return text[start:end if end != -1 else len(text)]


def _frontmatter(text: str) -> str:
    return text.split("---", 2)[1]


@pytest.mark.parametrize("skill", GENERATORS)
def test_argument_hint_names_patch(skill):
    hint = [ln for ln in _frontmatter(_text(skill)).splitlines()
            if ln.startswith("argument-hint:")]
    assert len(hint) == 1 and "--patch <findings.json>" in hint[0], hint


@pytest.mark.parametrize("skill", GENERATORS)
def test_patch_mode_section_edits_never_writes(skill):
    sec = _flat(_section(_text(skill), "Patch mode"))
    assert "--patch <findings.json>" in sec
    assert "Edit" in sec and "never" in sec and "Write" in sec
    assert "never rewrite" in sec.lower() or "never with write" in sec.lower()


@pytest.mark.parametrize("skill", GENERATORS)
def test_patch_mode_logs_one_entry_per_finding(skill):
    sec = _flat(_section(_text(skill), "Patch mode"))
    assert f"[{skill}] patch finding <k> → <section>" in sec
    assert "per finding" in sec


@pytest.mark.parametrize("skill", GENERATORS)
def test_patch_mode_blocks_without_artifact(skill):
    sec = _flat(_section(_text(skill), "Patch mode"))
    assert "BLOCKED" in sec
    assert "never falls back to regeneration" in sec


def test_plan_documents_optional_task_fields():
    flat = _flat(_text("tp-plan"))
    assert "`**Kind**: clerical`" in flat
    assert "`**Split**: <path> | none — <reason>`" in flat
    assert "`**Growth**: +N`" in flat


@pytest.mark.parametrize("skill", GENERATORS)
def test_generator_skill_sizes(skill):
    assert len(_text(skill).splitlines()) <= GENERATOR_MAX_LINES


def _orch_retry_prose() -> str:
    throughput = (ORCH / "throughput.md").read_text(encoding="utf-8")
    skill = skill_text.read_skill_text("tp-run-full-design")
    parts = [_section(throughput, "Retry with advice (audits)")]
    parts += [_section(skill, h) for h in ("Retry-with-advice (audits)",
                                           "Retry-with-advice counter",
                                           "Retry-with-advice escalation")]
    return "\n".join(parts)


def test_orchestrator_retry_dispatches_tp_generator_with_patch():
    sec = _flat(_section((ORCH / "throughput.md").read_text(encoding="utf-8"),
                         "Retry with advice (audits)"))
    assert "`tp-generator`" in sec
    for cmd in ("/tp-design-detail {slug} --auto --patch <F>", "/tp-plan {slug} --auto --patch <F>"):
        assert f"`{cmd}`" in sec, cmd


def test_orchestrator_retry_never_runs_a_generator_without_patch():
    spans = _GEN_SPAN.findall(_orch_retry_prose())
    assert spans, "the retry prose names the generator commands"
    for span in spans:
        assert "--patch" in span, span


def test_throughput_plan_audit_prechecks_run_plan_couplings():
    """run-throughput 5.8: Slot 6 never calls /tp-plan-audit, so it runs the precheck itself."""
    sec = _flat(_section((ORCH / "throughput.md").read_text(encoding="utf-8"),
                         "Plan-audit prechecks"))
    assert "skills/tp-plan-audit/scripts/plan_couplings.py" in sec
    assert "before the Slot 6 reader" in sec
    assert "pre-verified" in sec and "`findings[]`" in sec
    assert '`severity: "medium"`' in sec

