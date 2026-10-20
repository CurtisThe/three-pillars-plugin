"""A `$` or a backtick in an inline-Python path is not a literal (PR #323 review, round 1).

bash expands `$VAR`, `${VAR}` and backticks inside a double-quoted `-c` string
and inside an unquoted heredoc before Python ever runs, so `rmtree('$HOME/foo')`
deletes `<home>/foo`, not `<cwd>/$HOME/foo`. The scan cannot know the expanded
value, so such a path is unprovable and denied (fail closed, whatever the
quoting). The fixture builds a real repo with linked worktrees under `tmp_path`;
nothing is deleted.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

from delete_fence_py import check_python

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures"))
from delete_fence_repo import build  # noqa: E402

import delete_fence_hook as hook  # noqa: E402


@pytest.fixture
def tree(tmp_path):
    r = build(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    env = {"TP_DESIGN_RUN": "1", "CLAUDE_PROJECT_DIR": r["a"], "HOME": str(home),
           "TP_FENCE_PAD_BASE": str(tmp_path / "no-pad")}
    return {**r, "env": env}


def _decision(tree, command):
    payload = {"tool_name": "Bash", "cwd": tree["a"], "session_id": "s1",
               "tool_input": {"command": command}}
    out, code = hook.run(payload, env=dict(tree["env"]))
    assert code == 0
    return json.loads(out)["hookSpecificOutput"]["permissionDecision"] if out else "allow"


@pytest.mark.parametrize("path", ["$HOME/foo", "${HOME}/foo", "`pwd`/../b", "x/$(pwd)"])
def test_double_quoted_c_string_with_an_expansion_is_denied(tree, path):
    cmd = 'python3 -c "import shutil; shutil.rmtree(\'%s\')"' % path
    assert _decision(tree, cmd) == "deny"


def test_unquoted_heredoc_with_an_expansion_is_denied(tree):
    cmd = "python3 - <<EOF\nimport shutil\nshutil.rmtree('$HOME/foo')\nEOF"
    assert _decision(tree, cmd) == "deny"


def test_expansion_in_a_path_receiver_is_denied(tree):
    cmd = 'python3 -c "from pathlib import Path; Path(\'$HOME/f\').unlink()"'
    assert _decision(tree, cmd) == "deny"


def test_plain_relative_literal_stays_allowed(tree):
    cmd = 'python3 -c "import shutil; shutil.rmtree(\'build\')"'
    assert _decision(tree, cmd) == "allow"


def test_quoted_heredoc_with_a_plain_inside_path_stays_allowed(tree):
    cmd = "python3 - <<'EOF'\nimport shutil\nshutil.rmtree('%s/build')\nEOF" % tree["a"]
    assert _decision(tree, cmd) == "allow"


@pytest.mark.parametrize("path", ["<R>/$X", "<R>/`x`", "<R>/${X}/y"])
def test_check_python_refuses_an_expansion_in_an_absolute_path(tmp_path, path):
    root = str(tmp_path)
    src = "import shutil\nshutil.rmtree('%s')" % path.replace("<R>", root)
    assert check_python(src, [root], root, lambda text, cwd=None: None)
