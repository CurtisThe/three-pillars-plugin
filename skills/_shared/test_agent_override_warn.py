"""Tests for agent_override_warn.py — the project-local worker-override warning.

design: local-implement-and-review (Task 3.5, design Behavior 11).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import agent_override_warn as aow  # noqa: E402

SCRIPT = Path(__file__).resolve().parent / "agent_override_warn.py"


@pytest.fixture(autouse=True)
def _isolate_profile(tmp_path, monkeypatch):
    """Keep the real profile's effort pins out of the 'no warning' cases."""
    home = tmp_path / "_home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home / ".claude"))
    monkeypatch.delenv("CLAUDE_CODE_EFFORT_LEVEL", raising=False)


def _agent(root: Path, name: str, model: str | None, body: str = "Worker.\n") -> Path:
    path = root / ".claude" / "agents" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    front = f"---\nname: {name[:-3]}\n" + (f"model: {model}\n" if model else "") + "---\n"
    path.write_text(front + body, encoding="utf-8")
    return path


def test_detect_cases(tmp_path):
    # No .claude/agents at all.
    assert aow.detect(tmp_path) is None
    # Opus overrides (alias, full id, quoted) are fine; so is an unrelated agent.
    _agent(tmp_path, "tp-worker.md", "opus")
    _agent(tmp_path, "tp-task-worker.md", '"claude-opus-4-8"')
    _agent(tmp_path, "council-ada.md", "haiku")
    assert aow.detect(tmp_path) is None
    # A haiku pin on tp-worker warns, naming the file and the bypass.
    _agent(tmp_path, "tp-worker.md", "haiku")
    msg = aow.detect(tmp_path)
    assert msg is not None
    assert ".claude/agents/tp-worker.md" in msg and "haiku" in msg
    assert "bypasses the eligibility gate" in msg
    assert "tp-task-worker.md" not in msg
    # A sonnet full id on tp-task-worker warns too: one line per offending file.
    _agent(tmp_path, "tp-task-worker.md", "claude-sonnet-4-6")
    assert len(aow.detect(tmp_path).splitlines()) == 2
    # The tp-local markers warn even when the model is opus.
    for marker in ("tp-local-model: haiku\n", "# tp-local: generated override\n"):
        _agent(tmp_path, "tp-worker.md", "opus", body=marker)
        _agent(tmp_path, "tp-task-worker.md", "opus")
        msg = aow.detect(tmp_path)
        assert msg is not None and "tp-worker.md" in msg and "tp-local" in msg
        assert "bypasses the eligibility gate" in msg and len(msg.splitlines()) == 1
    # Unreadable override (a directory in the file's place) → fail-open None.
    (tmp_path / ".claude" / "agents" / "tp-worker.md").unlink()
    (tmp_path / ".claude" / "agents" / "tp-worker.md").mkdir()
    assert aow.detect(tmp_path) is None
    # Undecodable bytes are unreadable too.
    (tmp_path / ".claude" / "agents" / "tp-task-worker.md").write_bytes(b"\xff\xfe model: haiku")
    assert aow.detect(tmp_path) is None


def test_model_family_strips_bracket_suffix():
    assert aow.model_family("opus[1m]") == "opus"
    assert aow.model_family("claude-opus-4-8[1m]") == "opus"


def _cli(*args: str):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)


def test_cli_prints_and_exits_0(tmp_path):
    clean = _cli("--root", str(tmp_path))
    assert clean.returncode == 0 and clean.stdout == ""
    _agent(tmp_path, "tp-worker.md", "haiku")
    warned = _cli("--root", str(tmp_path))
    assert warned.returncode == 0
    assert "tp-worker.md" in warned.stdout and "bypasses the eligibility gate" in warned.stdout
    # Any error — here a root that is a file, not a directory — still exits 0.
    stray = tmp_path / "not-a-dir"
    stray.write_text("x", encoding="utf-8")
    assert _cli("--root", str(stray)).returncode == 0
    assert _cli("--root", str(tmp_path / "missing")).returncode == 0
    assert _cli("--no-such-flag").returncode == 0
    # From the repo's own cwd with no flags, the default root is ".".
    here = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True,
                          cwd=str(tmp_path))
    assert here.returncode == 0 and "tp-worker.md" in here.stdout


def test_detect_appends_effort_pin_lines(tmp_path):
    msg = aow.detect(tmp_path, env={"CLAUDE_CODE_EFFORT_LEVEL": "high"})
    assert msg is not None and "effort pin" in msg


def test_cli_prints_effort_pin_and_exits_0(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_EFFORT_LEVEL", "high")
    r = subprocess.run([sys.executable, str(SCRIPT), "--root", str(tmp_path)],
                       capture_output=True, text=True)
    assert r.returncode == 0 and "effort pin" in r.stdout
