"""test_kill_guard_hook.py — the kill-guard PreToolUse hook denies name kills.

design: no-kill-by-name (Task 1.3). Payloads and fixture files only: no
process is started or killed by these tests.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_SHARED = Path(__file__).resolve().parent
sys.path.insert(0, str(_SHARED))

import kill_guard_hook as hook  # noqa: E402


def _payload(command, cwd=None, **extra):
    return {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": cwd, **extra}


def _denied(out):
    return bool(out) and json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "deny"


@pytest.mark.parametrize("command", [
    "pkill -x claude", "killall node", "pgrep -f fake | xargs kill",
    "kill $(pgrep -f fake)", "cd /x && bash -c 'pkill -x claude'",
])
def test_denies_command(command):
    out, rc = hook.run(_payload(command))
    assert rc == 0 and _denied(out)
    assert "stop only PIDs your own code started" in json.loads(out)[
        "hookSpecificOutput"]["permissionDecisionReason"]


@pytest.mark.parametrize("name,body,command", [
    ("s.py", 'import subprocess\nsubprocess.run(["pkill", "-x", "claude"])\n', "python3 s.py"),
    ("t.sh", "#!/bin/bash\nsleep 1\nkillall x\n", "bash t.sh"),
    ("u", "#!/usr/bin/env python3\nimport os\nos.system('pkill -f x')\n", "./u"),
    ("test_a.py", 'import subprocess\ndef test_x():\n    subprocess.run(["pkill", "y"])\n',
     "python3 -m pytest test_a.py::test_x -q"),
    ("test_b.py", 'import subprocess\ndef test_x():\n    subprocess.run(["killall", "y"])\n',
     "TMPDIR=~/t pytest -n 4 test_b.py"),
])
def test_denies_executed_script(tmp_path, name, body, command):
    (tmp_path / name).write_text(body)
    assert _denied(hook.run(_payload(command, cwd=str(tmp_path)))[0])


def test_follows_cd_to_the_script(tmp_path):
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "s.py").write_text('import subprocess\nsubprocess.run(["pkill", "z"])\n')
    assert _denied(hook.run(_payload("cd d && python3 s.py", cwd=str(tmp_path)))[0])


def test_waiver_does_not_unlock_a_run(tmp_path):
    (tmp_path / "s.py").write_text(
        'import subprocess\nsubprocess.run(["pkill", "z"])  # tp-allow-fragile: test\n')
    assert _denied(hook.run(_payload("python3 s.py", cwd=str(tmp_path)))[0])


@pytest.mark.parametrize("command", [
    "python3 -c 'import subprocess; subprocess.run([\"pkill\", \"-x\", \"claude\"])'",
    "python3 - <<'EOF'\nimport os\nos.system('killall claude')\nEOF",
])
def test_denies_inline_python(command):
    assert _denied(hook.run(_payload(command))[0])


def test_allows_unrelated(tmp_path):
    (tmp_path / "test_table.py").write_text('CASES = [("pkill -x claude", "deny")]\n')
    (tmp_path / "ok.py").write_text("print('hi')\n")
    for command in ("ls -la", "kill 12345", "grep -rn pkill .", "python3 ok.py",
                    "pytest test_table.py", "python3 missing.py"):
        assert hook.run(_payload(command, cwd=str(tmp_path))) == ("", 0), command


@pytest.mark.parametrize("agent", [None, "tp-worker", "three-pillars:tp-finalizer", "general-purpose"])
def test_every_agent_type(agent):
    extra = {"agent_type": agent} if agent else {}
    assert _denied(hook.run(_payload("pkill -x claude", **extra))[0])


def test_non_bash_tool_allowed():
    assert hook.run({"tool_name": "Write", "tool_input": {"content": "pkill"}}) == ("", 0)


def test_fail_mode(monkeypatch):
    import name_kill_scan

    def boom(*_a, **_k):
        raise RuntimeError("scanner bug")
    monkeypatch.setattr(name_kill_scan, "scan_shell", boom)
    assert _denied(hook.run(_payload("pkill -x claude"))[0])
    assert hook.run(_payload("echo hi")) == ("", 0)


def test_hooks_json_registers():
    cfg = json.loads((_SHARED / "hooks" / "claude-code-hooks.json").read_text(encoding="utf-8"))
    bash = [e for e in cfg["hooks"]["PreToolUse"] if e["matcher"] == "Bash"]
    commands = [h["command"] for e in bash for h in e["hooks"]]
    assert any(c.endswith('/skills/_shared/kill_guard_hook.py"') for c in commands)
    assert any(c.endswith('/skills/_shared/reviewer_delete_hook.py"') for c in commands)


_BAD_PY = 'import subprocess\nsubprocess.run(["pkill", "-x", "claude"])\n'
_BAD_TEST = 'import subprocess\n\n\ndef test_x():\n    subprocess.run(["pkill", "y"])\n'


@pytest.mark.parametrize("command", [
    'eval "$(ssh-agent -s)" && python3 bad.py',  # an unmodelled segment beside the run
    "$PY bad.py",                                # an unresolvable verb: named files still read
    "bash -o pipefail bad.sh",                   # an option value is not the script
    "uv run python bad.py",
    "source bad.sh",
    ". bad.sh",
    "pytest d/",
    "cd d && pytest -q",
    "python3 -m pytest -q d",
])
def test_review_round_discovery_gaps_are_closed(tmp_path, command):
    (tmp_path / "bad.py").write_text(_BAD_PY, encoding="utf-8")
    (tmp_path / "bad.sh").write_text("pkill -x claude\n", encoding="utf-8")
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "test_k.py").write_text(_BAD_TEST, encoding="utf-8")
    assert _denied(hook.run(_payload(command, cwd=str(tmp_path)))[0]), command


def test_own_pid_stop_beside_a_search_is_allowed():
    assert hook.run(_payload('ps -p "$PID" >/dev/null && kill "$PID"')) == ("", 0)


def test_files_without_a_kill_word_are_not_parsed(tmp_path):
    (tmp_path / "test_skill.py").write_text("def (:\n  skills = 1\n", encoding="utf-8")
    assert hook.run(_payload("pytest", cwd=str(tmp_path))) == ("", 0)
