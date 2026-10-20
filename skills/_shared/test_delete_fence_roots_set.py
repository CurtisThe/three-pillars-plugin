"""The root set for the delete fence (design delete-fence-own-tree 1.7).

`compute_roots(kind, info, payload_cwd, env, git, scratch, session_id, uid)` is
pure over the injected `git` and `env`. The fixture (`fixtures/delete_fence_repo.py`)
builds a real repo with linked worktrees `repo-wt/a` and `repo-wt/b` under
`tmp_path`; `git` here is a counting stub that returns `worktree list --porcelain`
text, so nothing shells out and nothing is ever deleted. The harness pad
(`claude-<uid>/<project>/<session>` under the temp dir) is rebuilt under
`tmp_path` through the `TP_FENCE_PAD_BASE` override, so no test touches the
real temp dir.
"""
import os
import sys

import pytest

from delete_fence_roots import compute_roots

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "fixtures"))
from delete_fence_repo import build  # noqa: E402

UID = 1000
SID = "sess-1"
PORCELAIN = ["worktree", "list", "--porcelain"]


class _Git:
    """Counts calls; answers every one with a porcelain block for `paths`."""

    def __init__(self, paths=()):
        self.paths = list(paths)
        self.calls = []

    def __call__(self, args, cwd):
        self.calls.append(list(args))
        return "".join("worktree %s\nHEAD 0000\nbranch refs/heads/x\n\n" % p
                       for p in self.paths)


def _info(top):
    return {"top": str(top), "git_dir": str(top) + "/.git",
            "common_dir": str(top) + "/.git", "branch": "tp/a"}


def _roots(kind, top, git, cwd=None, env=None, scratch=None, sid=None):
    return compute_roots(kind, _info(top), str(cwd or top), env or {}, git,
                         scratch, sid, UID)


@pytest.fixture
def repo(tmp_path):
    return {k: os.path.realpath(v) for k, v in build(tmp_path).items()}


def _agent_tree(main):
    """A subagent's own tree: a dir with a `.git` file, under the seat's repo."""
    agent = os.path.join(main, ".claude", "worktrees", "agent-1")
    os.makedirs(os.path.join(agent, "sub"))
    with open(os.path.join(agent, ".git"), "w") as fh:
        fh.write("gitdir: elsewhere\n")
    return agent


@pytest.mark.parametrize("registered", [True, False])
def test_design_run_roots(repo, registered):
    a, b, main = repo["a"], repo["b"], repo["repo"]
    w1 = os.path.join(a, ".tp-scratch", "w1")
    w2 = os.path.join(a, ".claude", "worktrees", "w2")
    agent = _agent_tree(main)
    listed = [main, a, b, w1, w2] + ([agent] if registered else [])
    got = _roots("design-run", a, _Git(listed), cwd=os.path.join(agent, "sub"))
    assert set(got) == {a, agent, w1, w2}
    assert b not in got and main not in got


def test_design_run_never_gets_a_sibling_design_through_the_cwd(repo):
    a, b, main = repo["a"], repo["b"], repo["repo"]
    got = _roots("design-run", a, _Git([main, a, b]), cwd=b)
    assert set(got) == {a}


def test_design_run_cwd_inside_its_own_tree_adds_nothing(repo):
    a, b, main = repo["a"], repo["b"], repo["repo"]
    os.makedirs(os.path.join(a, "sub"))
    got = _roots("design-run", a, _Git([main, a, b]), cwd=os.path.join(a, "sub"))
    assert got == [a]


def test_seat_roots_are_the_checkout_and_every_worktree(repo):
    a, b, main = repo["a"], repo["b"], repo["repo"]
    got = _roots("seat", main, _Git([main, a, b]), cwd=b)
    assert set(got) == {main, a, b}
    assert len(got) == 3


@pytest.mark.parametrize("kind", ["design-run", "seat"])
def test_git_is_called_once_for_the_worktree_list(repo, kind):
    git = _Git([repo["repo"], repo["a"], repo["b"]])
    _roots(kind, repo["a"] if kind == "design-run" else repo["repo"], git)
    assert git.calls == [PORCELAIN]


@pytest.mark.parametrize("kind", ["design-run", "seat"])
def test_scratch_is_a_root_when_given(repo, tmp_path, kind):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    top = repo["a"] if kind == "design-run" else repo["repo"]
    assert os.path.realpath(scratch) in _roots(kind, top, _Git([top]),
                                               scratch=str(scratch))
    assert os.path.realpath(scratch) not in _roots(kind, top, _Git([top]))


def _pad(tmp_path):
    base = tmp_path / "claude-1000"
    mine = base / "proj" / SID
    other = base / "proj" / "other-session"
    mine.mkdir(parents=True)
    other.mkdir(parents=True)
    return base, mine, other, {"TP_FENCE_PAD_BASE": str(base)}


@pytest.mark.parametrize("kind", ["design-run", "seat"])
def test_session_pad_is_a_root_only_for_this_session(repo, tmp_path, kind):
    base, mine, other, env = _pad(tmp_path)
    top = repo["a"] if kind == "design-run" else repo["repo"]
    got = _roots(kind, top, _Git([top]), env=env, sid=SID)
    assert os.path.realpath(mine) in got
    for nope in (other, base, base / "proj"):
        assert os.path.realpath(nope) not in got


def test_no_session_id_means_no_pad_root(repo, tmp_path):
    _, mine, _, env = _pad(tmp_path)
    got = _roots("seat", repo["repo"], _Git([repo["repo"]]), env=env, sid=None)
    assert got == [repo["repo"]]


@pytest.mark.parametrize("sid", ["../stray", "proj/" + SID, "..", ""])
def test_session_id_cannot_climb_out_of_the_pad(repo, tmp_path, sid):
    base, _, _, env = _pad(tmp_path)
    (base / "stray").mkdir()
    got = _roots("seat", repo["repo"], _Git([repo["repo"]]), env=env, sid=sid)
    assert got == [repo["repo"]]


def test_a_symlinked_pad_is_not_followed(repo, tmp_path):
    base, _, _, env = _pad(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    os.symlink(elsewhere, base / "proj" / "linked")
    got = _roots("seat", repo["repo"], _Git([repo["repo"]]), env=env,
                 sid="linked")
    assert os.path.realpath(elsewhere) not in got
    assert got == [repo["repo"]]


def test_never_roots_are_dropped_whatever_the_source(repo, tmp_path):
    main = repo["repo"]
    home, tmpdir = tmp_path / "home", tmp_path / "tmpdir"
    env = {"HOME": str(home), "TMPDIR": str(tmpdir)}
    never = [os.sep, os.sep + "tmp", home, tmpdir, tmp_path,
             tmp_path / "pytest-of-bob", tmp_path / "claude-1000"]
    for path in never:
        path = str(path)
        got = _roots("seat", main, _Git([main, path]), env=env, scratch=path)
        assert got == [main], path


def test_a_tree_under_home_is_still_a_root(tmp_path):
    home = tmp_path / "home"
    top = home / "proj"
    top.mkdir(parents=True)
    got = _roots("seat", top, _Git([top]), env={"HOME": str(home)})
    assert got == [os.path.realpath(top)]


def test_roots_are_real_paths(repo, tmp_path):
    real = tmp_path / "real-scratch"
    real.mkdir()
    link = tmp_path / "link-scratch"
    os.symlink(real, link)
    got = _roots("seat", repo["repo"], _Git([repo["repo"]]), scratch=str(link))
    assert os.path.realpath(real) in got
    assert str(link) not in got


def test_a_worktree_listed_twice_is_one_root(repo):
    main = repo["repo"]
    got = _roots("seat", main, _Git([main, main, repo["a"]]))
    assert sorted(got) == sorted({main, repo["a"]})
