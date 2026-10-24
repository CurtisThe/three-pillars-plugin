"""test_create_fence_hook.py - the create fence's PreToolUse hook (design run-scratch-in-fence 1.5).

`run(payload, *, env=None, git=None) -> (stdout, exit_code)` denies a Write, Edit,
NotebookEdit or Bash create whose literal target is outside the fence roots, the
run's TMPDIR, the /dev stream files and the config dir's `projects/*/memory/`.
Everything runs against a throwaway repo under `tmp_path` (fixtures/delete_fence_repo.py);
the hook only reads, and no test creates the paths it judges. Assertions are on the
decision and the roots named in the refusal, never on prose (test-fragility.md).
The helpers below are shared with test_create_fence_escapes.py and
test_create_fence_registration.py.
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys

import pytest

import create_fence_targets
import run_scratch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures"))
from delete_fence_repo import build  # noqa: E402

import create_fence_hook as hook  # noqa: E402

TMP = os.path.join(os.sep, "tmp")
FILE_TOOLS = (("Write", "file_path"), ("Edit", "file_path"), ("NotebookEdit", "notebook_path"))


def make_repo(tmp_path):
    """Fixture repo + run dir, a home with an outside dir, links, a nested worker tree."""
    repo = {k: os.path.realpath(v) for k, v in build(tmp_path).items()}
    run = os.path.join(repo["a"], ".tp-scratch", "run")
    os.makedirs(run)
    home = os.path.join(os.path.dirname(repo["repo"]), "home")
    config = os.path.join(home, ".claude")
    os.makedirs(os.path.join(config, "projects", "p", "memory"))
    os.makedirs(os.path.join(home, "outside"))
    os.symlink(os.path.join(home, "outside"), os.path.join(run, "out-link"))
    os.symlink(os.path.join(home, "outside", "f"), os.path.join(run, "dangling"))
    attempt = os.path.join(repo["a"], ".tp-scratch", "tp-attempt-x")
    subprocess.run(["git", "-C", repo["a"], "worktree", "add", "-q", "--detach", attempt],
                   check=True, capture_output=True)
    repo.update(run=run, home=os.path.realpath(home), config=os.path.realpath(config),
                attempt=os.path.realpath(attempt))
    return repo


def make_env(repo, top="a", **extra):
    """The hook process's own env for a design run; a None value drops the key."""
    env = {"TP_DESIGN_RUN": "1", "CLAUDE_PROJECT_DIR": repo[top], "HOME": repo["home"],
           "TMPDIR": repo["run"], "CLAUDE_CONFIG_DIR": repo["config"],
           "TP_FENCE_PAD_BASE": os.path.join(repo["home"], "no-such-pad")}
    env.update(extra)
    return {k: v for k, v in env.items() if v is not None}


def fence(repo, tool, *, env=None, cwd=None, git=None, **tool_input):
    payload = {"tool_name": tool, "tool_input": tool_input, "cwd": cwd or repo["a"],
               "session_id": "sess-cf", "transcript_path": "/nonexistent/projects/p/s.jsonl"}
    return hook.run(payload, env=make_env(repo) if env is None else env, git=git)


def bash(repo, command, **kw):
    return fence(repo, "Bash", command=command, **kw)


def denial(out):
    """The refusal reason when `out` is a deny, else None."""
    if not out:
        return None
    spec = json.loads(out)["hookSpecificOutput"]
    assert spec["hookEventName"] == "PreToolUse"
    return spec["permissionDecisionReason"] if spec["permissionDecision"] == "deny" else None


@pytest.fixture(scope="module")
def repo(tmp_path_factory):
    return make_repo(tmp_path_factory.mktemp("create-fence-hook"))


def _field(tool):
    return dict(FILE_TOOLS)[tool]


@pytest.mark.parametrize("tool", [t for t, _ in FILE_TOOLS])
def test_a_file_tool_create_inside_a_root_or_an_allowed_sink_is_allowed(tool, repo):
    inside = [os.path.join(repo["a"], "src", "new.py"), os.path.join(repo["run"], "t", "f"),
              "/dev/null", os.path.join(repo["config"], "projects", "p", "memory", "m.md")]
    for path in inside:
        out, code = fence(repo, tool, **{_field(tool): path})
        assert (out, code) == ("", 0), "%s %s should be allowed" % (tool, path)


@pytest.mark.parametrize("tool", [t for t, _ in FILE_TOOLS])
def test_a_file_tool_create_outside_every_root_is_denied_with_the_roots_listed(tool, repo):
    outside = [os.path.join(repo["home"], ".cache_tel11.json"),
               os.path.join(repo["home"], "tmp", "x"), os.path.join(TMP, "x"),
               os.path.join(repo["home"], "t", "slot8-x", "f"),
               os.path.join(repo["config"], "projects", "p", "notes.md")]
    for path in outside:
        out, code = fence(repo, tool, **{_field(tool): path})
        reason = denial(out)
        assert code == 0 and reason, "%s %s should be denied" % (tool, path)
        assert repo["a"] in reason and repo["run"] in reason, reason


def test_a_relative_file_tool_path_resolves_against_the_payload_cwd(repo):
    assert fence(repo, "Write", file_path="src/new.py") == ("", 0)
    out, _ = fence(repo, "Write", file_path="../../outside.txt")
    assert denial(out)


TEMPLATES = [
    "mkdir {b}/tmp",
    "touch {b}/x",
    "echo hi > {b}/.cache_tel11.json",
    "mkdir -p {b}/t/slot8-x {b}/t/pc2-chk {b}/t/impl-audit-pria",
    "tar -xf a.tar -C {b}/y",
    "git clone u {b}/z",
    "cd {b} && touch x",
    "TMPDIR={b}/t pytest",
    "export TMPDIR={b}/x",
    "env TMPDIR={b}/x pytest",
]
PY_TEMPLATE = "python3 -c 'open(\"{b}/x\",\"w\")'"


@pytest.mark.parametrize("template", TEMPLATES + [PY_TEMPLATE])
def test_a_bash_create_outside_the_roots_is_denied_inside_the_run_dir_allowed(template, repo):
    for base in (TMP, repo["home"]) + (() if template is PY_TEMPLATE else ("~",)):
        cmd = template.format(b=base)
        reason = denial(bash(repo, cmd)[0])
        assert reason, "%r should be denied" % cmd
        assert repo["a"] in reason and repo["run"] in reason, reason
    for base in (repo["run"], repo["a"]):
        cmd = template.format(b=base)
        assert bash(repo, cmd) == ("", 0), "%r should be allowed" % cmd


@pytest.mark.parametrize("name", run_scratch.CACHE_VARS)
def test_a_cache_var_assignment_outside_the_roots_is_denied(name, repo):
    for cmd in ("export %s=~/c" % name, "%s=%s/c npm i" % (name, TMP)):
        assert denial(bash(repo, cmd)[0]), cmd
    assert bash(repo, "export %s=%s/cache" % (name, repo["run"])) == ("", 0)


def test_a_computed_target_is_allowed(repo):
    assert bash(repo, 'echo hi > "$X"') == ("", 0)


def test_a_dev_stream_redirect_is_allowed_without_a_git_call(repo):
    calls = []

    def git(args, cwd):
        calls.append(args)
        raise AssertionError("a /dev redirect needs no root lookup")
    assert bash(repo, "make > /dev/null 2> /dev/stderr", git=git) == ("", 0)
    assert calls == []


def test_a_plain_ls_never_reaches_the_target_parser(repo, monkeypatch):
    seen = []
    real = create_fence_targets.shell_targets

    def spy(*args, **kw):
        seen.append(args[0])
        return real(*args, **kw)
    monkeypatch.setattr(create_fence_targets, "shell_targets", spy)

    def git(args, cwd):
        raise AssertionError("a plain ls needs no root lookup")
    assert bash(repo, "ls -la", git=git) == ("", 0)
    assert seen == []
    bash(repo, "touch x")  # the spy is wired: a create verb does reach the parser
    assert seen == ["touch x"]


def test_inactive_without_a_design_run_or_with_the_switch_off(repo):
    def git(args, cwd):
        raise AssertionError("an inactive fence does no lookup")
    cmd = "touch %s/x" % TMP
    assert denial(bash(repo, cmd)[0])  # control: the same command is denied when active
    assert bash(repo, cmd, env=make_env(repo, TP_DESIGN_RUN=None), git=git) == ("", 0)
    assert bash(repo, cmd, env=make_env(repo, TP_CREATE_FENCE="off"), git=git) == ("", 0)
    for env in (make_env(repo, TP_DESIGN_RUN=None), make_env(repo, TP_CREATE_FENCE="off")):
        assert fence(repo, "Write", env=env, git=git,
                     file_path=os.path.join(TMP, "x")) == ("", 0)


def test_a_nested_worker_creates_in_the_runs_scratch_dir_but_not_in_the_run_tree(repo):
    env = make_env(repo, top="attempt")
    cwd = repo["attempt"]
    assert bash(repo, 'mkdir "$TMPDIR/x"', env=env, cwd=cwd) == ("", 0)
    assert bash(repo, "mkdir %s/inner" % repo["attempt"], env=env, cwd=cwd) == ("", 0)
    out, _ = bash(repo, "mkdir %s/other" % repo["a"], env=env, cwd=cwd)
    reason = denial(out)
    assert reason and repo["attempt"] in reason and repo["run"] in reason


def _stdin(monkeypatch, text):
    monkeypatch.setattr(sys, "stdin", io.StringIO(text))


def _crash_payload(tmp_path, repo):
    plain = tmp_path / "plain"
    plain.mkdir()
    return json.dumps({"tool_name": "Bash", "cwd": str(plain), "session_id": "s",
                       "tool_input": {"command": "touch %s/x" % repo["home"]}})


@pytest.mark.parametrize("kind", ["bad-json", "no-git", "parser-raises"])
def test_a_hook_crash_allows_with_one_stderr_line(kind, repo, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TP_DESIGN_RUN", "1")
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.delenv("TP_CREATE_FENCE", raising=False)
    _stdin(monkeypatch, "{not json" if kind == "bad-json" else _crash_payload(tmp_path, repo))
    if kind == "parser-raises":
        def boom(*a, **k):
            raise RuntimeError("parser exploded")
        monkeypatch.setattr(create_fence_targets, "shell_targets", boom)
    with pytest.raises(SystemExit) as exit_info:
        hook.main()
    captured = capsys.readouterr()
    assert exit_info.value.code == 0
    assert captured.out == ""
    assert len(captured.err.strip().splitlines()) == 1
