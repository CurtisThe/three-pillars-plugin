"""Tests for design_run_role: the explicit launcher role a design run is launched with."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import design_run_role as drr  # noqa: E402

HOME = Path("/opt/launcher")


@pytest.mark.parametrize("direct,home,has_run,assign,notes", [
    (True, HOME, True, "CLAUDE_LAUNCHER_ROLE=run", 1),
    (True, HOME, False, "CLAUDE_LAUNCHER_ROLE=seat", 1),
    (False, HOME, True, "", 0),
    (True, None, True, "", 1),
])
def test_assignment_cases(direct, home, has_run, assign, notes):
    got, note = drr.assignment(direct, home, supports=lambda h: has_run)
    assert got == assign
    assert len([ln for ln in note.splitlines() if ln]) == notes
    assert "\n" not in note
    if home is None:
        assert note.startswith("W:")
    if assign.endswith("seat"):
        assert "seat" in note
    if assign.endswith("run"):
        assert "run" in note


def test_role_never_inferred_from_env(monkeypatch):
    monkeypatch.setenv("CLAUDE_LAUNCHER_ROLE", "seat")
    assert drr.assignment(True, HOME, supports=lambda h: True)[0] == "CLAUDE_LAUNCHER_ROLE=run"


def test_constants():
    assert (drr.RUN_ROLE, drr.SEAT_ROLE, drr.ROLE_ENV) == ("run", "seat", "CLAUDE_LAUNCHER_ROLE")
