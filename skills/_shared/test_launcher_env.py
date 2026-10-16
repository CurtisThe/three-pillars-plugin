"""Tests for `launcher_env.py` — the launcher keys a spawned child must not inherit.

main-thread-direct-backend task 1.1 (design §S1). A child launched by `child_spawn` starts in the
child's folder, and its launcher must plan the route from that folder; a parent's forced backend,
its role and every env var the parent's launcher owns are that plan leaking into the child. The
examples are spec-derived (oracle: `example`, per `skills/_shared/test-fragility.md` §5 — written
from the design's wording, never from an implementation): one concrete seat env and its expected
child env, the separator variants of the owned list, a name the env lacks, an env with no launcher
keys at all, the caller's dict staying untouched, and the one kept value — a forced `strata`
backend, which the Homelab launcher exports on purpose in `backend.py` `_run_strata` so a Strata
window's children stay local. Nothing here runs a launcher, a router or `claude`: dicts and argv
lists only.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import child_spawn  # noqa: E402
import launcher_env  # noqa: E402

BG_WAIT_OFF = {"CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS": "0"}

# The design's seat env: a direct seat launched through the launcher, so the launcher has forced
# the `claude` backend, named the role and recorded the two keys it injected.
SEAT_ENV = {
    "CLAUDE_LAUNCHER_FORCE_BACKEND": "claude",
    "CLAUDE_LAUNCHER_ROLE": "seat",
    "CLAUDE_LAUNCHER_OWNED": "ANTHROPIC_BASE_URL,ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "ANTHROPIC_BASE_URL": "http://127.0.0.1:3457",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL": "strata",
    "CLAUDE_CODE_SESSION_ID": "abc",
    "PATH": "p",
}


def test_seat_env_is_scrubbed() -> None:
    """(a) The design's example, end to end through `child_spawn.child_env`."""
    assert child_spawn.child_env(SEAT_ENV) == {"PATH": "p", **BG_WAIT_OFF}


def test_strip_drops_launcher_keys_and_owned_names() -> None:
    """The three launcher keys and every name the owned list carries all go."""
    out = launcher_env.strip_launcher_keys(SEAT_ENV)

    assert out == {"PATH": "p", "CLAUDE_CODE_SESSION_ID": "abc"}
    assert launcher_env.owned_keys(SEAT_ENV) == {"ANTHROPIC_BASE_URL",
                                                 "ANTHROPIC_DEFAULT_HAIKU_MODEL"}


def test_owned_list_separators() -> None:
    """(b) Commas, colons and whitespace all separate names — the launcher writes the list, so
    the split follows what it can emit rather than one pinned spelling. Every variant names the
    same two keys, so every one strips exactly those two."""
    for owned in ("A,B", "A: B", " A\t B\n", "A,,B", "A:B"):
        out = launcher_env.strip_launcher_keys({"CLAUDE_LAUNCHER_OWNED": owned,
                                                "A": "1", "B": "2", "PATH": "p"})
        assert out == {"PATH": "p"}, owned


def test_owned_name_absent_from_env() -> None:
    """(c) An owned name the env lacks raises nothing — the list is the launcher's record, not a
    claim that the key is present."""
    out = launcher_env.strip_launcher_keys({"CLAUDE_LAUNCHER_OWNED": "GONE_KEY,PATH",
                                            "PATH": "p"})

    assert out == {}
    assert launcher_env.owned_keys({"PATH": "p"}) == set()
    assert launcher_env.owned_keys({"CLAUDE_LAUNCHER_OWNED": " ,:,, "}) == set()


def test_env_without_launcher_keys_is_unchanged() -> None:
    """(d) No launcher keys means nothing to strip; the child env is today's answer."""
    assert launcher_env.strip_launcher_keys({"PATH": "p"}) == {"PATH": "p"}
    assert child_spawn.child_env({"PATH": "p"}) == {"PATH": "p", **BG_WAIT_OFF}


def test_input_is_never_mutated() -> None:
    """(e) The caller's dict survives the call — the caller's own env is a seat's env."""
    before = dict(SEAT_ENV)

    child_spawn.child_env(SEAT_ENV)
    launcher_env.strip_launcher_keys(SEAT_ENV)

    assert SEAT_ENV == before


def test_forced_strata_backend_is_kept() -> None:
    """(f) A forced `strata` backend is the launcher's own child-stays-local export, so a Strata
    window's children keep planning locally."""
    out = launcher_env.strip_launcher_keys({"CLAUDE_LAUNCHER_FORCE_BACKEND": "strata",
                                            "PATH": "p"})

    assert out == {"CLAUDE_LAUNCHER_FORCE_BACKEND": "strata", "PATH": "p"}
    assert child_spawn.child_env({"CLAUDE_LAUNCHER_FORCE_BACKEND": "strata",
                                  "PATH": "p"}) == {"CLAUDE_LAUNCHER_FORCE_BACKEND": "strata",
                                                    "PATH": "p", **BG_WAIT_OFF}


def test_child_starts_through_the_path_launcher() -> None:
    """(g) With no override the child starts through the PATH `claude` — the launcher, which
    re-plans the route from the child's folder. Index 4 follows `timeout -k <grace> <max>`."""
    argv = child_spawn.host_argv("three-pillars:tp-runbook", "haiku",
                                 "/w/.claude/worktrees/child-spawn/ab12cd34.prompt.md",
                                 "uuid-1", env={"PATH": "p"}, cwd="/w")

    assert argv[:4] == ["timeout", "-k", "30", "1800"]
    assert argv[4] == "claude"
