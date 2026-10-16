"""test_tier_ladder_route_cli.py — start's stdout contract, route flags, record.

design: hybrid-routing-hardening (detailed-design.md §Effective-tier seam)

``start --task ID --tier T --record R [--route JSON | --route-from PATH]
[--root .]`` prints one JSON line ``{tier, rung, agent, model, reason, plan_tier,
display}``
— the only source of a first attempt's effective rung and model — and writes
a record carrying ``route`` (and ``floored_from`` when floored). Every
subprocess here passes an explicit env (``ANTHROPIC_BASE_URL`` popped, or
bound to a chosen value) so results never depend on this session's own
ambient base URL.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import local_route_check
import local_route_log
import tier_ladder
from agent_ref import resolve as _ref  # the spawn reference (this install's plugin name)

SCRIPT = str(Path(__file__).resolve().parent / "tier_ladder.py")

ROUTED = {"schema": "tp-local-route/v1", "state": "routed", "reason": "ok",
          "base_url": "http://127.0.0.1:3457", "checked_at": "2026-09-27T00:00:00Z"}
UNROUTED = {"schema": "tp-local-route/v1", "state": "unrouted", "reason": "no-base-url",
            "base_url": None, "checked_at": "2026-09-27T00:00:00Z"}


def cli(*args: str, env: dict | None = None) -> tuple[int, str]:
    if env is None:
        env = dict(os.environ)
        env.pop("ANTHROPIC_BASE_URL", None)
    proc = subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True,
                          timeout=60, env=env)
    return proc.returncode, proc.stdout


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _bare(tmp_path: Path, name: str = "bare") -> Path:
    root = tmp_path / name
    root.mkdir()
    return root


def test_start_stdout_has_exactly_eight_keys(tmp_path):
    rec = tmp_path / "R.json"
    bare = _bare(tmp_path)
    rc, out = cli("start", "--task", "1.1", "--tier", "local", "--record", str(rec),
                  "--route", json.dumps(ROUTED), "--root", str(bare))
    assert rc == 0
    assert set(json.loads(out)) == {"tier", "rung", "agent", "agent_ref", "model", "reason",
                                    "plan_tier", "display"}


def test_routeless_start_is_missing_route_and_floored(tmp_path):
    rec = tmp_path / "R.json"
    bare = _bare(tmp_path)
    rc, out = cli("start", "--task", "1.1", "--tier", "local", "--record", str(rec),
                  "--root", str(bare))
    assert rc == 0
    assert json.loads(out) == {
        "tier": "sonnet", "rung": "sonnet-medium", "agent": "tp-task-worker-sonnet-medium", "agent_ref": _ref("tp-task-worker-sonnet-medium"),
        "model": "sonnet", "reason": "missing-route",
        "plan_tier": "local", "display": "local->sonnet: missing-route",
    }
    record = _load(rec)
    assert record["route"] == "missing-route"
    assert record["floored_from"] == "local-medium"
    assert record["tier_path"] == ["sonnet-medium"]


def test_routed_route_stays_local_and_uses_haiku_default(tmp_path):
    rec = tmp_path / "R.json"
    bare = _bare(tmp_path)
    rc, out = cli("start", "--task", "1.1", "--tier", "local", "--record", str(rec),
                  "--route", json.dumps(ROUTED), "--root", str(bare))
    assert rc == 0
    result = json.loads(out)
    assert result["tier"] == "local" and result["model"] == "haiku"
    assert "floored_from" not in _load(rec)


def test_unrouted_route_display_names_the_floor(tmp_path):
    rec = tmp_path / "R.json"
    bare = _bare(tmp_path)
    rc, out = cli("start", "--task", "1.1", "--tier", "local", "--record", str(rec),
                  "--route", json.dumps(UNROUTED), "--root", str(bare))
    assert rc == 0
    assert json.loads(out)["display"] == "local->sonnet: unrouted/no-base-url"


def test_route_and_route_from_together_is_usage_error(tmp_path):
    rec = tmp_path / "R.json"
    bare = _bare(tmp_path)
    decisions = tmp_path / "decisions.md"
    decisions.write_text("nothing routing-shaped here\n", encoding="utf-8")
    rc, _out = cli("start", "--task", "1.1", "--tier", "local", "--record", str(rec),
                   "--route", json.dumps(ROUTED), "--route-from", str(decisions),
                   "--root", str(bare))
    assert rc == 2
    assert not rec.exists()


def test_invalid_route_is_malformed_and_floored(tmp_path):
    rec = tmp_path / "R.json"
    bare = _bare(tmp_path)
    rc, out = cli("start", "--task", "1.1", "--tier", "local", "--record", str(rec),
                  "--route", json.dumps({"not": "a route"}), "--root", str(bare))
    assert rc == 0
    result = json.loads(out)
    assert result["reason"] == "malformed-route"
    assert result["tier"] == "sonnet"
    assert _load(rec)["floored_from"] == "local-medium"


def _decisions_with_routed_entry(tmp_path: Path) -> Path:
    base_url = local_route_check.redact_url("http://127.0.0.1:3457")
    result = {**ROUTED, "base_url": base_url, "ollama": None, "detail": ""}
    entry = local_route_log.render_entry(result, "run-start", "none")
    path = tmp_path / "decisions.md"
    path.write_text("# Decisions log — schema v1\n\n" + entry + "\n", encoding="utf-8")
    return path


def test_route_from_stale_when_env_unset(tmp_path):
    rec = tmp_path / "R.json"
    bare = _bare(tmp_path)
    decisions = _decisions_with_routed_entry(tmp_path)
    rc, out = cli("start", "--task", "1.1", "--tier", "local", "--record", str(rec),
                  "--route-from", str(decisions), "--root", str(bare))
    assert rc == 0
    assert json.loads(out)["reason"] == "stale-route"


def test_route_from_routed_ok_when_env_matches(tmp_path):
    rec = tmp_path / "R.json"
    bare = _bare(tmp_path)
    decisions = _decisions_with_routed_entry(tmp_path)
    env = dict(os.environ)
    env["ANTHROPIC_BASE_URL"] = "http://127.0.0.1:3457"
    rc, out = cli("start", "--task", "1.1", "--tier", "local", "--record", str(rec),
                  "--route-from", str(decisions), "--root", str(bare), env=env)
    assert rc == 0
    assert json.loads(out)["reason"] == "routed/ok"


def test_route_from_missing_path_is_missing_route(tmp_path):
    rec = tmp_path / "R.json"
    bare = _bare(tmp_path)
    missing = tmp_path / "does-not-exist.md"
    rc, out = cli("start", "--task", "1.1", "--tier", "local", "--record", str(rec),
                  "--route-from", str(missing), "--root", str(bare))
    assert rc == 0
    assert json.loads(out)["reason"] == "missing-route"


def test_sonnet_tier_never_floors_under_unrouted(tmp_path):
    rec = tmp_path / "R.json"
    bare = _bare(tmp_path)
    rc, out = cli("start", "--task", "1.1", "--tier", "sonnet", "--record", str(rec),
                  "--route", json.dumps(UNROUTED), "--root", str(bare))
    assert rc == 0
    result = json.loads(out)
    assert result["tier"] == "sonnet" and result["display"] == "sonnet"
    assert "floored_from" not in _load(rec)


def test_haiku_fallback_model_refused_to_sonnet_when_floored(tmp_path):
    rec = tmp_path / "R.json"
    cfg_root = tmp_path / "cfg"
    (cfg_root / ".three-pillars").mkdir(parents=True)
    block = {"fallback_model": "haiku"}
    (cfg_root / ".three-pillars" / "config.json").write_text(
        json.dumps({"local_implement": block}), encoding="utf-8")
    rc, out = cli("start", "--task", "1.1", "--tier", "local", "--record", str(rec),
                  "--route", json.dumps(UNROUTED), "--root", str(cfg_root))
    assert rc == 0
    result = json.loads(out)
    assert result["tier"] == "sonnet" and result["model"] == "sonnet"


_HAIKU_CFG = {"local_implement": {"enabled": True, "model": "haiku",
                                  "fallback_model": "haiku", "max_retries": 0}}


def _haiku_cfg_root(tmp_path: Path) -> Path:
    cfg_root = tmp_path / "cfg"
    (cfg_root / ".three-pillars").mkdir(parents=True)
    (cfg_root / ".three-pillars" / "config.json").write_text(
        json.dumps(_HAIKU_CFG), encoding="utf-8")
    return cfg_root


def test_next_uses_record_route(tmp_path):
    unrouted_rec = tmp_path / "unrouted.json"
    unrouted_rec.write_text(json.dumps(
        {**tier_ladder.start("1.1", "local"), "route": "unrouted/no-base-url"}),
        encoding="utf-8")
    cfg_root = _haiku_cfg_root(tmp_path)
    rc, out = cli("next", "--record", str(unrouted_rec), "--outcome", "FAIL",
                  "--root", str(cfg_root))
    assert rc == 0
    result = json.loads(out)
    assert result == {"action": "escalate", "tier": "sonnet", "rung": "sonnet-xhigh",
                      "agent": "tp-task-worker-sonnet-xhigh", "agent_ref": _ref("tp-task-worker-sonnet-xhigh"), "model": "sonnet"}
    assert "haiku" not in str(result["model"]).lower()

    routed_rec = tmp_path / "routed.json"
    routed_rec.write_text(json.dumps(
        {**tier_ladder.start("1.1", "local"), "route": "routed/ok"}), encoding="utf-8")
    rc, out = cli("next", "--record", str(routed_rec), "--outcome", "FAIL",
                  "--root", str(cfg_root))
    assert rc == 0
    result = json.loads(out)
    assert result == {"action": "escalate", "tier": "local", "rung": "local-xhigh",
                      "agent": "tp-task-worker-local-xhigh", "agent_ref": _ref("tp-task-worker-local-xhigh"), "model": "haiku"}


def test_next_old_record_never_haiku(tmp_path):
    rec = tmp_path / "R.json"
    rec.write_text(json.dumps(tier_ladder.start("1.1", "local")), encoding="utf-8")
    cfg_root = _haiku_cfg_root(tmp_path)
    rc, out = cli("next", "--record", str(rec), "--outcome", "FAIL", "--root", str(cfg_root))
    assert rc == 0
    result = json.loads(out)
    assert result == {"action": "escalate", "tier": "sonnet", "rung": "sonnet-xhigh",
                      "agent": "tp-task-worker-sonnet-xhigh", "agent_ref": _ref("tp-task-worker-sonnet-xhigh"), "model": "sonnet"}
    assert "haiku" not in str(result["model"]).lower()


def test_decision_entry_route_floor_line(tmp_path):
    floored = {**tier_ladder.start("1.1", "sonnet"), "route": "unrouted/no-base-url",
               "floored_from": "local"}
    entry = tier_ladder.to_decision_entry(floored)
    match = re.search(local_route_log.FLOOR_RE, entry, re.M)
    assert match is not None
    assert match.group(1) == "unrouted/no-base-url"

    unfloored = {**tier_ladder.start("1.1", "local"), "route": "routed/ok"}
    assert "**Route floor**" not in tier_ladder.to_decision_entry(unfloored)

    rec = tmp_path / "R.json"
    rec.write_text(json.dumps(floored), encoding="utf-8")
    rc, out = cli("entry", "--record", str(rec))
    assert rc == 0
    assert re.search(local_route_log.FLOOR_RE, out, re.M)


def test_start_takes_rungs_and_floors_before_write(tmp_path):
    """Rung-aware start: `local-xhigh` unrouted is written `sonnet-xhigh`; a legacy
    `sonnet` starts at `sonnet-xhigh`; the floor line stays family-level (FLOOR_RE)."""
    bare = _bare(tmp_path)
    rec = tmp_path / "x.json"
    rc, out = cli("start", "--task", "1.1", "--tier", "local-xhigh", "--record", str(rec),
                  "--route", json.dumps(UNROUTED), "--root", str(bare))
    assert rc == 0 and _load(rec)["tier_path"] == ["sonnet-xhigh"]
    assert (json.loads(out)["rung"], json.loads(out)["plan_tier"]) == (
        "sonnet-xhigh", "local-xhigh")
    rec = tmp_path / "m.json"
    rc, _out = cli("start", "--task", "1.1", "--tier", "local-medium", "--record", str(rec),
                   "--route", json.dumps(UNROUTED), "--root", str(bare))
    rc, entry = cli("entry", "--record", str(rec))
    match = re.search(local_route_log.FLOOR_RE, entry, re.M)
    assert rc == 0 and match is not None and match.group(1) == "unrouted/no-base-url"
    rec = tmp_path / "s.json"
    rc, out = cli("start", "--task", "1.1", "--tier", "sonnet", "--record", str(rec),
                  "--route", json.dumps(ROUTED), "--root", str(bare))
    assert json.loads(out)["rung"] == "sonnet-xhigh"
    assert _load(rec)["tier_path"] == ["sonnet-xhigh"]
    rc, out = cli("start", "--task", "1.1", "--tier", "local-max", "--record", str(rec),
                  "--route", json.dumps(ROUTED), "--root", str(bare))
    assert rc == 2


def test_telemetry_copies_route():
    floored = {**tier_ladder.start("1.1", "sonnet"), "route": "unrouted/no-base-url",
               "floored_from": "local"}
    tel = tier_ladder.to_telemetry(floored)
    assert tel["route"] == "unrouted/no-base-url"
    assert tel["floored_from"] == "local"
    assert re.search(local_route_log.FLOOR_RE, tier_ladder.to_decision_entry(tel), re.M)

    env = dict(os.environ)
    env.pop("ANTHROPIC_BASE_URL", None)
    proc = subprocess.run([sys.executable, SCRIPT, "entry", "--record", "-"],
                          input=json.dumps(tel), capture_output=True, text=True,
                          timeout=60, env=env)
    assert proc.returncode == 0, proc.stderr
    assert re.search(local_route_log.FLOOR_RE, proc.stdout, re.M)
