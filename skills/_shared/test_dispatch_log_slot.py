"""test_dispatch_log_slot.py — the cheap-tier slot fields on dispatch_log.record.

design: cheap-tier-offload (Task 2.4, Behavior 8)

`slot`, `oracle` (the verdict string), `escalated` (a bool) and `ab_pair` are
added to a record only when not None, the same rule as `served`, so a legacy
call (and a legacy CLI row) stays byte-identical. `--rung` still sets `rung`.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_SHARED = Path(__file__).resolve().parent
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

import dispatch_log  # noqa: E402

CLI = _SHARED / "dispatch_log.py"
SLOT_KEYS = {"slot", "oracle", "escalated", "ab_pair"}
LEGACY_KW = dict(role="task", agent=None, reason="attempt 1", outcome="green",
                 started_at="2026-01-01T00:00:00Z", ended_at="2026-01-01T00:00:05Z",
                 tokens=123)
# Pinned before the slot fields landed: the legacy row must never change.
LEGACY_ROW = (
    '{"agent": null, "effort": "inline (dispatcher effort)", '
    '"ended_at": "2026-01-01T00:00:05Z", "model": "opus", "outcome": "green", '
    '"phase": null, "reason": "attempt 1", "role": "task", "route": "-", "rung": null, '
    '"served_by": "opus", "started_at": "2026-01-01T00:00:00Z", "tokens": 123, '
    '"tokens_reason": null, "wall_s": 5.0}'
)


def test_legacy_call_is_byte_identical():
    rec = dispatch_log.record("unused", **LEGACY_KW)
    assert json.dumps(rec, sort_keys=True) == LEGACY_ROW
    assert rec == json.loads(LEGACY_ROW)


def test_all_none_slot_kwargs_add_nothing():
    rec = dispatch_log.record("unused", slot=None, oracle=None, escalated=None,
                              ab_pair=None, **LEGACY_KW)
    assert json.dumps(rec, sort_keys=True) == LEGACY_ROW


@pytest.mark.parametrize("key, value", [("slot", "handoff"), ("oracle", "prose_shape: ok"),
                                        ("escalated", False), ("escalated", True),
                                        ("ab_pair", "handoff-7")])
def test_each_key_appears_only_when_set(key, value):
    rec = dispatch_log.record("unused", **LEGACY_KW, **{key: value})
    assert rec[key] == value
    assert SLOT_KEYS & set(rec) == {key}
    rest = {k: v for k, v in rec.items() if k != key}
    assert rest == json.loads(LEGACY_ROW)


def test_all_slot_keys_together_with_rung():
    rec = dispatch_log.record("unused", slot="classifier_judge", oracle="accept",
                              escalated=False, ab_pair="p1", rung="sonnet-medium",
                              **LEGACY_KW)
    assert (rec["slot"], rec["oracle"], rec["escalated"], rec["ab_pair"], rec["rung"]) == (
        "classifier_judge", "accept", False, "p1", "sonnet-medium")


LOCAL = {"local_implement": {"model": "qwen-local", "fallback_model": "sonnet"}}


@pytest.mark.parametrize("agent", ["tp-drafter", "tp-drafter-xhigh", "tp-runbook"])
@pytest.mark.parametrize("rung, model", [("sonnet-xhigh", "sonnet"), ("sonnet-medium", "sonnet"),
                                         ("opus-medium", "opus"), ("opus-xhigh", "opus"),
                                         ("local-medium", "qwen-local")])
def test_a_given_rung_sets_the_model(agent, rung, model):
    # tp-drafter's AGENTS row is `rung:local`; the arm that ran is the rung (impl-audit #12)
    rec = dispatch_log.record("unused", **{**LEGACY_KW, "agent": agent}, rung=rung,
                              config=LOCAL, slot="handoff")
    assert (rec["model"], rec["rung"]) == (model, rung)


def test_no_rung_or_a_code_rung_keeps_the_agent_model():
    kw = {**LEGACY_KW, "agent": "tp-drafter"}
    assert dispatch_log.record("unused", **kw, config=LOCAL)["model"] == "qwen-local"
    assert dispatch_log.record("unused", **kw, config=LOCAL, rung="code")["model"] == "qwen-local"
    inline = dispatch_log.record("unused", **LEGACY_KW, rung="sonnet-xhigh")
    assert inline["model"] == "opus"  # --inline stays the pinned dispatcher


def _cli(tmp_path, *extra):
    base = ["record", "--design-dir", str(tmp_path), "--role", "handoff", "--inline",
            "--reason", "cheap attempt", "--outcome", "accept", "--root", str(tmp_path),
            "--started-at", "2026-01-01T00:00:00Z", "--ended-at", "2026-01-01T00:00:02Z"]
    proc = subprocess.run([sys.executable, str(CLI), *base, *extra],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    printed = json.loads(proc.stdout)
    rows = (tmp_path / dispatch_log.NDJSON_NAME).read_text(encoding="utf-8").splitlines()
    assert json.loads(rows[-1]) == printed
    return printed


@pytest.mark.parametrize("flag, expected", [("true", True), ("false", False)])
def test_cli_round_trips_the_slot_flags(tmp_path, flag, expected):
    rec = _cli(tmp_path, "--slot", "handoff", "--oracle", "pass",
               "--escalated", flag, "--ab-pair", "handoff-7", "--rung", "sonnet-medium")
    assert (rec["slot"], rec["oracle"], rec["escalated"], rec["ab_pair"]) == (
        "handoff", "pass", expected, "handoff-7")
    assert rec["rung"] == "sonnet-medium"  # the cheap-dispatch record step relies on it


def test_cli_without_slot_flags_writes_a_legacy_row(tmp_path):
    rec = _cli(tmp_path)
    assert SLOT_KEYS.isdisjoint(rec)


@pytest.mark.parametrize("oracle", ["ok", "accept", "prose_shape: ok", "PASS"])
def test_cli_refuses_a_slot_oracle_other_than_pass_or_fail(tmp_path, oracle):
    # cheap_ab rates only `pass`, so any other string would read as a silent fail
    proc = subprocess.run([sys.executable, str(CLI), "record", "--design-dir", str(tmp_path),
                           "--role", "r", "--inline", "--reason", "x", "--outcome", "y",
                           "--slot", "handoff", "--oracle", oracle],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 2 and "--oracle" in proc.stderr
    assert not (tmp_path / dispatch_log.NDJSON_NAME).exists()


def test_cli_accepts_fail_with_a_slot_and_any_oracle_without_one(tmp_path):
    assert _cli(tmp_path, "--slot", "handoff", "--oracle", "fail")["oracle"] == "fail"
    assert _cli(tmp_path, "--oracle", "prose_shape: ok")["oracle"] == "prose_shape: ok"


def test_cli_refuses_a_non_bool_escalated(tmp_path):
    proc = subprocess.run([sys.executable, str(CLI), "record", "--design-dir", str(tmp_path),
                           "--role", "r", "--inline", "--reason", "x", "--outcome", "y",
                           "--escalated", "maybe"], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 2 and "escalated" in proc.stderr


def test_drafter_arm_labels_merge_a_partial_local_block_over_the_defaults(tmp_path):
    # PR #191 review r1: this repo's own local_implement block has no model keys
    cfg = {"local_implement": {"enabled": True, "full_design": True}}
    rec = dispatch_log.record(tmp_path, role="handoff", agent="tp-drafter", reason="x",
                              outcome="accept", config=cfg, rung="sonnet-medium",
                              slot="handoff", oracle="pass")
    assert (rec["model"], rec["effort"]) == ("sonnet", "medium")
