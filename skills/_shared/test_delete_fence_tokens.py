"""The fence's delete-token grammar (design delete-fence-own-tree 2.1).

Two rules, both about words that only *look* like deletes:

  * `worktree` is a delete token only as `worktree remove`. A bare `worktree`
    word (a `git worktree list`, a commit message about the worktree reaper) is
    not one, so the fence-mode word set and the hook's prefilter ignore it.
  * In fence mode the expansion pre-check ignores text inside single quotes:
    single-quoted text is data, never expanded, so a backtick or a `$(` written
    inside `'…'` cannot pair with a delete word. A double-quoted `$(` or
    backtick still expands, so it still denies. Reviewer mode is unchanged:
    its word set is the wider one and it strips nothing.

Commands are only classified, and every hook test answers git with a counting
stub, so nothing here deletes anything.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures"))
from delete_fence_repo import build  # noqa: E402

import delete_fence_hook as hook  # noqa: E402
from delete_fence_verbs import DELETE_WORD  # noqa: E402
from reviewer_delete_guard import classify  # noqa: E402

SID = "sess-1"


@pytest.fixture
def tree(tmp_path):
    root, out = tmp_path / "root", tmp_path / "out"
    (root / "w").mkdir(parents=True)
    out.mkdir()
    return str(root), str(out)


def _sub(tree, text):
    root, out = tree
    return text.replace("<R>", root).replace("<O>", out)


def _v(cmd, tree, mode="fence"):
    return classify(_sub(tree, cmd), scratch=[_sub(tree, "<R>")],
                    cwd=_sub(tree, "<R>"), mode=mode)


FENCE_ALLOWED = [
    "git worktree list",
    "git worktree list --porcelain",
    "git worktree remove <R>/w",
    "git commit -m 'docs(worktree-fleet): note the worktree reaper'",
    "git commit -m 'fix `rm` handling'",
    'git log --oneline -n 3 "$(git merge-base HEAD main)"',
    # A real expansion next to single-quoted delete text: the quoted half is data.
    'echo "$(cat <R>/f)" && git commit -m \'rm -rf /home/x\'',
]
FENCE_DENIED = [
    'echo "$(rm -rf /home/x)"',
    "`rm -rf /home/x`",
    'git commit -m "fix `rm` handling"',
    "git worktree remove /elsewhere/w",
    "git worktree remove <O>/w",
    "rm -rf /home/x",
]


@pytest.mark.parametrize("cmd", FENCE_ALLOWED)
def test_fence_allows_a_word_that_is_not_a_delete(cmd, tree):
    verdict = _v(cmd, tree)
    assert verdict.allowed, verdict.reason


@pytest.mark.parametrize("cmd", FENCE_DENIED)
def test_fence_still_denies_a_real_delete(cmd, tree):
    verdict = _v(cmd, tree)
    assert not verdict.allowed, verdict.reason


def test_fence_denied_reason_is_the_expansion_precheck(tree):
    verdict = _v('echo "$(rm -rf /home/x)"', tree)
    assert "expansion" in verdict.reason and "destructive word" in verdict.reason


def test_reviewer_mode_strips_nothing(tree):
    # Reviewer mode keeps the wider word set and strips no quoted spans.
    assert not _v('echo "$(cat <R>/f)" && git commit -m \'rm -rf /home/x\'',
                  tree, mode="reviewer").allowed
    assert not _v("git worktree remove <R>/w", tree, mode="reviewer").allowed


def test_worktree_is_a_token_only_as_worktree_remove():
    for cmd in ("git worktree remove /x/w", "git  worktree\tremove /x/w", "worktree remove"):
        assert DELETE_WORD.search(cmd), cmd
    for cmd in ("git worktree list", "worktree reaper", "worktree-fleet",
                "docs(worktree-fleet): note the worktree reaper", "git worktree"):
        assert not DELETE_WORD.search(cmd), cmd


# --- the hook's prefilter and the token list --------------------------------


class GitStub:
    """Answers the two calls the fence is allowed to make, and counts them."""

    def __init__(self, top, branch="tp/a", worktrees=()):
        common = os.path.join(top, ".git")
        self.top, self.git_dir = top, common
        self.common_dir, self.branch = common, branch
        self.worktrees = list(worktrees)
        self.calls = []

    def __call__(self, args, cwd):
        self.calls.append(list(args))
        if args[:1] == ["rev-parse"]:
            return "%s\n%s\n%s\n%s\n" % (self.top, self.git_dir, self.common_dir, self.branch)
        if args[:2] == ["worktree", "list"]:
            return "".join("worktree %s\nHEAD 1\n\n" % p for p in self.worktrees)
        raise AssertionError("unexpected git call: %r" % (args,))

    def count(self, *prefix):
        return sum(1 for c in self.calls if c[:len(prefix)] == list(prefix))


@pytest.fixture(scope="module")
def repo(tmp_path_factory):
    return {k: os.path.realpath(v)
            for k, v in build(tmp_path_factory.mktemp("fence-tokens")).items()}


def _stub(repo):
    return GitStub(repo["a"], worktrees=[repo[k] for k in ("repo", "a", "b")])


def _env(repo):
    outside = os.path.dirname(repo["repo"])
    return {"TP_DESIGN_RUN": "1", "CLAUDE_PROJECT_DIR": repo["a"], "HOME": outside,
            "TMPDIR": outside, "TP_FENCE_PAD_BASE": os.path.join(outside, "no-such-pad")}


def _fence(command, repo, git=None):
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": repo["a"],
               "session_id": SID, "transcript_path": "/nonexistent/projects/p/s.jsonl"}
    return hook.run(payload, env=_env(repo), git=_stub(repo) if git is None else git)


def _denied(out):
    return bool(out) and json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "deny"


@pytest.mark.parametrize("command", [
    'git commit -m "docs(worktree-fleet): x"',
    "git commit -m 'docs(worktree-fleet): note the worktree reaper'",
    "git worktree list",
])
def test_prefilter_lets_a_non_delete_worktree_word_through_without_git(command, repo):
    git = _stub(repo)
    assert _fence(command, repo, git=git) == ("", 0)
    assert git.calls == []


def test_worktree_remove_of_a_sibling_is_still_parsed_and_denied(repo):
    git = _stub(repo)
    out, code = _fence("git worktree remove %s" % repo["b"], repo, git=git)
    assert code == 0 and _denied(out)
    assert git.count("rev-parse") == 1 and git.count("worktree", "list") == 1


# tp-allow-fragile: the design pins the two closed token lists against each other (task 2.1 Red)
def test_raw_token_spells_the_same_alternatives_as_tokens():
    assert hook._RAW_TOKEN.pattern == hook.TOKENS.pattern
