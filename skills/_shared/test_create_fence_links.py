"""test_create_fence_links.py - a link made and written through in one command (run-scratch-in-fence B1).

The hook resolves every target before the command runs, so a link made earlier in
the same command is not yet there: `ln -s ~/.config c && mkdir c/foo` would create
`~/.config/foo`. A command that creates a symlink whose path is, or is a prefix of,
any other create target of the same command is therefore refused outright. The
refusal names both paths. Shell and inline-Python link makers are covered. Nothing
is created; the hook only reads (helpers in test_create_fence_hook.py).
"""
from __future__ import annotations

import os

import pytest

import create_fence_targets
from test_create_fence_hook import bash, denial, make_repo


@pytest.fixture(scope="module")
def repo(tmp_path_factory):
    return make_repo(tmp_path_factory.mktemp("create-fence-links"))


def _refused_naming(repo, command, *paths):
    out, code = bash(repo, command)
    reason = denial(out)
    assert code == 0 and reason, "%r should be refused" % command
    for path in paths:
        assert path in reason, "%s should be named in the refusal" % path
    return reason


def test_a_link_then_a_mkdir_through_it_is_refused_and_names_both_paths(repo):
    a = repo["a"]
    _refused_naming(repo, "ln -s ~/.config c && mkdir c/foo", os.path.join(a, "c"),
                    os.path.join(a, "c", "foo"))


@pytest.mark.parametrize("command", [
    "ln -sf ~/.cache c; touch c/z",
    "ln -s ~/.cache c && echo hi > c/z",
    "ln -s /tmp l && touch l/z",
    "ln -s ~/.cache c && touch c",
    "ln --symbolic ~/.cache c && cp x c/y",
    "ln -s ~/.cache c && ln -s x c/inner",
    "ln -s ~/.cache c && cd c && touch z",
    "ln -s ~/.config c && mkdir c/../foo",
    "ln -s ~/.config l && touch x/../l/f",
])
def test_a_shell_link_then_a_create_through_it_is_refused(repo, command):
    _refused_naming(repo, command)


@pytest.mark.parametrize("command", [
    "python3 -c 'import os; os.symlink(\"/tmp\", \"l\"); open(\"l/z\", \"w\")'",
    "python3 -c 'from pathlib import Path; Path(\"l\").symlink_to(\"/tmp\"); "
    "Path(\"l/z\").touch()'",
])
def test_an_inline_python_link_then_a_create_through_it_is_refused(repo, command):
    _refused_naming(repo, command, os.path.join(repo["a"], "l"))


@pytest.mark.parametrize("command", [
    "ln -s x l && ls l",
    "mkdir -p d && ln -s x d/l",
    "ln -sf a l && ln -sf b l",
    "ln -s x l && touch other",
    "python3 -c 'import os; os.symlink(\"/tmp\", \"l\")'",
])
def test_a_link_with_no_create_through_it_is_allowed(repo, command):
    assert bash(repo, command) == ("", 0), command


def test_shell_scan_reports_the_conflict_pair(repo):
    paths, unprovable, conflict = create_fence_targets.shell_scan(
        "ln -s ~/.config c && mkdir c/foo", repo["a"], {"HOME": repo["home"]})
    assert conflict == (os.path.join(repo["a"], "c"), os.path.join(repo["a"], "c", "foo"))
    assert create_fence_targets.shell_targets(
        "ln -s ~/.config c && mkdir c/foo", repo["a"], {"HOME": repo["home"]}) == (paths, unprovable)


def test_dotdot_after_a_link_stays_in_the_literal_so_the_hook_resolves_the_link_first(repo):
    env = {"HOME": repo["home"]}
    paths, _unprovable = create_fence_targets.shell_targets(
        "mkdir %s/out-link/../x" % repo["run"], repo["a"], env)
    assert paths == ["%s/out-link/../x" % repo["run"]]
