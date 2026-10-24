"""test_create_fence_braces.py - a simple shell brace list is a literal target (run-scratch-in-fence B2).

`mkdir -p ~/.cache/{a,b}` is two literal paths, not a computed one, so the create
fence reads it exactly like `mkdir -p ~/.cache/a ~/.cache/b`. Simple lists
(`{a,b}`, nested lists, `{1..3}` numeric ranges, zero padding) expand to at most 64
words; a longer expansion, an unmatched brace, a lone `{x}` or a letter range stays
unprovable (allowed, as before: the leftover check reports a stray).
`${NAME}` is a variable, never a brace list. Nothing is created (helpers in
test_create_fence_hook.py).
"""
from __future__ import annotations

import os

import pytest

from create_fence_targets import shell_targets
from test_create_fence_hook import TMP, bash, denial, make_repo

H = "/home/u"
ENV = {"HOME": H}


def _paths(cmd):
    return shell_targets(cmd, "/srv/w", dict(ENV))


@pytest.mark.parametrize("cmd,expected", [
    ("mkdir -p ~/.cache/{a,b}", [H + "/.cache/a", H + "/.cache/b"]),
    ("touch /x/{a,b}/{c,d}", ["/x/a/c", "/x/a/d", "/x/b/c", "/x/b/d"]),
    ("touch /x/{a,b{1,2}}", ["/x/a", "/x/b1", "/x/b2"]),
    ("touch /x/f{1..3}", ["/x/f1", "/x/f2", "/x/f3"]),
    ("touch /x/f{03..01}", ["/x/f03", "/x/f02", "/x/f01"]),
    ("touch /x/{,a}", ["/x/", "/x/a"]),
    ("touch ${HOME}/{a,b}", [H + "/a", H + "/b"]),
    ("echo hi > /x/{a,b}", ["/x/a", "/x/b"]),
])
def test_a_simple_brace_list_expands_to_literal_paths(cmd, expected):
    paths, unprovable = _paths(cmd)
    assert paths == [os.path.normpath(p) for p in expected] and not unprovable


def test_sixty_four_words_expand_and_sixty_five_do_not():
    paths, unprovable = _paths("touch /x/f{1..64}")
    assert len(paths) == 64 and not unprovable
    paths, unprovable = _paths("touch /x/f{1..65}")
    assert paths == [] and unprovable
    paths, unprovable = _paths("touch /x/{1..9}{1..9}")
    assert paths == [] and unprovable


@pytest.mark.parametrize("cmd", ["touch /x/{a,b", "touch /x/{a}", "touch /x/{a..c}",
                                 "touch /x/{}", "touch /x/f{1..3..2}"])
def test_a_brace_that_cannot_be_expanded_literally_is_unprovable(cmd):
    paths, unprovable = _paths(cmd)
    assert paths == [] and unprovable


@pytest.fixture(scope="module")
def repo(tmp_path_factory):
    return make_repo(tmp_path_factory.mktemp("create-fence-braces"))


def test_a_brace_list_is_refused_exactly_like_its_words(repo):
    for plain, braced in [("mkdir -p ~/.cache/a ~/.cache/b", "mkdir -p ~/.cache/{a,b}"),
                          ("touch %s/x1 %s/x2 %s/x3" % (TMP, TMP, TMP), "touch %s/x{1..3}" % TMP),
                          ("mkdir ~/q1/z ~/q2/z", "mkdir ~/q{1,2}/z")]:
        assert denial(bash(repo, plain)[0]), plain
        assert denial(bash(repo, braced)[0]), braced


def test_a_brace_list_inside_the_run_dir_is_allowed(repo):
    assert bash(repo, "mkdir -p %s/{a,b}" % repo["run"]) == ("", 0)
    assert denial(bash(repo, "mkdir %s/a ~/.cache/{b,c}" % repo["run"])[0])


def test_an_unexpandable_brace_stays_allowed(repo):
    assert bash(repo, "mkdir -p ~/.cache/f{1..65}") == ("", 0)
    assert bash(repo, "mkdir -p ~/.cache/{a}") == ("", 0)
