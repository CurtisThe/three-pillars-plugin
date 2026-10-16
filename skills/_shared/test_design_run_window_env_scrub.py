"""Tests for `design_run_window_env.plan(..., launcher=True)` (launch-role-precedence Task 1.3).

When the run has a launcher, the window scrubs every launcher name whatever the
seat's env carries, and pins no profile. `launcher=False` plans as before.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import design_run_window_env as dwe  # noqa: E402
from launcher_export_fixture import DIRECT_EXPORT  # noqa: E402
from launcher_which import SCRUB_NAMES  # noqa: E402

PROTECTED = {"TP_LOCAL_MODE", "TP_DESIGN_RUN", "PATH", "HOME"}
OWNED = set(DIRECT_EXPORT["CLAUDE_LAUNCHER_OWNED"].split())
LEFTOVERS = {"CLAUDE_LAUNCHER_FORCE_PROFILE": "personal", "CLAUDE_LAUNCHER_FORCE_BACKEND": "claude",
             "CLAUDE_LAUNCHER_ROLE": "seat"}
ENVS = {
    "export": (dict(DIRECT_EXPORT), OWNED),
    "export+leftovers": ({**DIRECT_EXPORT, **LEFTOVERS}, OWNED),
    "empty": ({}, set()),
    "mixed": ({"CLAUDE_CONFIG_DIR": "/home/u/.claude-profiles/work"}, set()),
}


@pytest.mark.parametrize("name", ENVS)
def test_launcher_scrubs_every_name_and_pins_nothing(name):
    env, owned = ENVS[name]
    assignments, unset, _ = dwe.plan(env, None, launcher=True)
    assert set(unset) == (set(SCRUB_NAMES) | owned) - PROTECTED
    assert not [a for a in assignments if a[0] == "CLAUDE_LAUNCHER_FORCE_PROFILE"]
    assert unset == sorted(set(unset))
    assert not PROTECTED & set(unset)


@pytest.mark.parametrize("name", ENVS)
def test_launcher_local_mode_still_assigned(name):
    assignments, unset, _ = dwe.plan(ENVS[name][0], "wait", launcher=True)
    assert assignments == [("TP_LOCAL_MODE", "wait")]
    assert "TP_LOCAL_MODE" not in unset


def test_launcher_hostile_owned_token_dropped_with_one_note():
    env = {**DIRECT_EXPORT, "CLAUDE_LAUNCHER_OWNED": "CLAUDE_LAUNCHER_OWNED $(evil) FOO"}
    _, unset, notes = dwe.plan(env, None, launcher=True)
    assert "$(evil)" not in " ".join(unset)
    assert "FOO" in unset
    assert len(notes) == 1


@pytest.mark.parametrize("name", ENVS)
def test_default_matches_launcher_false(name):
    env = ENVS[name][0]
    assert dwe.plan(env, "fallback") == dwe.plan(env, "fallback", launcher=False)


def test_no_launcher_still_pins_profile():
    assignments, unset, _ = dwe.plan(DIRECT_EXPORT, None, launcher=False)
    assert ("CLAUDE_LAUNCHER_FORCE_PROFILE", "personal") in assignments
    assert "CLAUDE_CONFIG_DIR" not in unset
