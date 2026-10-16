"""test_seat_launch_docs.py — the seat launch and the direct-main-thread rule are documented.

design: main-thread-direct-backend 1.5 (S5)

A main thread (the seat, a run orchestrator) must talk to Anthropic directly; only a spawned
child may be routed to the local backend. Three docs carry that to an operator: `topology.md`
gets a `## Seat launch` section naming the seat launch and the no-launcher case, the worktree
skill's `seat` verb points at that section instead of re-describing it, and `strata-spawn.md`
states the rule where its loop spawns Strata. Prose pins only — see
`skills/_shared/test-fragility.md`: tokens that carry the meaning, never the wording around
them. The pro-exclusive worktree skill is absent from free-tier trees (release leak guard), so
it is found by glob and its pin skips when the file is missing.
"""
from __future__ import annotations

from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
TOPOLOGY = HERE / "topology.md"
SPAWN = HERE / "strata-spawn.md"
# the pro-tier worktree skill is absent from free-tier trees (release leak guard): find it by glob
WORKTREE = next(iter(sorted(HERE.parent.glob("*worktree/SKILL.md"))), None)


def _flat(text: str) -> str:
    return " ".join(text.split())


def _section(text: str, heading: str) -> str:
    """The body under `heading`, up to the next `## ` heading (or end of file)."""
    assert heading in text, f"no {heading!r} section"
    body = text.split(heading, 1)[1]
    return body.split("\n## ", 1)[0]


def test_topology_names_the_seat_launch():
    body = _flat(_section(TOPOLOGY.read_text(encoding="utf-8"), "## Seat launch"))
    for token in ("CLAUDE_LAUNCHER_ROLE=seat", "claude --seat"):
        assert token in body, token


def test_topology_covers_the_routed_and_no_launcher_cases():
    body = _flat(_section(TOPOLOGY.read_text(encoding="utf-8"), "## Seat launch"))
    assert "hybrid" in body and "preflight" in body, body
    assert "already direct" in body, body


def test_seat_launch_section_precedes_the_cheatsheet():
    text = TOPOLOGY.read_text(encoding="utf-8")
    assert text.index("## Seat launch") < text.index("## Quick-Reference Cheatsheet")


def test_worktree_seat_verb_points_at_the_section():
    if WORKTREE is None:
        pytest.skip("the pro-exclusive worktree skill is absent in the free bundle")
    body = _flat(_section(WORKTREE.read_text(encoding="utf-8"), "## `seat"))
    assert "topology.md" in body and "Seat launch" in body, body


def test_strata_spawn_states_main_threads_run_direct():
    text = SPAWN.read_text(encoding="utf-8")
    sentences = _flat(text).split(". ")
    pinned = [s for s in sentences
              if "main thread" in s and "direct" in s and "child session" in s]
    assert pinned, "no sentence says main threads run direct, Strata only in child sessions"
    assert "child-spawn.md" in text
