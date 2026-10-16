"""Structured checks over skills/council/SKILL.md for ORCHESTRATOR MODE.

/council --orchestrator is a per-round dispatcher. The contract is read from the
parsed code spans (skill_spans) and the shipped round-bundle schema, never from
the prose wording:
  - the `/council --orchestrator ...` CLI span carries the documented flags
  - orchestrator-only flags appear in no span before that CLI span (standalone
    /council is unchanged without the flag), bar the STEP-0 routing span
  - the round-bundle schema it names is a shipped schema file
  - members are dispatched by `council-{name}` agent ref (a top-level fan-out)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
SKILL_MD = _HERE / "SKILL.md"
_SHARED = str(_HERE.parent / "_shared")
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)
SCHEMAS = _HERE.parent / "tp-run-full-design" / "schemas"

ORCH_ONLY = ("--round", "--artifacts", "--round1", "--code-input")


def _spans() -> list[tuple[int, list[str]]]:
    skill_spans = pytest.importorskip("skill_spans")
    return [
        (line, skill_spans.tokens_of(span, shell))
        for line, span, shell in skill_spans.code_spans(SKILL_MD.read_text(encoding="utf-8"))
    ]


def _cli() -> tuple[int, list[str]]:
    for line, toks in _spans():
        if toks[:2] == ["/council", "--orchestrator"] and "--round" in toks:
            return line, toks
    raise AssertionError("no `/council --orchestrator --round ...` CLI span")


def test_cli_carries_orchestrator_flags():
    _, toks = _cli()
    for flag in ("--orchestrator", "--round", "--members", "--artifacts", "--round1"):
        assert any(flag in t for t in toks), f"CLI span must carry {flag}"


def test_step0_routes_orchestrator_and_keeps_parse_order():
    cli_line, _ = _cli()
    before = [(ln, t) for ln, t in _spans() if ln < cli_line]
    tokens = {tok for _, t in before for tok in t}
    # tp-allow-fragile: --orchestrator/--quick/--duo are CLI flag names (the interface)
    assert {"--orchestrator", "--quick", "--duo"} <= tokens
    assert any(t[:2] == ["if", "--orchestrator"] for _, t in before), "STEP-0 branch span"


def test_orchestrator_only_flags_absent_before_cli():
    cli_line, _ = _cli()
    for line, toks in _spans():
        if line < cli_line:
            leaked = [f for f in ORCH_ONLY if f in toks]
            assert not leaked, f"line {line}: orchestrator-only {leaked} before the CLI"


def test_round_bundle_schema_is_shipped():
    cli_line, _ = _cli()
    named = [
        tok for ln, t in _spans() if ln > cli_line for tok in t
        if tok.startswith("council-round-bundle.v")
    ]
    assert named, "the round-bundle schema must be named in a code span"
    for tok in named:
        assert (SCHEMAS / f"{tok}.json").is_file(), f"{tok} is not a shipped schema"


def test_members_dispatched_by_agent_ref():
    cli_line, _ = _cli()
    assert any(
        ln > cli_line and t == ["council-{name}"] for ln, t in _spans()
    ), "members must be dispatched as top-level `council-{name}` agents"


def test_skill_refs_clean():
    skill_refs = pytest.importorskip("skill_refs")
    report = skill_refs.check(_HERE.parents[1], [SKILL_MD])
    assert not report.issues
