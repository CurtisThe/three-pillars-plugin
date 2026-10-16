"""test_tier_ladder_start_model.py — `start`'s printed model follows the
FLOORED tier, not the plan tier, for a local model that is not haiku.

design: hybrid-routing-hardening (detailed-design.md §Effective-tier seam:
`start` prints `{tier, model, ...}` with `model = effective_model(tier, ...)`
for the effective, floored `tier`)

With `local_implement.model == "haiku"` the haiku refusal hides a regression
that computes the model from the plan tier: both paths print `sonnet`. A
non-haiku local model (`qwen3-coder`) separates them — an unrouted `local`
start must print the Claude fallback for the sonnet rung, never the local
model. Every subprocess pops `ANTHROPIC_BASE_URL`, so the ambient router is
never consulted.

The unrouted test is parametrized with explicit ids so each case is its OWN
node and its own guard claim: `[explicit-unrouted]` (an `--route` unrouted
line) and `[missing-route]` (no route at all). Each case builds its config and
record under its own `tmp_path` — no shared state couples them, so either can
go red alone (e.g. a model computed from the plan tier only for one label).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = str(Path(__file__).resolve().parent / "tier_ladder.py")
LOCAL_MODEL = "qwen3-coder"

ROUTED = {"schema": "tp-local-route/v1", "state": "routed", "reason": "ok",
          "base_url": "http://127.0.0.1:3457", "checked_at": "2026-09-27T00:00:00Z"}
UNROUTED = {"schema": "tp-local-route/v1", "state": "unrouted", "reason": "no-base-url",
            "base_url": None, "checked_at": "2026-09-27T00:00:00Z"}


def _cfg_root(tmp_path: Path) -> Path:
    root = tmp_path / "cfg"
    (root / ".three-pillars").mkdir(parents=True)
    (root / ".three-pillars" / "config.json").write_text(
        json.dumps({"local_implement": {"enabled": True, "model": LOCAL_MODEL}}),
        encoding="utf-8")
    return root


def _start(tmp_path: Path, *route_args: str) -> dict:
    env = dict(os.environ)
    env.pop("ANTHROPIC_BASE_URL", None)
    proc = subprocess.run(
        [sys.executable, SCRIPT, "start", "--task", "1.1", "--tier", "local",
         "--record", str(tmp_path / "R.json"), *route_args, "--root", str(_cfg_root(tmp_path))],
        capture_output=True, text=True, timeout=60, env=env)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


@pytest.mark.parametrize("route_args, reason", [
    (("--route", json.dumps(UNROUTED)), "unrouted/no-base-url"),
    ((), "missing-route"),
], ids=["explicit-unrouted", "missing-route"])
def test_unrouted_local_start_prints_the_sonnet_fallback_not_the_local_model(
        tmp_path, route_args, reason):
    out = _start(tmp_path, *route_args)
    assert out["tier"] == "sonnet"
    assert out["model"] == "sonnet"
    assert out["model"] != LOCAL_MODEL
    assert out["reason"] == reason and out["plan_tier"] == "local"


def test_routed_local_start_keeps_the_local_model(tmp_path):
    out = _start(tmp_path, "--route", json.dumps(ROUTED))
    assert out["tier"] == "local" and out["model"] == LOCAL_MODEL
