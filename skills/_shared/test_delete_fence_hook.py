"""test_delete_fence_hook.py — the delete fence's PreToolUse hook (design delete-fence-own-tree 1.8).

`run(payload, *, env=None, git=None) -> (stdout, exit_code)` wires the four
modules: the delete-token prefilter, activation, the root set and the shell
classifier in `mode="fence"` (plus the inline-Python bodies). The fixture
(`fixtures/delete_fence_repo.py`) builds a real repo with linked worktrees
`repo-wt/a` and `repo-wt/b`; every git call is answered by a counting stub and
no test deletes anything or touches a real worktree of this checkout.
"""
from __future__ import annotations

import io
import json
import os
import sys

import pytest

import delete_fence_roots
import reviewer_delete_guard

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures"))
from delete_fence_repo import build  # noqa: E402

import delete_fence_hook as hook  # noqa: E402

SID = "sess-1"
PY_C = 'python3 -c "import shutil; shutil.rmtree(\'/home/x\')"'
PY_HD = "python3 - <<'EOF'\nimport shutil\nshutil.rmtree('/home/x')\nEOF"
UNMODELLED = ["uncrackable-tool $(mv a b)", "uncrackable-tool $(rsync --delete a b)",
              "uncrackable-tool $(find . -exec rm {} +)", "rm -rf $(cmd)"]


class GitStub:
    """Answers the two calls the fence is allowed to make, and counts them."""

    def __init__(self, top, git_dir, common_dir, branch, worktrees=()):
        self.top, self.git_dir = top, git_dir
        self.common_dir, self.branch = common_dir, branch
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
    """One real fixture repo for the module, as real paths."""
    return {k: os.path.realpath(v)
            for k, v in build(tmp_path_factory.mktemp("fence-hook")).items()}


def _stub(repo, top="a", branch="tp/a", linked=True):
    common = os.path.join(repo["repo"], ".git")
    return GitStub(repo[top], os.path.join(repo[top], ".git") if linked else common,
                   common, branch, [repo[k] for k in ("repo", "a", "b")])


def _env(repo, top="a", **extra):
    """The hook process's own environment for a design run in `repo-wt/a`."""
    outside = os.path.dirname(repo["repo"])
    env = {"TP_DESIGN_RUN": "1", "CLAUDE_PROJECT_DIR": repo[top], "HOME": outside,
           "TMPDIR": outside, "TP_FENCE_PAD_BASE": os.path.join(outside, "no-such-pad")}
    env.update(extra)
    return env


def _payload(command, cwd, agent=None, **extra):
    p = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": cwd,
         "session_id": SID, "transcript_path": "/nonexistent/projects/p/s.jsonl"}
    if agent:
        p["agent_type"] = agent
        p["agent_id"] = "a1"
    p.update(extra)
    return p


def _fence(command, repo, top="a", agent=None, env=None, git=None):
    return hook.run(_payload(command, repo[top], agent=agent),
                    env=_env(repo) if env is None else env,
                    git=_stub(repo, top=top) if git is None else git)


def _reason(out):
    d = json.loads(out)["hookSpecificOutput"]
    assert d["permissionDecision"] == "deny" and d["hookEventName"] == "PreToolUse"
    return d["permissionDecisionReason"]


def _denied(out):
    return bool(out) and json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_denies_a_sibling_design_worktree(repo):
    out, code = _fence("rm -rf %s/x" % repo["b"], repo)
    assert code == 0 and _denied(out)
    reason = _reason(out)
    assert "delete-fence" in reason and repo["a"] in reason
    # The seat owns teardown of other trees. A paid skill name cannot appear in a
    # core-shipped file (the release.sh leak guard scans every shipped file), so
    # the reason names the seat's teardown path in git terms instead:
    # `/tp-post-merge`, `git worktree remove`, gc.
    assert "/tp-post-merge" in reason and "worktree remove" in reason and "gc" in reason
    assert "seat" in reason


def test_denies_home(repo):
    assert _denied(_fence("rm -rf $HOME/x", repo)[0])


@pytest.mark.parametrize("command", [PY_C, PY_HD])
def test_denies_inline_python_delete(command, repo):
    out = _fence(command, repo)[0]
    assert _denied(out) and "shutil.rmtree" in _reason(out)


@pytest.mark.parametrize("command", ["rm -rf <a>/build", "rm -rf .tp-scratch/x"])
def test_allows_inside_the_run_own_tree(command, repo):
    assert _fence(command.replace("<a>", repo["a"]), repo) == ("", 0)


@pytest.mark.parametrize("command", ["ls", "pytest -x", "git status", "echo hi"])
def test_allows_benign_commands(command, repo):
    assert _fence(command, repo) == ("", 0)


@pytest.mark.parametrize("agent", [None, "general-purpose", "three-pillars:tp-worker",
                                   "three-pillars:tp-finalizer", "tp-review-confirmer"])
def test_applies_to_every_agent_type_and_to_none(agent, repo):
    assert _denied(_fence("rm -rf %s/x" % repo["b"], repo, agent=agent)[0])


def test_prefilter_never_calls_git_for_ls(repo):
    git = _stub(repo)
    assert _fence("ls", repo, git=git) == ("", 0)
    assert git.calls == []


def test_at_most_one_rev_parse_and_one_worktree_list(repo):
    git = _stub(repo)
    assert _denied(_fence("rm -rf %s/x" % repo["b"], repo, git=git)[0])
    assert git.count("rev-parse") == 1 and git.count("worktree", "list") == 1


@pytest.mark.parametrize("command", UNMODELLED)
def test_denies_an_unmodelled_command_holding_a_delete_token(command, repo):
    assert _denied(_fence(command, repo)[0])


def test_fail_mode_when_roots_raise(monkeypatch, repo):
    def boom(*a, **k):
        raise RuntimeError("roots lookup failed")
    monkeypatch.setattr(delete_fence_roots, "compute_roots", boom)
    assert _denied(_fence("rm -rf x", repo)[0])
    assert _fence("echo hi", repo) == ("", 0)


def test_fail_mode_when_classifier_raises(monkeypatch, repo):
    def boom(*a, **k):
        raise RuntimeError("classifier failed")
    monkeypatch.setattr(reviewer_delete_guard, "classify", boom)
    assert _denied(_fence("rm -rf x", repo)[0])
    assert _fence("echo hi", repo) == ("", 0)


def test_off_switch_in_the_hook_env_allows(repo):
    assert _fence("rm -rf /home/x", repo, env=_env(repo, TP_DELETE_FENCE="off")) == ("", 0)


def test_inline_off_assignment_does_not_disable_the_fence(repo):
    assert _denied(_fence("TP_DELETE_FENCE=off rm -rf /home/x", repo)[0])


def test_non_tp_repo_allows_silently(tmp_path):
    """A repo with no tp marker and no `TP_DESIGN_RUN`: allowed, and no roots built."""
    here = str(tmp_path)
    git = GitStub(here, os.path.join(here, ".git"), os.path.join(here, ".git"), "master")
    payload = _payload("rm -rf /home/x", here)
    out, code = hook.run(payload, env={"HOME": here}, git=git)
    assert (out, code) == ("", 0)
    assert git.count("worktree", "list") == 0


def test_non_bash_tool_allows(repo):
    git = _stub(repo)
    payload = _payload("rm -rf %s/x" % repo["b"], repo["a"], tool_name="Read")
    assert hook.run(payload, env=_env(repo), git=git) == ("", 0)
    assert git.calls == []


def _main(monkeypatch, capsys, raw):
    monkeypatch.setattr(sys, "stdin", io.StringIO(raw))
    with pytest.raises(SystemExit) as exc:
        hook.main()
    return capsys.readouterr().out, exc.value.code


def _raw(command):
    return json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})


def test_main_prints_the_verdict_and_exits_zero(monkeypatch, capsys):
    monkeypatch.setattr(hook, "run", lambda payload: ("sentinel", 0))
    assert _main(monkeypatch, capsys, _raw("rm -rf /home/x")) == ("sentinel\n", 0)


def test_main_crash_denies_only_when_the_text_holds_a_delete_token(monkeypatch, capsys):
    def boom(payload):
        raise RuntimeError("hook crashed")
    monkeypatch.setattr(hook, "run", boom)
    out, code = _main(monkeypatch, capsys, _raw("rm -rf /home/x"))
    assert code == 0 and _denied(out) and "crashed" in _reason(out)
    assert _main(monkeypatch, capsys, _raw("echo hi")) == ("", 0)
