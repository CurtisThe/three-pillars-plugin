"""Inline Python follows the cwd it really runs in (PR #323 review, round 1).

The shell classifier tracks a `cd`, but the inline-Python scan used to judge
relative literals against the payload cwd. So `cd .. && python3 -c
"…rmtree('b')"` from design `a` was allowed and would delete the sibling
design's worktree. Now a `cd`/`pushd`/`popd` segment anywhere in the command,
an `os.chdir(...)` in the source, or a `cwd=` keyword on a subprocess call
leaves relative literals unprovable (denied). Absolute literals inside the
roots stay allowed. The fixture builds a real repo with linked worktrees under
`tmp_path`; nothing is deleted.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

from delete_fence_py import check_python
from reviewer_delete_guard import classify

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures"))
from delete_fence_repo import build  # noqa: E402

import delete_fence_hook as hook  # noqa: E402


@pytest.fixture
def tree(tmp_path):
    r = build(tmp_path)
    out = tmp_path / "out"
    (out / "x").mkdir(parents=True)
    home = tmp_path / "home"
    home.mkdir()
    env = {"TP_DESIGN_RUN": "1", "CLAUDE_PROJECT_DIR": r["a"], "HOME": str(home),
           "TP_FENCE_PAD_BASE": str(tmp_path / "no-pad")}
    return {**r, "out": str(out), "env": env}


def _decision(tree, command):
    payload = {"tool_name": "Bash", "cwd": tree["a"], "session_id": "s1",
               "tool_input": {"command": command}}
    out, code = hook.run(payload, env=dict(tree["env"]))
    assert code == 0
    return json.loads(out)["hookSpecificOutput"]["permissionDecision"] if out else "allow"


def _py(body):
    return 'python3 -c "%s"' % body


RMTREE_B = _py("import shutil; shutil.rmtree('b')")
RMTREE_X = _py("import shutil; shutil.rmtree('x')")


def test_cd_up_then_relative_rmtree_of_the_sibling_is_denied(tree):
    assert _decision(tree, "cd .. && " + RMTREE_B) == "deny"


@pytest.mark.parametrize("prefix", ["cd {out} && ", "cd ~ && ", "pushd {out} && ",
                                    "cd {out}; ", "popd; "])
def test_any_cwd_move_makes_inline_relative_literals_unprovable(tree, prefix):
    assert _decision(tree, prefix.format(out=tree["out"]) + RMTREE_X) == "deny"


def test_cd_inside_a_nested_shell_string_is_followed(tree):
    cmd = "bash -c \"cd .. && python3 -c 'import shutil; shutil.rmtree(\\\"b\\\")'\""
    assert _decision(tree, cmd) == "deny"


def test_relative_inline_delete_without_any_cd_stays_allowed(tree):
    assert _decision(tree, _py("import shutil; shutil.rmtree('build')")) == "allow"


def test_absolute_literal_inside_the_root_after_cd_stays_allowed(tree):
    body = "import shutil; shutil.rmtree('%s/build')" % tree["a"]
    assert _decision(tree, "cd .. && " + _py(body)) == "allow"


def test_subprocess_with_a_cwd_keyword_and_relative_operand_is_denied(tree):
    body = "import subprocess; subprocess.run(['rm', '-rf', 'x'], cwd='%s')" % tree["out"]
    assert _decision(tree, _py(body)) == "deny"


def test_subprocess_with_a_cwd_keyword_and_absolute_inside_operand_is_allowed(tree):
    body = ("import subprocess; subprocess.run(['rm', '-rf', '%s/x'], cwd='%s')"
            % (tree["a"], tree["out"]))
    assert _decision(tree, _py(body)) == "allow"


def test_os_chdir_then_relative_rmtree_is_denied(tree):
    body = "import os, shutil; os.chdir('%s'); shutil.rmtree('x')" % tree["out"]
    assert _decision(tree, _py(body)) == "deny"


def test_os_chdir_then_absolute_inside_rmtree_is_allowed(tree):
    body = "import os, shutil; os.chdir('%s'); shutil.rmtree('%s/build')" % (
        tree["out"], tree["a"])
    assert _decision(tree, _py(body)) == "allow"


# --- check_python directly: the chdir / cwd= rules without the hook ---------

def _shell(root):
    def check(text, cwd=root):
        v = classify(text, scratch=[root], cwd=cwd, mode="fence")
        return None if v.allowed else v.reason
    return check


def test_check_python_aliased_chdir_makes_relative_unprovable(tmp_path):
    root = str(tmp_path)
    src = "from os import chdir\nimport shutil\nchdir('/elsewhere')\nshutil.rmtree('build')"
    assert check_python(src, [root], root, _shell(root))


def test_check_python_chdir_makes_relative_subprocess_operand_unprovable(tmp_path):
    root = str(tmp_path)
    src = "import os, subprocess\nos.chdir('/elsewhere')\nsubprocess.run(['rm', '-rf', 'x'])"
    assert check_python(src, [root], root, _shell(root))


def test_check_python_without_chdir_keeps_relative_inside(tmp_path):
    root = str(tmp_path)
    src = "import shutil, subprocess\nshutil.rmtree('build')\nsubprocess.run(['rm', '-rf', 'x'])"
    assert check_python(src, [root], root, _shell(root)) is None
