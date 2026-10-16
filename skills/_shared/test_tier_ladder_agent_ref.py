"""test_tier_ladder_agent_ref.py — `start`/`next` print the spawn reference.

design: run-throughput (seat ruling: PR #178 merge held — agent-name resolver fix, (a'))

Against a fixture framework root whose plugin.json names ``three-pillars-pro``: the
spawn field ``agent_ref`` carries ``three-pillars-pro:<variant>`` while ``agent`` and the
ladder record keep the bare name (the telemetry key). An unresolvable reference exits 2
with an ``agent-unresolved:`` line after the record is written, so the dispatcher can
halt it with ``next --outcome env-error``.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from test_agent_ref import fixture_root

SCRIPT = str(Path(__file__).resolve().parent / "tier_ladder.py")
ROUTED = {"schema": "tp-local-route/v1", "state": "routed", "reason": "ok",
          "base_url": "http://127.0.0.1:3457", "checked_at": "2026-09-27T00:00:00Z"}
VARIANTS = tuple(f"tp-task-worker-{f}-{e}" for f in ("local", "sonnet", "opus")
                 for e in ("medium", "xhigh"))


def cli(*args: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_BASE_URL"}
    return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True,
                          timeout=60, env=env)


def _start(tmp_path: Path, plugin_root: Path, tier="local") -> tuple[subprocess.CompletedProcess, Path]:
    rec = tmp_path / "R.json"
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    res = cli("start", "--task", "1.1", "--tier", tier, "--record", str(rec), "--route",
              json.dumps(ROUTED), "--root", str(repo), "--plugin-root", str(plugin_root))
    return res, rec


def test_start_prints_pro_reference_and_keeps_bare_name(tmp_path):
    res, rec = _start(tmp_path, fixture_root(tmp_path, agents=VARIANTS))
    assert res.returncode == 0, res.stderr
    out = json.loads(res.stdout)
    assert out["agent_ref"] == "three-pillars-pro:tp-task-worker-local-medium"
    assert out["agent"] == "tp-task-worker-local-medium"
    assert "three-pillars-pro" not in rec.read_text(encoding="utf-8")  # telemetry stays bare


def test_next_prints_the_escalated_reference(tmp_path):
    root = fixture_root(tmp_path, agents=VARIANTS)
    res, rec = _start(tmp_path, root)
    assert res.returncode == 0, res.stderr
    res = cli("next", "--record", str(rec), "--outcome", "unavailable", "--root",
              str(tmp_path / "repo"), "--plugin-root", str(root))
    assert res.returncode == 0, res.stderr
    out = json.loads(res.stdout)
    assert (out["action"], out["agent"]) == ("escalate", "tp-task-worker-sonnet-medium")
    assert out["agent_ref"] == "three-pillars-pro:tp-task-worker-sonnet-medium"


def test_every_rung_prints_a_spawnable_reference(tmp_path):
    """Q4: opus-* rungs spawn their own variants too; none is inline any more."""
    root = fixture_root(tmp_path, agents=VARIANTS)
    for rung in (v[len("tp-task-worker-"):] for v in VARIANTS):
        res, _ = _start(tmp_path, root, tier=rung)
        assert res.returncode == 0, res.stderr
        out = json.loads(res.stdout)
        assert out["agent_ref"] == f"three-pillars-pro:tp-task-worker-{rung}", out
        assert out["model"] is not None


def test_opus_medium_to_xhigh_changes_the_agent(tmp_path):
    root = fixture_root(tmp_path, agents=VARIANTS)
    res, rec = _start(tmp_path, root, tier="opus-medium")
    res = cli("next", "--record", str(rec), "--outcome", "FAIL", "--reason", "assert 1 == 2",
              "--root", str(tmp_path / "repo"), "--plugin-root", str(root))
    out = json.loads(res.stdout)
    assert (out["action"], out["rung"], out["model"]) == ("escalate", "opus-xhigh", "opus")
    assert out["agent_ref"] == "three-pillars-pro:tp-task-worker-opus-xhigh"


def test_unresolvable_reference_exits_2_after_writing_the_record(tmp_path):
    root = fixture_root(tmp_path, agents=("tp-task-worker-sonnet-medium",))
    res, rec = _start(tmp_path, root)
    assert res.returncode == 2 and res.stdout == ""
    assert "agent-unresolved: tp-task-worker-local-medium" in res.stderr
    assert json.loads(rec.read_text(encoding="utf-8"))["tier_path"] == ["local-medium"]


# --- (c) a rejected spawn is a loud halt, never `unavailable` ------------------------

import pytest  # noqa: E402

import tier_ladder  # noqa: E402

CFG = {"escalate": True, "max_retries": 2, "model": "haiku", "fallback_model": "sonnet"}
REASON = "agent-unresolved: three-pillars:tp-task-worker-local-medium"


@pytest.mark.parametrize("outcome", ["env-error", "unavailable", "FAIL"])
def test_agent_unresolved_halts_without_advancing(outcome):
    rec = tier_ladder.start("1.1", "local-medium")
    action, rung, after = tier_ladder.next_step(rec, outcome, CFG, reason=REASON)
    assert (action, rung, after["final"]) == ("halt", None, "env-error")
    assert after["tier_path"] == ["local-medium"]
    assert after["attempts"] == {"local-medium": 0}
    assert after["verdicts"][-1]["outcome"] == "env-error"


def test_plain_unavailable_still_walks_to_sonnet():
    rec = tier_ladder.start("1.1", "local-medium")
    action, rung, after = tier_ladder.next_step(rec, "unavailable", CFG, reason="backend down")
    assert (action, rung, after["final"]) == ("escalate", "sonnet-medium", None)


def test_opus_rung_unresolved_is_a_halt():
    rec = tier_ladder.start("1.1", "opus-xhigh")
    action, _, after = tier_ladder.next_step(rec, "unavailable", CFG, reason=REASON)
    assert (action, after["final"]) == ("halt", "env-error")


def test_cli_unresolved_start_then_env_error_next_halts(tmp_path):
    root = fixture_root(tmp_path, agents=("tp-task-worker-sonnet-medium",))
    res, rec = _start(tmp_path, root)
    assert res.returncode == 2
    reason = res.stderr.strip().split("tier_ladder: ", 1)[1]
    res = cli("next", "--record", str(rec), "--outcome", "env-error", "--reason", reason,
              "--root", str(tmp_path / "repo"), "--plugin-root", str(root))
    assert res.returncode == 0, res.stderr
    assert json.loads(res.stdout)["action"] == "halt"
    assert json.loads(rec.read_text(encoding="utf-8"))["final"] == "env-error"
