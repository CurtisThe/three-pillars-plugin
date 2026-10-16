"""test_kill_guard_subst.py — quoted substitutions and heredoc-written tests.

design: no-kill-by-name (PR #237 review round 2). A name kill inside a quoted
command substitution (`out="$(pkill …)"`) is denied, and a test file the same
command writes from a heredoc is scanned when `pytest` walks its directory.
Payloads and fixture strings only: no process is started or killed by these tests.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_SHARED = Path(__file__).resolve().parent
sys.path.insert(0, str(_SHARED))

import kill_guard_hook as hook  # noqa: E402

_KILL = "pk" + "ill"  # fixture text only: the name-kill verb under test


def _decision(command, cwd):
    out, rc = hook.run({"tool_name": "Bash", "tool_input": {"command": command},
                        "cwd": str(cwd)})
    assert rc == 0
    return json.loads(out)["hookSpecificOutput"]["permissionDecision"] if out else "allow"


@pytest.mark.parametrize("command", [
    'out="$(%s -x claude)"' % _KILL,
    'echo "stopping: $(killall claude)"',
    'out="`%s -x claude`"' % _KILL,
    'x="$(kill $(pgrep foo))"',
])
def test_quoted_substitution_name_kill_is_denied(command, tmp_path):
    assert _decision(command, tmp_path) == "deny"


def test_quoted_substitution_running_a_killing_script_is_denied(tmp_path):
    (tmp_path / "t.py").write_text("import os\nos.system('%s -x claude')\n" % _KILL)
    assert _decision('out="$(python3 t.py 2>&1)"', tmp_path) == "deny"


@pytest.mark.parametrize("command", [
    'out="$(git log --oneline -3)"',
    'echo "$(date) %s mentioned in prose"' % _KILL,
    "echo '$(%s x)' > notes.txt" % _KILL,
    "cat > notes.md <<'EOF'\nnever run $(%s -x claude)\nEOF" % _KILL,
])
def test_substitution_without_a_kill_command_is_allowed(command, tmp_path):
    assert _decision(command, tmp_path) == "allow"


@pytest.mark.parametrize("tail", ["pytest tests/", "pytest -q", "python3 -m pytest tests"])
def test_heredoc_written_test_collected_by_a_pytest_walk_is_denied(tail, tmp_path):
    (tmp_path / "tests").mkdir()
    body = "import subprocess\ndef test_a():\n    subprocess.run(['%s', '-x', 'claude'])\n" % _KILL
    command = "cat > tests/test_x.py <<'EOF'\n" + body + "EOF\n" + tail
    assert _decision(command, tmp_path) == "deny"


def test_heredoc_written_test_outside_the_walked_dir_is_not_collected(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "other").mkdir()
    body = "import subprocess\ndef test_a():\n    subprocess.run(['%s', 'x'])\n" % _KILL
    command = "cat > other/test_x.py <<'EOF'\n" + body + "EOF\npytest tests/"
    assert _decision(command, tmp_path) == "allow"


# PR #237 review round 3: the written-file model must reach a nested scan and a
# directory that is not on disk yet, and keep the path the write resolved to.
_TEST_BODY = "import subprocess\ndef test_a():\n    subprocess.run(['%s', '-x', 'claude'])\n" % _KILL


@pytest.mark.parametrize("tail", [
    'out="$(python3 t.py 2>&1)"',
    "bash -c 'python3 t.py'",
    'echo "r: `python3 t.py`"',
])
def test_heredoc_written_script_run_in_a_nested_scan_is_denied(tail, tmp_path):
    body = "import os\nos.system('%s -x claude')\n" % _KILL
    assert _decision("cat > t.py <<'EOF'\n" + body + "EOF\n" + tail, tmp_path) == "deny"


@pytest.mark.parametrize("tail", ["pytest fresh", "cd fresh && pytest", 'out="$(pytest -q fresh)"'])
def test_heredoc_written_test_in_a_dir_the_command_makes_is_denied(tail, tmp_path):
    command = "mkdir -p fresh && cat > fresh/test_x.py <<'EOF'\n" + _TEST_BODY + "EOF\n" + tail
    assert _decision(command, tmp_path) == "deny"


def test_heredoc_written_test_in_an_absolute_fresh_dir_is_denied(tmp_path):
    fresh, cwd = tmp_path / "fresh", tmp_path / "other"
    cwd.mkdir()
    command = "mkdir -p %s && cat > %s/test_x.py <<'EOF'\n%sEOF\npytest %s" % (
        fresh, fresh, _TEST_BODY, fresh)
    assert _decision(command, cwd) == "deny"


def test_heredoc_written_test_keeps_its_write_time_dir_across_a_cd(tmp_path):
    (tmp_path / "tests").mkdir()
    command = "cd tests && cat > test_x.py <<'EOF'\n" + _TEST_BODY + "EOF\ncd .. && pytest tests"
    assert _decision(command, tmp_path) == "deny"


def test_fresh_dir_outside_the_walked_dir_is_still_not_collected(tmp_path):
    (tmp_path / "tests").mkdir()
    command = "mkdir -p other && cat > other/test_x.py <<'EOF'\n" + _TEST_BODY + "EOF\npytest tests/"
    assert _decision(command, tmp_path) == "allow"
