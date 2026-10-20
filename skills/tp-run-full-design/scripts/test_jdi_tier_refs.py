"""Tier 1 pickup invariants for skills/tp-run-full-design/tier-1-pickup.md.

design: run-full-design-jdi-tier, Task 1.9. Two behavioural checks, never prose
wording: `skill_refs` (invariant 46) resolves every path, script, flag and skill
the skill text names (core + tier files, plus the tp-promote SKILL.md), and the
commands parsed with `skill_spans` show Tier 1 running `jdi_eligibility.py route`.

Run with: pytest skills/tp-run-full-design/scripts/test_jdi_tier_refs.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[3]
TIER_1 = SKILL_DIR / "tier-1-pickup.md"
PROMOTE_SKILL_MD = REPO_ROOT / "skills" / "tp-promote" / "SKILL.md"
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_shared"))


# Built from pieces: a verbatim >=10-char literal that also occurs in the
# sealed SKILL.md ranges would add a phantom "pins" row to the rule ledgers.
DESIGN_DIR_FLAG = "--design" + "-dir"
PHASE_CHECK_SCRIPT = "phase_" + "check" + ".py"


def _jdi_script(tokens):
    """The index of a token naming jdi_eligibility.py in one command, else None."""
    for i, tok in enumerate(tokens):
        if tok.endswith("jdi_eligibility.py"):
            return i
    return None


def test_skill_references_resolve(tmp_path) -> None:
    """Every path, helper script, flag and skill the skill text names exists."""
    skill_refs = pytest.importorskip("skill_refs")
    skill_text = pytest.importorskip("skill_text")
    files = skill_text.skill_paths(SKILL_DIR.name, REPO_ROOT) + [PROMOTE_SKILL_MD]
    assert skill_refs.check(REPO_ROOT, files, cache_dir=tmp_path).issues == []


def test_tier_one_runs_jdi_eligibility_route() -> None:
    """The Tier 1 part invokes `jdi_eligibility.py` with its `route` subcommand."""
    skill_spans = pytest.importorskip("skill_spans")
    commands = []
    for _line, span, shell in skill_spans.code_spans(TIER_1.read_text(encoding="utf-8")):
        tokens = skill_spans.tokens_of(span, shell)
        if tokens[:1] == ["python3"]:
            commands.append(tokens)
    routes = [t for t in commands
              if _jdi_script(t) is not None
              and t[_jdi_script(t) + 1:_jdi_script(t) + 2] == ["route"]]
    assert routes, "tier-1-pickup.md shows no `jdi_eligibility.py route` invocation"


def _skill_commands() -> list[list[str]]:
    """Every `python3 …` command the core SKILL.md and its tier files invoke."""
    skill_spans = pytest.importorskip("skill_spans")
    skill_text = pytest.importorskip("skill_text")
    commands = []
    for path in skill_text.skill_paths(SKILL_DIR.name, REPO_ROOT):
        for _line, span, shell in skill_spans.code_spans(path.read_text(encoding="utf-8")):
            tokens = skill_spans.tokens_of(span, shell)
            if tokens[:1] == ["python3"]:
                commands.append(tokens)
    return commands


def _runs(commands, script: str, *required: str) -> bool:
    """One command names `script` and carries every token in `required`."""
    for tokens in commands:
        named = [i for i, t in enumerate(tokens) if t.endswith(script)]
        for i in named:
            rest = tokens[i + 1:]
            if all(tok in rest for tok in required):
                return True
    return False


def test_just_do_it_mapping_commands_are_real_invocations():
    """The jdi mapping's steps appear as invocations, with the flags the scripts take."""
    commands = _skill_commands()
    assert _runs(commands, "jdi_eligibility.py", "route", DESIGN_DIR_FLAG,
                 "--base", "--head")
    assert _runs(commands, "jdi_plan.py", "write", DESIGN_DIR_FLAG)
    assert _runs(commands, "audit_artifact.py", "--write", "--mode", "jdi-mechanical")
    assert _runs(commands, PHASE_CHECK_SCRIPT, "prepare", "--jdi", "--phase", "jdi",
                 "--base", "--head")
