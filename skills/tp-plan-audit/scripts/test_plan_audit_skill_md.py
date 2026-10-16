"""test_plan_audit_skill_md.py — structured invocation checks for tp-plan-audit.

plugin-mode-parity Task 3.8 [N2]: Step 2's audit_plan.py invocation must use the
$TP_ROOT anchor, not a legacy ~/.claude/skills/ or project-installed path.
run-throughput 5.8: plan_couplings.py runs right after audit_plan.py.

The checks read the shell code spans of the SKILL.md through skill_spans (the
parsed tokens of each call), never the prose; path/script references are covered
by skill_refs (invariant 46).

Run with: pytest skills/tp-plan-audit/scripts/test_plan_audit_skill_md.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SKILL_MD = Path(__file__).resolve().parents[1] / "SKILL.md"
_SHARED = str(Path(__file__).resolve().parents[2] / "_shared")
_RUNNER = "$TP_ROOT/skills/tp-plan-audit/scripts/"


def _calls() -> list[tuple[int, str, list[str]]]:
    """(line, script basename, tokens from the script) of every audit_plan.py /
    plan_couplings.py call in the SKILL.md, from the parsed code spans."""
    if _SHARED not in sys.path:
        sys.path.insert(0, _SHARED)
    skill_spans = pytest.importorskip("skill_spans")
    out: list[tuple[int, str, list[str]]] = []
    text = _SKILL_MD.read_text(encoding="utf-8")
    for line, span, shell in skill_spans.code_spans(text):
        toks = skill_spans.tokens_of(span, shell)
        for i, tok in enumerate(toks):
            base = tok.rsplit("/", 1)[-1]
            if base in ("audit_plan.py", "plan_couplings.py"):
                out.append((line, base, toks[i:]))
    return out


def test_audit_plan_invocation_is_tp_root_anchored():
    """Every audit_plan.py / plan_couplings.py call is $TP_ROOT-anchored: no legacy
    ~/.claude/skills/ or project-installed path survives."""
    calls = _calls()
    assert {b for _, b, _ in calls} == {"audit_plan.py", "plan_couplings.py"}
    for line, base, toks in calls:
        assert toks[0] == _RUNNER + base, f"line {line}: {toks[0]} is not $TP_ROOT-anchored"


def test_plan_couplings_runs_beside_audit_plan():
    """Step 2 runs plan_couplings.py after audit_plan.py, both on the design dir."""
    calls = _calls()
    names = [b for _, b, _ in calls]
    assert names.index("plan_couplings.py") > names.index("audit_plan.py")
    for line, _, toks in calls:
        assert "$DESIGN_DIR" in toks, f"line {line}: call must take $DESIGN_DIR: {toks}"
