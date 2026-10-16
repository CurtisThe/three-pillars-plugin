"""Tests for local_timeouts CLI: `claude_version` + `main` (no real `claude` calls)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import local_timeouts as lt  # noqa: E402


class FakeResult:
    def __init__(self, out="2.1.286 (Claude Code)", err=""):
        self.stdout = out
        self.stderr = err
        self.returncode = 0


def _write_cfg(root) -> Path:
    p = root / ".three-pillars" / "config.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"schema_version": 1, "local_implement": {"enabled": True}}),
                 encoding="utf-8")
    return p


def _write_settings(root, data) -> Path:
    p = root / ".claude" / "settings.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
    return p


# --- claude_version -----------------------------------------------------------

def test_claude_version_parses_and_invocation():
    calls = []

    def run(cmd, **kw):
        calls.append((cmd, kw))
        return FakeResult()

    assert lt.claude_version(run=run) == (2, 1, 286)
    cmd, kw = calls[0]
    assert cmd == ["claude", "--version"]
    assert kw.get("timeout") == 5
    assert kw.get("capture_output") is True


def test_claude_version_missing_binary():
    def run(cmd, **kw):
        raise FileNotFoundError("claude")

    assert lt.claude_version(run=run) is None


def test_claude_version_timeout():
    def run(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd="claude", timeout=5)

    assert lt.claude_version(run=run) is None


def test_claude_version_oserror():
    def run(cmd, **kw):
        raise OSError("spawn failed")

    assert lt.claude_version(run=run) is None


def test_claude_version_unparseable():
    def run(cmd, **kw):
        return FakeResult(out="no digits here")

    assert lt.claude_version(run=run) is None


# --- offer --------------------------------------------------------------------

def test_offer_prints_json_and_writes_nothing(tmp_path, capsys):
    cfg, settings = _write_cfg(tmp_path), _write_settings(tmp_path, {"env": {}})
    cfg_b, set_b = cfg.read_bytes(), settings.read_bytes()
    rc = lt.main(["offer", "--root", str(tmp_path), "--claude-version", "2.1.242"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["wanted"] is True
    assert out["settled"] is False
    assert out["version"] == "2.1.242"
    assert out["version_ok"] is True
    assert out["plan"]["path"] == str(settings)
    assert cfg.read_bytes() == cfg_b
    assert settings.read_bytes() == set_b


def test_offer_version_ok_false(tmp_path, capsys):
    _write_cfg(tmp_path)
    _write_settings(tmp_path, {"env": {}})
    rc = lt.main(["offer", "--root", str(tmp_path), "--claude-version", "2.1.241"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["version"] == "2.1.241"
    assert out["version_ok"] is False


def test_offer_version_unknown_is_null(tmp_path, capsys):
    _write_cfg(tmp_path)
    _write_settings(tmp_path, {"env": {}})
    rc = lt.main(["offer", "--root", str(tmp_path), "--claude-version", "unknown"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["version"] is None
    assert out["version_ok"] is None


def test_offer_without_flag_uses_claude_version(tmp_path, capsys, monkeypatch):
    _write_cfg(tmp_path)
    _write_settings(tmp_path, {"env": {}})
    monkeypatch.setattr(lt, "claude_version", lambda run=subprocess.run: (2, 1, 286))
    rc = lt.main(["offer", "--root", str(tmp_path)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["version"] == "2.1.286"
    assert out["version_ok"] is True


@pytest.mark.parametrize("data", ["[]", '{"env": []}', "not json at all"])
@pytest.mark.parametrize("cmd", [["offer", "--claude-version", "2.1.242"], ["apply"]])
def test_malformed_settings_exit_2_unchanged(tmp_path, capsys, data, cmd):
    cfg = _write_cfg(tmp_path)
    settings = _write_settings(tmp_path, data)
    cfg_b, set_b = cfg.read_bytes(), settings.read_bytes()
    rc = lt.main(cmd + ["--root", str(tmp_path)])
    assert rc == 2
    err = capsys.readouterr().err
    assert len(err.strip().splitlines()) == 1
    assert settings.read_bytes() == set_b
    assert cfg.read_bytes() == cfg_b


# --- apply / decline / status -------------------------------------------------

def test_apply_prints_record_and_writes(tmp_path, capsys):
    _write_cfg(tmp_path)
    rc = lt.main(["apply", "--root", str(tmp_path)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["declined"] is False
    assert out["applied_at"]
    s = json.loads((tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert s["env"]["API_TIMEOUT_MS"] == "1800000"


def test_decline_prints_record(tmp_path, capsys):
    _write_cfg(tmp_path)
    rc = lt.main(["decline", "--root", str(tmp_path)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["declined"] is True
    assert out["applied_at"] is None


def test_status_exit_0_json(tmp_path, capsys):
    _write_cfg(tmp_path)
    rc = lt.main(["status", "--root", str(tmp_path)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["state"] == "unoffered"
    assert "line" in out


def test_status_exit_0_on_malformed_settings(tmp_path, capsys):
    _write_cfg(tmp_path)
    _write_settings(tmp_path, "[]")
    rc = lt.main(["status", "--root", str(tmp_path)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["state"] == "unoffered"
