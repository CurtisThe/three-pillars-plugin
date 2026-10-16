"""Path containment for reviewer_delete_guard: scratch, symlink, glob, brace,
variable and cwd cases. Fixtures live under tmp_path; nothing is executed."""
import os

import pytest

from reviewer_delete_guard import _inside, classify


@pytest.fixture
def tree(tmp_path):
    scratch, other = tmp_path / "scratch", tmp_path / "other"
    scratch.mkdir()
    other.mkdir()
    os.symlink("../other", str(scratch / "link"))
    (scratch / "a1").write_text("")
    (scratch / "a2").write_text("")
    return str(scratch), str(other)


def _verdict(cmd, tree, cwd=None, scratch=True):
    sc, other = tree
    cmd = cmd.replace("<S>", sc).replace("<O>", other)
    return classify(cmd, scratch=sc if scratch else None, cwd=cwd or sc)


ALLOWED = [
    pytest.param("rm -rf <S>/pytest-out", id="rm-inside"),
    pytest.param("rm <S>/a*", id="rm-glob-inside"),
    pytest.param("mv <S>/a1 <S>/b", id="mv-inside"),
    pytest.param("mv -t <S>/d <S>/a1", id="mv-t-inside"),
    pytest.param("find <S>/sub -delete", id="find-inside"),
    pytest.param("rsync -a --delete <S>/a/ <S>/b/", id="rsync-inside"),
]

REFUSED = [
    pytest.param("rm -rf <S>/../other", id="dotdot"),
    pytest.param("rm -rf <S>/link/x", id="symlink-dir"),
    pytest.param("rm <S>/*", id="glob-symlink-match"),
    pytest.param("rm -rf <S>", id="scratch-root"),
    pytest.param("rm -rf <S>/{a,../../x}", id="brace"),
    pytest.param("rm -rf $SCRATCH/x", id="var"),
    pytest.param('rm -rf "${TP_SCRATCH}/x"', id="var-braced"),
    pytest.param("rm ~/x", id="tilde"),
    pytest.param("rm <S>/a*/../../x", id="glob-dotdot"),
    pytest.param("mv <O>/f <S>/f", id="mv-src-outside"),
    pytest.param("mv <S>/a1 <O>/a1", id="mv-dst-outside"),
    pytest.param("rsync -a --delete host:<S>/a/ <S>/b/", id="rsync-remote"),
]


@pytest.mark.parametrize("cmd", ALLOWED)
def test_allowed(cmd, tree):
    verdict = _verdict(cmd, tree)
    assert verdict.allowed, verdict.reason


@pytest.mark.parametrize("cmd", REFUSED)
def test_refused(cmd, tree):
    assert not _verdict(cmd, tree).allowed


def test_relative_operand_follows_cwd(tree):
    sc, other = tree
    assert _verdict("rm x", tree, cwd=sc).allowed
    assert not _verdict("rm x", tree, cwd=other).allowed


def test_cd_makes_relative_unprovable(tree):
    assert not _verdict("cd <S> && rm x", tree).allowed


@pytest.mark.parametrize("cmd", [
    "rm -rf <S>/x", "mv <S>/a1 <S>/b", "find <S>/sub -delete", "rmdir <S>/x",
    "rsync -a --delete <S>/a/ <S>/b/",
])
def test_no_scratch_refuses_every_destructive_form(cmd, tree):
    verdict = _verdict(cmd, tree, scratch=False)
    assert not verdict.allowed
    assert "no scratch known" in verdict.reason


def test_xargs_idiom_with_no_scratch(tree):
    verdict = _verdict("find <O> -print0 | xargs -0 rm -rf", tree, scratch=False)
    assert not verdict.allowed


def test_read_only_allowed_without_scratch(tree):
    assert _verdict("ls -la", tree, scratch=False).allowed


def test_inside_is_strict(tree):
    sc, other = tree
    assert _inside(sc + "/a1", sc, sc)
    assert not _inside(sc, sc, sc)
    assert not _inside(sc + "/link/x", sc, sc)
    assert not _inside("x", sc, None)
    assert _inside("x", sc, sc)
