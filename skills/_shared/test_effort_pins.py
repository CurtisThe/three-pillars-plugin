"""Tests for effort_pins.py — only the proven override (`CLAUDE_CODE_EFFORT_LEVEL`) warns.

design: run-throughput 6.3; seat ruling G2 (PR #178 live checks #2/#3): a settings-file
`effortLevel` / `modelSettings.*.effortLevel` pin never overrides agent frontmatter, so it
is never reported and no line advises removing it.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import agent_override_warn as aow  # noqa: E402
import effort_pins as ep  # noqa: E402

# The live-check shape: a profile settings.json carrying all three settings pins.
PINNED = {"effortLevel": "high",
          "modelSettings": {"claude-opus-5-5": {"effortLevel": "high"},
                            "claude-sonnet-5-5": {"effortLevel": "high"}}}


def _profile(tmp_path: Path) -> Path:
    cfg = tmp_path / "profile"
    cfg.mkdir()
    (cfg / "settings.json").write_text(json.dumps(PINNED), encoding="utf-8")
    repo = tmp_path / "repo" / ".claude"
    repo.mkdir(parents=True)
    for name in ("settings.json", "settings.local.json"):
        (repo / name).write_text(json.dumps(PINNED), encoding="utf-8")
    return cfg


def test_env_var_gives_one_line_with_flattens_claim():
    assert ep.detect({"CLAUDE_CODE_EFFORT_LEVEL": "high"}) == [
        "⚠ effort pin: CLAUDE_CODE_EFFORT_LEVEL = 'high' — flattens every agent variant"]


def test_no_env_var_no_line():
    assert ep.detect({}) == []
    assert ep.detect({"CLAUDE_CONFIG_DIR": "/x", "OTHER": "high"}) == []


def test_settings_file_pins_never_warn(tmp_path):
    """The live-check profile (three settings pins) yields no warning at all."""
    cfg = _profile(tmp_path)
    env = {"CLAUDE_CONFIG_DIR": str(cfg), "HOME": str(tmp_path)}
    assert aow.detect(tmp_path / "repo", env=env) is None


def test_settings_pins_plus_env_var_warns_only_on_env(tmp_path):
    cfg = _profile(tmp_path)
    env = {"CLAUDE_CONFIG_DIR": str(cfg), "CLAUDE_CODE_EFFORT_LEVEL": "low"}
    msg = aow.detect(tmp_path / "repo", env=env)
    assert msg == "⚠ effort pin: CLAUDE_CODE_EFFORT_LEVEL = 'low' — flattens every agent variant"
    assert "settings" not in msg and "effortLevel" not in msg and "remove" not in msg.lower()


def test_cli_with_settings_pins_prints_nothing(tmp_path):
    cfg = _profile(tmp_path)
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "CLAUDE_CONFIG_DIR": str(cfg)}
    r = subprocess.run([sys.executable, str(HERE / "agent_override_warn.py"),
                        "--root", str(tmp_path / "repo")],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0 and r.stdout == ""


def test_flattens_wording_true_and_null():
    assert "flattens every agent variant" in ep.flattens_clause(True)
    assert "flattens every agent variant" in ep.flattens_clause(None)


def test_recorded_value_is_true():
    assert ep.ENV_OVERRIDES_FRONTMATTER is True


def test_false_recording_keeps_source_drops_claim(monkeypatch):
    monkeypatch.setattr(ep, "ENV_OVERRIDES_FRONTMATTER", False)
    line = ep.detect({"CLAUDE_CODE_EFFORT_LEVEL": "high"})[0]
    assert line == "⚠ effort pin: CLAUDE_CODE_EFFORT_LEVEL = 'high'"
    assert "— " not in line and "flattens" not in line
