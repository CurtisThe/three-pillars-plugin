"""Tests for portable_path — the host-path → committed-artifact form."""
from pathlib import Path

import pytest

import portable_path as pp
from portable_path import OUTSIDE_MARKER, find_anchor, is_abs_path_str, portable_path


def _repo(tmp_path: Path, git_file: bool = False) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    if git_file:
        (repo / ".git").write_text("gitdir: /elsewhere/.git/worktrees/repo\n", encoding="utf-8")
    else:
        (repo / ".git").mkdir()
    return repo


def test_find_anchor_walks_up_to_git_dir(tmp_path):
    repo = _repo(tmp_path)
    deep = repo / "three-pillars-docs" / "tp-designs" / "x"
    deep.mkdir(parents=True)
    assert find_anchor(deep) == repo.resolve()
    assert find_anchor(repo) == repo.resolve()


def test_find_anchor_accepts_worktree_git_file(tmp_path):
    repo = _repo(tmp_path, git_file=True)
    assert find_anchor(repo / "a" / "b") == repo.resolve()


def test_find_anchor_none_when_no_git_anywhere(tmp_path, monkeypatch):
    lone = tmp_path / "lone"
    lone.mkdir()
    monkeypatch.setattr(pp.Path, "exists", lambda self: False)
    assert find_anchor(lone) is None
    assert portable_path(lone / "agent-x", find_anchor(lone)) == f"{OUTSIDE_MARKER}:agent-x"


def test_find_anchor_resolve_error_is_none(tmp_path, monkeypatch):
    def boom(self, strict=False):
        raise RuntimeError("symlink loop")

    monkeypatch.setattr(pp.Path, "resolve", boom)
    assert find_anchor(tmp_path) is None


def test_inside_anchor_is_posix_relative(tmp_path):
    repo = _repo(tmp_path)
    wt = repo / ".claude" / "worktrees" / "agent-x"
    assert portable_path(wt, repo) == ".claude/worktrees/agent-x"
    assert portable_path(str(wt), repo) == ".claude/worktrees/agent-x"


def test_outside_anchor_is_basename_marker(tmp_path):
    repo = _repo(tmp_path)
    other = tmp_path / "elsewhere" / "agent-x"
    assert portable_path(other, repo) == f"{OUTSIDE_MARKER}:agent-x"


def test_no_anchor_is_marker(tmp_path):
    assert portable_path(tmp_path / "agent-x", None) == f"{OUTSIDE_MARKER}:agent-x"


def test_symlinked_anchor_still_matches(tmp_path):
    repo = _repo(tmp_path)
    link = tmp_path / "link"
    link.symlink_to(repo)
    wt = repo / ".claude" / "worktrees" / "agent-x"
    assert portable_path(wt, link) == ".claude/worktrees/agent-x"
    assert portable_path(link / ".claude" / "worktrees" / "agent-x", repo) == (
        ".claude/worktrees/agent-x"
    )


def test_resolve_error_falls_back_to_marker(tmp_path, monkeypatch):
    repo = _repo(tmp_path)

    def boom(self, strict=False):
        raise RuntimeError("symlink loop")

    monkeypatch.setattr(pp.Path, "resolve", boom)
    assert portable_path(repo / "agent-x", repo) == f"{OUTSIDE_MARKER}:agent-x"


def test_marker_never_discloses_parent_tree(tmp_path):
    out = portable_path(tmp_path / "secret" / "agent-x", None)
    assert str(tmp_path) not in out
    assert not Path(out).is_absolute()


@pytest.mark.parametrize(
    "value, expected",
    [("/abs/path", True), ("rel/path", False), ("", False), (None, False),
     (3, False), (["/abs"], False), ("agent-abc", False)],
)
def test_is_abs_path_str(value, expected):
    assert is_abs_path_str(value) is expected


def test_path_equal_to_anchor_keeps_basename_marker(tmp_path):
    repo = _repo(tmp_path)
    assert portable_path(repo, repo) == f"{OUTSIDE_MARKER}:repo"


@pytest.mark.parametrize("bad", [None, 42, b"/abs/bytes"])
def test_non_path_input_never_raises(bad):
    out = portable_path(bad, None)
    assert out.startswith(f"{OUTSIDE_MARKER}:")
    assert portable_path(bad, "/some/anchor").startswith(f"{OUTSIDE_MARKER}:")


def test_marker_is_markdown_safe(tmp_path):
    # decisions.md is rendered as markdown: a <tag>-like marker would vanish.
    out = portable_path(tmp_path / "agent-x", None)
    assert "<" not in out and ">" not in out


@pytest.mark.parametrize("degenerate", ["/", "/srv/x/.."])
def test_degenerate_name_gets_unknown(degenerate):
    assert portable_path(degenerate, None) == f"{OUTSIDE_MARKER}:unknown"
