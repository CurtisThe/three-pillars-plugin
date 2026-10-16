"""Tests for `child_spawn_ops.child_env` — the profile pin a spawned child inherits.

design: child-spawn-profile-inherit task 1.2. A child `claude -p` launched by the local
dispatcher must answer with the orchestrator's Claude profile, not the default one: the parent's
`CLAUDE_CONFIG_DIR` names that profile, and the launcher owns that key, so the scrub would
otherwise throw the profile away. The pin re-records it as `CLAUDE_LAUNCHER_FORCE_PROFILE`.
Examples are spec-derived (oracle: `example`, per `skills/_shared/test-fragility.md` §5 — written
from the plan's wording, never from an implementation): the design's launcher-style parent env and
its exact child env, a plain `~/.claude` config dir that gets no pin, an env with no config dir at
all, the caller's dict staying untouched, and that the pin adds one key and nothing else. Nothing
here runs a launcher, a router or `claude`: dicts only.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import child_spawn  # noqa: E402
import launcher_env  # noqa: E402

BG_WAIT_OFF = {"CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS": "0"}
PIN = "CLAUDE_LAUNCHER_FORCE_PROFILE"

# The design's launcher-style parent env: the launcher injected the profile's config dir and the
# local router's base URL, and recorded both as its own.
PROFILED_ENV = {
    "CLAUDE_CONFIG_DIR": "/home/u/.claude-profiles/aris",
    "CLAUDE_LAUNCHER_OWNED": "CLAUDE_CONFIG_DIR,ANTHROPIC_BASE_URL",
    "ANTHROPIC_BASE_URL": "http://127.0.0.1:3457",
    "CLAUDE_CODE_SESSION_ID": "abc",
    "PATH": "p",
}


def test_profiled_parent_env_gets_the_pin() -> None:
    """(a) The design's example, end to end through `child_spawn.child_env`."""
    assert child_spawn.child_env(PROFILED_ENV) == {
        "PATH": "p", **BG_WAIT_OFF, PIN: "aris"}


def test_plain_config_dir_gets_no_pin() -> None:
    """(b) A config dir that is not a profile dir changes nothing — today's answer, unchanged."""
    assert child_spawn.child_env({"CLAUDE_CONFIG_DIR": "/home/u/.claude",
                                  "PATH": "p"}) == {
        "CLAUDE_CONFIG_DIR": "/home/u/.claude", "PATH": "p", **BG_WAIT_OFF}


def test_no_config_dir_gets_no_pin() -> None:
    """(c) No config dir at all is not a profile either."""
    out = child_spawn.child_env({"PATH": "p"})

    assert PIN not in out
    assert out == {"PATH": "p", **BG_WAIT_OFF}


def test_input_is_never_mutated() -> None:
    """(d) The caller's dict survives the call — the caller's own env is a seat's env."""
    before = dict(PROFILED_ENV)

    child_spawn.child_env(PROFILED_ENV)

    assert PROFILED_ENV == before


def test_pin_adds_only_the_profile_key() -> None:
    """(e) Against today's scrub, the pin's whole contribution is the one profile key."""
    assert set(child_spawn.child_env(PROFILED_ENV)) - set(
        launcher_env.strip_launcher_keys(PROFILED_ENV)) == {
            PIN, "CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS"}
