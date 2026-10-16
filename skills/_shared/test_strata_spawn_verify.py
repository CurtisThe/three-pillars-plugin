"""Tests for strata_spawn.mark / verify over a fixture router log (design: local-role-routing 2.2)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import strata_spawn  # noqa: E402

AGENT = "abcdef12deadbeef"
A8 = AGENT[:8]

LOCAL = "local"
BUSY_HELD = "FALLBACK upstream (slot held by 880ace71)"
BUSY_AGENT = "FALLBACK upstream (agent-busy 99aa88bb)"
DOWN = "FALLBACK upstream (upstream-down)"


def _post(agent, route):
    return (f"[2026-10-08T10:00:00] POST /v1/messages  model=claude-haiku  sess=11111111  "
            f"agent={agent}  -> {route}\n")


def _setup(tmp_path, before=(), after=()):
    log = tmp_path / "router.log"
    log.write_text("".join(_post(a, r) for a, r in before), encoding="utf-8")
    env = {"TP_LOCAL_LOG": str(log)}
    since = strata_spawn.mark(env)
    with open(log, "a", encoding="utf-8") as fh:
        fh.write("".join(_post(a, r) for a, r in after))
    return env, since


def test_mark_is_file_size(tmp_path):
    log = tmp_path / "router.log"
    log.write_text(_post(A8, LOCAL), encoding="utf-8")
    assert strata_spawn.mark({"TP_LOCAL_LOG": str(log)}) == log.stat().st_size


def test_mark_missing_log_is_zero(tmp_path):
    assert strata_spawn.mark({"TP_LOCAL_LOG": str(tmp_path / "none.log")}) == 0


def test_all_local_is_strata(tmp_path):
    env, since = _setup(tmp_path, after=[(A8, LOCAL)] * 2)
    got = strata_spawn.verify(AGENT, since, env)
    assert got["served"] == "strata"
    assert got["local_requests"] == 2 and got["fallback_requests"] == 0


def test_busy_only_is_fallback_busy(tmp_path):
    env, since = _setup(tmp_path, after=[(A8, BUSY_HELD), (A8, BUSY_AGENT)])
    got = strata_spawn.verify(AGENT, since, env)
    assert got["served"] == "fallback-busy"
    assert got["fallback_requests"] == 2 and got["local_requests"] == 0
    assert got["fallback_reasons"] == ["880ace71", "99aa88bb"]


def test_busy_mixed_with_local_is_fallback_busy(tmp_path):
    env, since = _setup(tmp_path, after=[(A8, LOCAL), (A8, BUSY_HELD)])
    got = strata_spawn.verify(AGENT, since, env)
    assert got["served"] == "fallback-busy"
    assert got["local_requests"] == 1 and got["fallback_requests"] == 1


def test_other_reason_is_fallback(tmp_path):
    env, since = _setup(tmp_path, after=[(A8, DOWN)])
    got = strata_spawn.verify(AGENT, since, env)
    assert got["served"] == "fallback" and got["fallback_requests"] == 1


def test_other_reason_mixed_with_busy_is_fallback(tmp_path):
    env, since = _setup(tmp_path, after=[(A8, BUSY_HELD), (A8, DOWN)])
    got = strata_spawn.verify(AGENT, since, env)
    assert got["served"] == "fallback"
    assert got["fallback_requests"] == 2
    assert "880ace71" in got["fallback_reasons"]


def test_before_mark_and_other_agents_ignored(tmp_path):
    env, since = _setup(tmp_path, before=[(A8, DOWN)],
                        after=[("ffffffff", DOWN), (A8, LOCAL)])
    got = strata_spawn.verify(AGENT, since, env)
    assert got == {"served": "strata", "local_requests": 1, "fallback_requests": 0,
                   "fallback_reasons": []}
