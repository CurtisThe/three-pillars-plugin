"""Tests for attempt_watchdog.py delegating orphan logic (run-throughput 1.5).

`attempt_watchdog` re-exports `orphans` / `orphan_finished` from `attempt_orphans`
by identity; `mark_orphan` stamps `orphaned_at` beside `orphan: true`; and the CLI
`orphans` subcommand passes `--settle-s` / `--router-log` / `--config-dir` through.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import attempt_orphans as ao  # noqa: E402
import attempt_watchdog as aw  # noqa: E402

AGENT = "a0000001-rest-of-id"


def _state(tmp_path, started_at):
    path = tmp_path / "ladder" / "1.5.watch.json"
    state = aw.arm(path, attempt_id="t15", agent_id=AGENT, rung="local-medium",
                   phase="1", router_log=None, now=started_at)
    return json.loads(json.dumps(state)), path


def _cli(monkeypatch, argv):
    import io
    buf = io.StringIO()
    real = sys.stdout
    sys.stdout = buf
    try:
        rc = aw.main(argv)
    finally:
        sys.stdout = real
    assert rc == 0, "the CLI must exit 0"
    return json.loads(buf.getvalue())


# --- identity: the watchdog delegates the orphan logic --------------------------

def test_orphans_identity_is_the_attempt_orphans_module():
    assert aw.orphans is ao.orphans


def test_orphan_finished_identity_is_the_attempt_orphans_module():
    assert aw.orphan_finished is ao.orphan_finished


# --- mark_orphan: orphaned_at beside orphan -------------------------------------

def test_mark_orphan_stamps_orphaned_at_with_injected_clock(tmp_path, monkeypatch):
    monkeypatch.setattr(aw, "_clock", lambda: 123.0)
    _unused, path = _state(tmp_path, 100.0)
    out = aw.mark_orphan(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["orphan"] is True
    assert data["orphaned_at"] == 123.0
    # every other key stays untouched
    assert data["attempt_id"] == "t15"
    assert data["agent_id"] == AGENT
    assert data["agent8"] == "a0000001"
    assert data["rung"] == "local-medium"
    assert data["phase"] == "1"
    assert data["started_at"] == 100.0
    assert data["log_offset"] == 0
    assert out["orphan"] is True and out["orphaned_at"] == 123.0


def test_mark_orphan_prefers_the_now_argument(tmp_path, monkeypatch):
    monkeypatch.setattr(aw, "_clock", lambda: 999.0)
    _unused, path = _state(tmp_path, 100.0)
    out = aw.mark_orphan(path, now=7.5)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["orphaned_at"] == 7.5
    assert data["orphan"] is True
    assert out["orphaned_at"] == 7.5


# --- CLI: orphans passes settle-s / router-log / config-dir through -------------

def test_cli_orphans_passes_each_flag_through(monkeypatch, tmp_path):
    calls = []

    def recorder(ladder_dir, **kw):
        calls.append((str(ladder_dir), dict(kw)))
        return {"holds_gpu": False, "orphans": []}

    monkeypatch.setattr(aw, "orphans", recorder)
    ladder = tmp_path / "ladder"
    out = _cli(monkeypatch, ["orphans", "--dir", str(ladder), "--phase", "3",
                             "--settle-s", "90", "--router-log", "P",
                             "--config-dir", "D"])
    assert out == {"holds_gpu": False, "orphans": []}
    assert len(calls) == 1
    ladder_dir, kw = calls[0]
    assert ladder_dir == str(ladder)
    assert kw["phase"] == "3"
    assert kw["settle_s"] == 90
    assert kw["router_log"] == "P"
    assert kw["config_dir"] == "D"


def test_cli_orphans_defaults_settle_s_zero_and_router_log_none(monkeypatch, tmp_path):
    calls = []

    def recorder(ladder_dir, **kw):
        calls.append((str(ladder_dir), dict(kw)))
        return {"holds_gpu": False, "orphans": []}

    monkeypatch.setattr(aw, "orphans", recorder)
    ladder = tmp_path / "ladder"
    _cli(monkeypatch, ["orphans", "--dir", str(ladder), "--phase", "1",
                       "--config-dir", "D"])
    assert len(calls) == 1
    _ladder_dir, kw = calls[0]
    assert kw["phase"] == "1"
    assert kw["settle_s"] == 0
    assert kw["router_log"] is None
    assert kw["config_dir"] == "D"
