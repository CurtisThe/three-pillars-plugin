"""test_create_fence_escapes.py - one test per producer row of design.md's table (run-scratch-in-fence 1.5).

Rows P2 to P5, P7, P8 and P10 are the create fence's own (L2); P1, P6, P11 and P12
are the redirect, pinned in test_redirect_lands_inside.py, and P9 is the leftover
check. Each test feeds the hook a command or tool call a run could make for that
producer, from a throwaway repo (helpers in test_create_fence_hook.py), and asserts
the decision: refused outside the roots, allowed once aimed inside the run dir.
Nothing is created; the hook only reads (test-fragility.md: assert on the decision).
"""
from __future__ import annotations

import os

import pytest

from test_create_fence_hook import TMP, bash, denial, fence, make_repo


@pytest.fixture(scope="module")
def repo(tmp_path_factory):
    return make_repo(tmp_path_factory.mktemp("create-fence-escapes"))


def _refused(repo, command):
    out, code = bash(repo, command)
    reason = denial(out)
    assert code == 0 and reason, "%r should be refused" % command
    return reason


def _allowed(repo, command):
    assert bash(repo, command) == ("", 0), "%r should be allowed" % command


def test_p2_an_explicit_mkdir_of_a_slot_dir_outside_is_refused(repo):
    for name in ("slot8-x", "pc2-chk", "impl-audit-pria"):
        reason = _refused(repo, "mkdir -p ~/t/%s" % name)
        assert repo["run"] in reason
        _allowed(repo, "mkdir -p %s/t/%s" % (repo["run"], name))
    _refused(repo, "mkdir -p %s/slot8-x" % TMP)
    _refused(repo, "mkdir -p ~/t/slot8-x ~/t/pc2-chk ~/t/impl-audit-pria")


def test_p3_mkdir_of_a_tmp_dir_under_home_is_refused(repo):
    _refused(repo, "mkdir ~/tmp")
    _refused(repo, "mkdir -p $HOME/tmp")
    _allowed(repo, "mkdir %s/tmp" % repo["run"])


def test_p4_a_cache_file_write_is_refused_by_a_redirect_python_and_the_write_tool(repo):
    cache = os.path.join(repo["home"], ".cache_tel11.json")
    _refused(repo, "echo hi > ~/.cache_tel11.json")
    _refused(repo, "echo hi >> %s" % cache)
    _refused(repo, "python3 -c 'open(\"%s\",\"w\").write(\"{}\")'" % cache)
    _refused(repo, "python3 -c 'from pathlib import Path; Path(\"%s\").write_text(\"{}\")'"
             % cache)
    assert denial(fence(repo, "Write", file_path=cache)[0])
    inside = os.path.join(repo["run"], ".cache_tel11.json")
    _allowed(repo, "echo hi > %s" % inside)
    _allowed(repo, "python3 -c 'open(\"%s\",\"w\")'" % inside)
    assert fence(repo, "Write", file_path=inside) == ("", 0)


def test_p5_touch_and_a_redirect_under_the_shared_tmp_are_refused(repo):
    _refused(repo, "touch %s/x" % TMP)
    _refused(repo, "echo hi > %s/x" % TMP)
    _refused(repo, "cd %s && touch x" % TMP)
    _refused(repo, "python3 -c 'open(\"%s/x\",\"w\")'" % TMP)
    _allowed(repo, "touch %s/x" % repo["run"])
    _allowed(repo, "cd %s && touch x" % repo["run"])


def test_p7_a_tree_maker_with_an_outside_destination_is_refused(repo):
    makers = ["tar -xf a.tar -C {d}/y", "unzip a.zip -d {d}/y", "git clone u {d}/y",
              "git worktree add {d}/y", "git init {d}/y", "rsync -a src/ {d}/y",
              "python3 -m venv {d}/y", "pip install --target {d}/y pkg"]
    for maker in makers:
        for outside in ("~", TMP):
            _refused(repo, maker.format(d=outside))
        _allowed(repo, maker.format(d=repo["run"]))


def test_p8_a_write_through_a_symlink_is_judged_by_where_it_lands(repo):
    run = repo["run"]
    # A link inside the run dir whose real ancestor is outside.
    _refused(repo, "touch %s/out-link/f" % run)
    _refused(repo, "mkdir -p %s/out-link/deeper/still" % run)
    assert denial(fence(repo, "Write", file_path=os.path.join(run, "out-link", "f"))[0])
    # A `..` after the link climbs from the link's target, not from the run dir.
    _refused(repo, "mkdir %s/out-link/../x" % run)
    assert denial(fence(repo, "Write", file_path=os.path.join(run, "out-link", "..", "x"))[0])
    # A dangling final component: the whole literal is resolved before the ancestor test.
    assert not os.path.exists(os.path.join(run, "dangling"))
    _refused(repo, "echo hi > %s/dangling" % run)
    assert denial(fence(repo, "Write", file_path=os.path.join(run, "dangling"))[0])
    # Making a link whose destination is inside is allowed, wherever it points.
    _allowed(repo, "ln -s %s/outside/f %s/newlink" % (repo["home"], run))


def test_p10_an_override_of_the_redirect_is_refused(repo):
    for name in ("TMPDIR", "TMP", "TEMP"):
        _refused(repo, "%s=~/t pytest" % name)
        _refused(repo, "export %s=/x" % name)
        _refused(repo, "env %s=/x pytest" % name)
        _allowed(repo, "%s=%s pytest" % (name, repo["run"]))
    for name in ("XDG_CACHE_HOME", "PIP_CACHE_DIR", "npm_config_cache", "UV_CACHE_DIR"):
        _refused(repo, "%s=/x npm i" % name)
        _allowed(repo, "export %s=%s/cache" % (name, repo["run"]))
