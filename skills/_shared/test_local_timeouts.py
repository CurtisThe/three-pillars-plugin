"""Tests for local_timeouts.py: wanted / settled / plan (tmp_path only)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import attempt_watchdog  # noqa: E402
import local_timeouts as lt  # noqa: E402

STR_VALUES = {k: str(v) for k, v in lt.TIMEOUTS.items()}


def _write(root, data):
    p = root / ".claude" / "settings.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(data if isinstance(data, str) else json.dumps(data))
    return p


def _rec(r):
    return {"local_implement": {"enabled": True, "client_timeouts": r}}


def test_timeouts_values():
    assert lt.TIMEOUTS == {
        "CLAUDE_BYTE_STREAM_IDLE_TIMEOUT_MS": 1_800_000,
        "CLAUDE_STREAM_IDLE_TIMEOUT_MS": 1_800_000,
        "API_TIMEOUT_MS": 1_800_000,
        "CLAUDE_ASYNC_AGENT_STALL_TIMEOUT_MS": 1_500_000,
    }
    assert lt.MIN_CLAUDE_VERSION == (2, 1, 242)
    assert lt.CONFIG_KEY == "local_implement.client_timeouts"
    assert lt.SETTINGS_REL == Path(".claude") / "settings.json"


def test_ordering_invariant():
    stall = lt.TIMEOUTS["CLAUDE_ASYNC_AGENT_STALL_TIMEOUT_MS"]
    assert stall > attempt_watchdog.DEFAULT_WALL_S * 1000
    for k in ("CLAUDE_BYTE_STREAM_IDLE_TIMEOUT_MS", "CLAUDE_STREAM_IDLE_TIMEOUT_MS", "API_TIMEOUT_MS"):
        assert lt.TIMEOUTS[k] >= stall


def test_wanted():
    assert lt.wanted({"local_implement": {"enabled": True}})
    assert lt.wanted({"models": {"implement": "local-qwen"}})
    assert not lt.wanted({})
    assert not lt.wanted({"local_implement": {"enabled": False}, "models": {"a": "opus"}})


def test_settled_not_wanted_and_record(tmp_path):
    assert lt.settled({}, tmp_path)
    assert not lt.settled({"local_implement": {"enabled": True}}, tmp_path)
    assert lt.settled(_rec({"applied_at": "2026-01-01"}), tmp_path)
    assert lt.settled(_rec({"declined": True}), tmp_path)
    assert not lt.settled(_rec({"applied_at": None, "declined": False}), tmp_path)


def test_settled_by_settings_file(tmp_path):
    cfg = {"local_implement": {"enabled": True}}
    _write(tmp_path, {"env": STR_VALUES})
    assert lt.settled(cfg, tmp_path)
    partial = dict(STR_VALUES)
    del partial["API_TIMEOUT_MS"]
    _write(tmp_path, {"env": partial})
    assert not lt.settled(cfg, tmp_path)


def test_plan_absent(tmp_path):
    p = lt.plan(tmp_path)
    assert p["creates_file"] is True
    assert p["add"] == STR_VALUES
    assert p["keep"] == {} and p["same"] == []
    assert p["path"] == str(tmp_path / ".claude" / "settings.json")
    assert '"env"' in p["diff"] and "+" in p["diff"]
    assert not (tmp_path / ".claude" / "settings.json").exists()


def test_plan_keep_same_and_untouched(tmp_path):
    path = _write(tmp_path, {"model": "x", "env": {"API_TIMEOUT_MS": "5",
                                                  "CLAUDE_STREAM_IDLE_TIMEOUT_MS": "1800000",
                                                  "OTHER": "1"}})
    before = path.read_text(encoding="utf-8")
    p = lt.plan(tmp_path)
    assert p["creates_file"] is False
    assert p["keep"] == {"API_TIMEOUT_MS": "5"}
    assert p["same"] == ["CLAUDE_STREAM_IDLE_TIMEOUT_MS"]
    assert set(p["add"]) == {"CLAUDE_BYTE_STREAM_IDLE_TIMEOUT_MS", "CLAUDE_ASYNC_AGENT_STALL_TIMEOUT_MS"}
    assert "OTHER" in p["diff"] and '"model"' in p["diff"]
    assert path.read_text(encoding="utf-8") == before


def test_plan_no_env_key(tmp_path):
    _write(tmp_path, {"model": "x"})
    p = lt.plan(tmp_path)
    assert p["add"] == STR_VALUES and p["creates_file"] is False


@pytest.mark.parametrize("data", ["[]", '{"env": []}', '"s"'])
def test_plan_bad_shape(tmp_path, data):
    _write(tmp_path, data)
    with pytest.raises(ValueError):
        lt.plan(tmp_path)
