"""Carve-out tests for worktree_isolation_guard.orchestration_only_staged().

fable-escalation 6.1: the seat's paper-trail carve-out widens from the
orchestration slot alone to a tuple that also admits the repo escalation
layer under `three-pillars-docs/escalations/`. Every other path still fails
the predicate, so the isolation guard keeps blocking design work in the seat.

Pure predicate tests — no git, no tmp repos (skills/_shared/test-fragility.md).

Design refs:
  - three-pillars-docs/completed-tp-designs/fable-escalation/detailed-design.md
    (§Interfaces: worktree_isolation_guard.py; §Data Flow)
  - three-pillars-docs/completed-tp-designs/fable-escalation/plan.md (Task 6.1)
"""

from __future__ import annotations

import pytest

from worktree_isolation_guard import orchestration_only_staged

ORCH = "three-pillars-docs/tp-designs/orchestration/"
ESC = "three-pillars-docs/escalations/"


def test_escalations_only_passes():
    assert orchestration_only_staged([
        ESC + "lessons.md",
        ESC + "rulings/quiet-watch-20261011-abcdef.md",
    ]) is True


def test_escalations_and_orchestration_together_pass():
    assert orchestration_only_staged([
        ESC + "lessons.md",
        ORCH + "handoff.md",
    ]) is True


def test_escalations_plus_code_fails():
    assert orchestration_only_staged([
        ESC + "lessons.md",
        "skills/foo.py",
    ]) is False


def test_orchestration_only_still_passes():
    assert orchestration_only_staged([ORCH + "handoff.md"]) is True


@pytest.mark.parametrize("path", [
    "three-pillars-docs/escalations-x/a.md",
    "three-pillars-docs/escalationsx/a.md",
    "three-pillars-docs/a-escalations/b.md",
    "docs/escalations/lessons.md",
])
def test_sibling_and_unrelated_dirs_fail(path):
    assert orchestration_only_staged([path]) is False


def test_empty_and_none_fail_closed():
    assert orchestration_only_staged([]) is False
    assert orchestration_only_staged(None) is False
