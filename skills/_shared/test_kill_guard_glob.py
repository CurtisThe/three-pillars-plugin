"""test_kill_guard_glob.py — a globbed path is expanded before the scan.

design: no-kill-by-name (PR #237 review round 4). Payloads and fixture files
only: no process is started or killed by these tests.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import kill_guard_hook as hook  # noqa: E402

KILL_TEST = 'import subprocess\n\n\ndef test_a():\n    subprocess.run(["pkill", "-x", "claude"])\n'
CLEAN_TEST = "def test_ok():\n    assert True\n"


def _decision(command, cwd):
    out, _ = hook.run({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)})
    return json.loads(out)["hookSpecificOutput"]["permissionDecision"] if out else "allow"


@pytest.mark.parametrize("command", [
    "pytest g/test_*.py",
    "python3 -m pytest -n 4 g/test_*.py",
    "TMPDIR=~/t pytest -q g/test_[a-z].py",
    "pytest g/**/test_*.py",
    "python3 g/test_?.py",
])
def test_a_glob_over_a_name_kill_test_is_denied(tmp_path, command):
    (tmp_path / "g").mkdir()
    (tmp_path / "g" / "test_a.py").write_text(KILL_TEST, encoding="utf-8")
    assert _decision(command, tmp_path) == "deny", command


def test_a_glob_over_a_heredoc_written_test_is_denied(tmp_path):
    command = ("mkdir -p g && cat > g/test_w.py <<'EOF'\n" + KILL_TEST + "EOF\n"
               "pytest g/test_*.py")
    assert _decision(command, tmp_path) == "deny"


def test_a_glob_over_clean_tests_is_allowed(tmp_path):
    (tmp_path / "g").mkdir()
    (tmp_path / "g" / "test_a.py").write_text(CLEAN_TEST, encoding="utf-8")
    assert _decision("pytest g/test_*.py", tmp_path) == "allow"
    assert _decision("pytest g/test_nomatch_*.py", tmp_path) == "allow"
