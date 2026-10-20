"""A quoted `$(cat <<'EOF' … EOF)` message argument is data (design delete-fence-own-tree 2.2).

The commit-message and PR-body idiom is `git commit -m "$(cat <<'EOF' … EOF)"`.
A *quoted* heredoc is never expanded and never runs, so the words inside it are
prose: a message that says "remove old files, rm -rf notes" is not a delete. The
fence rewrites each such heredoc to a placeholder word (the helper the kill
guard already uses, `kill_guard_hook._data_heredocs`) before classifying, and
runs its prefilter on the same rewritten text — so a message that only
*mentions* a delete verb never parses, never calls git, and never denies.

Three shapes must keep denying:

  * `bash -c "$(cat <<'EOF' … EOF)"` — the substitution is an argument of a
    shell, so the body could run as code: the helper answers `None` and the
    original text is classified (no rewrite, no allow);
  * a message followed by a real delete (`… EOF)" && rm -rf /home/x`) — the
    rewrite leaves the second segment, so the delete is still judged;
  * a plain `rm -rf /home/x` outside the roots.

Every command here is only classified and the git seam is a stub, so nothing
deletes anything and no real worktree is touched.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures"))
from delete_fence_repo import build  # noqa: E402

import delete_fence_hook as hook  # noqa: E402

SID = "sess-1"

# The message bodies name delete verbs as prose. `<B>` is the sibling design's
# worktree — outside this run's roots, so a real delete there would deny.
MSG_COMMIT = ('git commit -m "$(cat <<\'EOF\'\n'
              'docs: remove old files, rm -rf notes, clean up the worktree\n'
              'EOF\n)"')
MSG_BODY = ('gh pr create --title t --body "$(cat <<\'EOF\'\n'
            'mv a b; git worktree remove x\n'
            'EOF\n)"')
MSG_OUTSIDE = ('git commit -m "$(cat <<\'EOF\'\n'
               'teardown: rm -rf <B>\n'
               'EOF\n)"')
CODE_HEREDOC = 'bash -c "$(cat <<\'EOF\'\nrm -rf /home/x\nEOF\n)"'
MSG_THEN_DELETE = 'git commit -m "$(cat <<\'EOF\'\nok\nEOF\n)" && rm -rf /home/x'
MSG_THEN_DELETE_TREE = ('gh pr create --body "$(cat <<\'EOF\'\nok\nEOF\n)"'
                        ' && git worktree remove <B>')
PLAIN_DELETE = "rm -rf /home/x"


@pytest.fixture(scope="module")
def repo(tmp_path_factory):
    return {k: os.path.realpath(v)
            for k, v in build(tmp_path_factory.mktemp("fence-heredoc")).items()}


def _sub(repo, text):
    return text.replace("<B>", repo["b"])


class GitStub:
    """Answers the two calls the fence is allowed to make, and counts them."""

    def __init__(self, top, worktrees=()):
        common = os.path.join(top, ".git")
        self.top, self.git_dir = top, common
        self.common_dir, self.branch = common, "tp/a"
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


def _env(repo):
    outside = os.path.dirname(repo["repo"])
    return {"TP_DESIGN_RUN": "1", "CLAUDE_PROJECT_DIR": repo["a"], "HOME": outside,
            "TMPDIR": outside, "TP_FENCE_PAD_BASE": os.path.join(outside, "no-such-pad")}


def _fence(command, repo, git=None):
    payload = {"tool_name": "Bash", "tool_input": {"command": _sub(repo, command)},
               "cwd": repo["a"], "session_id": SID,
               "transcript_path": "/nonexistent/projects/p/s.jsonl"}
    if git is None:
        git = GitStub(repo["a"], worktrees=[repo[k] for k in ("repo", "a", "b")])
    out, code = hook.run(payload, env=_env(repo), git=git)
    return out, code, git


def _reason(out):
    return json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"]


# --- allowed: the message is data ------------------------------------------


@pytest.mark.parametrize("command", [MSG_COMMIT, MSG_BODY, MSG_OUTSIDE])
def test_a_quoted_message_heredoc_is_data(command, repo):
    """Empty stdout: the fence never sees the message's delete words."""
    out, code, _ = _fence(command, repo)
    assert (out, code) == ("", 0), _reason(out) if out else ""


@pytest.mark.parametrize("command", [MSG_COMMIT, MSG_BODY, MSG_OUTSIDE])
def test_the_prefilter_reads_the_rewritten_text(command, repo):
    """A message that only mentions delete words never parses and never calls git."""
    out, code, git = _fence(command, repo)
    assert (out, code) == ("", 0), _reason(out) if out else ""
    assert git.calls == []


# --- still denied ----------------------------------------------------------


def test_a_heredoc_that_could_run_as_code_is_denied(repo):
    out, code, git = _fence(CODE_HEREDOC, repo)
    assert code == 0 and out and "delete-fence: refused" in _reason(out)
    assert git.calls  # not skipped by the prefilter: the body could run as code


@pytest.mark.parametrize("command", [MSG_THEN_DELETE, MSG_THEN_DELETE_TREE])
def test_a_real_delete_after_the_message_is_denied(command, repo):
    out, code, _ = _fence(command, repo)
    assert code == 0 and out
    reason = _reason(out)
    assert "delete-fence: refused" in reason and "outside scratch" in reason


def test_a_plain_delete_is_denied(repo):
    out, code, _ = _fence(PLAIN_DELETE, repo)
    assert code == 0 and out
    assert "outside scratch" in _reason(out)
