"""Tests for strata_spawn.main (local-role-routing Task 2.4).

Fakes are injected through module attributes; no live router is touched and
every case without --busy passes --config <tmp fixture>.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_DIR = Path(__file__).resolve().parent
if str(_DIR) not in sys.path:
    sys.path.insert(0, str(_DIR))

import strata_spawn  # noqa: E402


class FakeLease:
    POLL_S = 1

    def __init__(self, state="free"):
        self.state = state
        self.released = []

    def acquire_timed(self, **kw):
        return self.state, "why", 0.0

    def release_agent(self, agent_id):
        self.released.append(agent_id)
        return True


class FakeTime:
    def __init__(self, now=1000.0):
        self.now = now

    def time(self):
        return self.now

    def sleep(self, s):
        pass


@pytest.fixture
def env(monkeypatch, tmp_path):
    lease = FakeLease()
    monkeypatch.setattr(strata_spawn, "local_lease", lease)
    monkeypatch.setattr(strata_spawn, "time", FakeTime())
    empty = tmp_path / "empty.json"
    empty.write_text("{}", encoding="utf-8")
    waitcfg = tmp_path / "wait.json"
    waitcfg.write_text(json.dumps({"strata_spawn": {"busy": "wait"}}), encoding="utf-8")
    return lease, str(empty), str(waitcfg)


def run(capsys, *argv):
    code = strata_spawn.main(list(argv))
    return code, capsys.readouterr().out


def test_wait_free_prints_started_at(env, capsys):
    _, empty, _ = env
    code, out = run(capsys, "wait", "--config", empty)
    assert code == 0
    assert json.loads(out)["started_at"] == 1000.0
    assert json.loads(out)["state"] == "free"


def test_wait_busy_default_is_busy_fallback(env, capsys):
    lease, empty, _ = env
    lease.state = "busy"
    code, out = run(capsys, "wait", "--config", empty)
    assert code == 0
    assert json.loads(out)["state"] == "busy-fallback"


def test_wait_busy_flag_wait_echoes_started_at(env, capsys):
    lease, _, _ = env
    lease.state = "busy"
    code, out = run(capsys, "wait", "--busy", "wait", "--started-at", "990")
    assert code == 3
    data = json.loads(out)
    assert data["state"] == "still-busy"
    assert data["started_at"] == 990.0


def test_config_wait_policy_makes_bare_wait_busy(env, capsys):
    lease, _, waitcfg = env
    lease.state = "busy"
    code, out = run(capsys, "wait", "--config", waitcfg)
    assert code == 3
    assert json.loads(out)["state"] == "still-busy"


def test_wait_unhealthy_exits_4(env, capsys):
    lease, empty, _ = env
    lease.state = "unhealthy"
    code, _ = run(capsys, "wait", "--config", empty)
    assert code == 4


def test_wait_past_ceiling_exits_5(env, capsys):
    lease, _, _ = env
    lease.state = "busy"
    code, out = run(capsys, "wait", "--busy", "wait", "--ceiling-s", "1",
                    "--started-at", "900")
    assert code == 5
    assert json.loads(out)["state"] == "wait-exhausted"


@pytest.mark.parametrize("served", ["fallback", "fallback-busy"])
def test_verify_fallback_exits_3(monkeypatch, capsys, served):
    monkeypatch.setattr(strata_spawn, "verify",
                        lambda agent_id, since, env=None: {"served": served})
    code, out = run(capsys, "verify", "a1", "0")
    assert code == 3
    assert json.loads(out)["served"] == served


def test_verify_strata_exits_0(monkeypatch, capsys):
    monkeypatch.setattr(strata_spawn, "verify",
                        lambda agent_id, since, env=None: {"served": "strata"})
    code, _ = run(capsys, "verify", "a1", "0")
    assert code == 0


def test_mark_prints_json_offset(monkeypatch, capsys):
    monkeypatch.setattr(strata_spawn, "mark", lambda env=None: 42)
    code, out = run(capsys, "mark")
    assert code == 0
    assert json.loads(out) == 42


def test_decide_accepts_fallback_busy_by_default(env, capsys):
    _, empty, _ = env
    code, out = run(capsys, "decide", "0", "fallback-busy", "review_finder",
                    "--config", empty)
    assert code == 0
    assert out.strip() == "accept"


def test_decide_wait_policy_respawns(env, capsys):
    code, out = run(capsys, "decide", "0", "fallback-busy", "review_finder",
                    "--busy", "wait")
    assert code == 0
    assert out.strip() == "respawn"


def test_decide_exhausted_council_goes_sonnet(env, capsys):
    _, empty, _ = env
    code, out = run(capsys, "decide", "2", "fallback", "council_member",
                    "--config", empty)
    assert code == 0
    assert out.strip() == "sonnet"


def test_release_exits_0(env, capsys):
    lease, _, _ = env
    code, out = run(capsys, "release", "a1")
    assert code == 0
    assert lease.released == ["a1"]
    assert json.loads(out) == {"agent_id": "a1", "outcome": True}


def _busy_line(agent, reason):
    return (f"[2026-10-08T10:00:00] POST /v1/messages  model=claude-haiku  sess=11111111  "
            f"agent={agent}  -> FALLBACK upstream ({reason})\n")


def test_verify_dedupes_fallback_reasons_first_seen(tmp_path):
    agent = "cafef00dfeedface"
    a8 = agent[:8]
    holder_x = "aaaa1111"
    holder_y = "bbbb2222"
    log = tmp_path / "router.log"
    lines = [
        _busy_line(a8, f"slot held by {holder_x}"),
        _busy_line(a8, f"slot held by {holder_x}"),
        _busy_line(a8, f"agent-busy {holder_y}"),
        _busy_line(a8, f"slot held by {holder_x}"),
    ]
    log.write_text("".join(lines), encoding="utf-8")
    got = strata_spawn.verify(agent, 0, {"TP_LOCAL_LOG": str(log)})
    assert got["fallback_reasons"] == [holder_x, holder_y]
    assert got["fallback_requests"] == 4
    assert got["served"] == "fallback-busy"


def test_release_prints_real_release_agent_outcome(monkeypatch, capsys):
    class NotHolderLease:
        def release_agent(self, agent_id):
            return {"outcome": "not-holder", "endpoints": []}

    monkeypatch.setattr(strata_spawn, "local_lease", NotHolderLease())
    code, out = run(capsys, "release", "a1")
    assert code == 0
    data = json.loads(out)
    assert data["outcome"] == "not-holder"
    assert "not-holder" in out
