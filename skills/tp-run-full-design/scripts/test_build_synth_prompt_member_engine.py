"""Tests for build_synth_prompt member_engine (local-role-routing 4.1)."""

import pytest

from build_synth_prompt import build_synth_prompt

# Captured at Red time from the unmodified function; never recomputed.
GOLDEN = 'You are the SYNTHESIZER for the `plan-audit` audit slot of the autonomous tp-run-full-design orchestrator.\nYou are a read-only `tp-readonly-auditor` subagent. Read the artifact paths below yourself; weigh the council deliberation; emit ONE fenced ```json block carrying the `audit-return.v1` envelope (schema tp-run-full-design/audit-return/v1).\n\n## Artifacts under audit (read these paths yourself)\n- a.md\n\n## Round 1 — independent verdicts\nEach finding already carries its per-finding `confidence`; carry it forward VERBATIM into the audit-return findings[] (do not invent values).\n### council-ada\n```json\n{"member": "council-ada", "verdict": "pass-with-notes", "findings": []}\n```\n\nMerge + deduplicate the Round-1 findings, compute the overall `verdict` from the confidence/verdict mix exactly as the standalone audit skill would, and emit the audit-return.v1 envelope.\n`severity` (`critical|medium|minor`) is REQUIRED on every finding, independent of its `confidence`: `critical` blocks the artifact\'s purpose, `medium` is a real defect a run or user would hit, `minor` is polish. A finding without it takes the full retry loop (the orchestrator\'s lows rule treats it as not minor).\nEach finding also carries `file` (repo-relative path), `line` (an int, or null when no single line applies) and `run_failure` (the command or test plus the observed failure; an empty string when none) beside its `severity` (`critical|medium|minor`).\nMap-check findings (the state-space Check-mode angle: a better locus or alternative dismissed without evidence) MUST carry `category: "map-check"` exactly, whatever their confidence (keep a member\'s tag; add it if a member omitted it). They question design.md\'s own framing, so the orchestrator never turns them into retry advice; it escalates them straight to the operator.'


def _args():
    r1 = [{"member": "council-ada", "verdict": "pass-with-notes", "findings": []}]
    return (["a.md"], r1, None, "plan-audit")


def test_default_matches_golden():
    assert build_synth_prompt(*_args()) == GOLDEN


def test_opus_equals_default_and_golden():
    assert build_synth_prompt(*_args(), member_engine="opus") == GOLDEN


def test_local_extends_opus_with_gap_pass_brief():
    out = build_synth_prompt(*_args(), member_engine="local")
    assert out.startswith(GOLDEN)
    brief = out[len(GOLDEN):]
    assert "your own pass over the artifacts" in brief
    assert "escape_dispositions[]" in brief
    assert "{from, disposition, defect_class?, served?}" in brief
    for d in ("kept", "dropped", "downgraded", "opus-added"):
        assert d in brief
    assert "sonnet-busy" in brief


def test_unknown_engine_raises():
    with pytest.raises(ValueError):
        build_synth_prompt(*_args(), member_engine="gpt")
