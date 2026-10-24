"""Tests for wt_layout_hook (design worktrees-under-wt-only 1.2)."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parent / "wt_layout_hook.py"
ISO = {"isolation": "worktree"}


def _run(payload, env_extra=None, raw=None, design_run=True):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("TP_") and k != "CLAUDE_PROJECT_DIR"}
    if design_run:
        env["TP_DESIGN_RUN"] = "1"
    env.update(env_extra or {})
    data = raw if raw is not None else json.dumps(payload)
    return subprocess.run([sys.executable, str(HOOK)], input=data, env=env,
                          capture_output=True, text=True)


def _bash(cmd, cwd):
    return {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": str(cwd)}


def _assert_deny(proc):
    assert proc.returncode == 0
    out = json.loads(proc.stdout)["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny"
    reason = out["permissionDecisionReason"]
    assert "wt_root.py open" in reason
    assert "--role" in reason and "--slug" in reason and "--base-ref" in reason


def _assert_allow(proc):
    assert proc.returncode == 0
    assert proc.stdout == ""


@pytest.fixture
def repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    return tmp_path


def _agent(repo, tool="Agent"):
    return {"tool_name": tool, "tool_input": dict(ISO, prompt="x"), "cwd": str(repo)}


def test_inactive_without_design_run_or_marker(repo):
    _assert_allow(_run(_agent(repo), design_run=False))


def test_active_with_design_run(repo):
    _assert_deny(_run(_agent(repo)))


def test_off_switch(repo):
    _assert_allow(_run(_agent(repo), {"TP_WT_LAYOUT": "off"}))


def test_active_with_tp_marker(repo):
    (repo / "three-pillars-docs").mkdir()
    _assert_deny(_run(_agent(repo), design_run=False))


def test_isolation_denied(repo):
    """One testcase: both tool names must deny; each failure names the marker and the case."""
    marker = 'out["permissionDecision"] == "deny"'
    for tool in ("Agent", "Task"):
        where = f"tool_name={tool!r} isolation=worktree"
        try:
            proc = _run(_agent(repo, tool))
        except Exception as exc:  # noqa: BLE001 - report, never escape
            pytest.fail(f"{marker} expected, hook call raised ({exc!r}): {where}")
        assert proc.returncode == 0, \
            f"{marker} expected, hook exited {proc.returncode}: {where}"
        assert proc.stdout.strip(), f"{marker} expected, hook allowed: {where}"
        try:
            out = json.loads(proc.stdout)["hookSpecificOutput"]
        except (ValueError, KeyError, TypeError) as exc:
            pytest.fail(f"{marker} expected, hook output unparseable ({exc!r}): {where}")
        assert out.get("permissionDecision") == "deny", \
            f"{marker} expected, got {out.get('permissionDecision')!r}: {where}"
        reason = out.get("permissionDecisionReason", "")
        assert "wt_root.py open" in reason, f"{marker}: reason lacks wt_root.py open: {where}"
        for flag in ("--role", "--slug", "--base-ref"):
            assert flag in reason, f"{marker}: reason lacks {flag}: {where}"


def test_agent_without_isolation_allowed(repo):
    _assert_allow(_run({"tool_name": "Agent", "tool_input": {"prompt": "x"}, "cwd": str(repo)}))


CLW = "/r/" + ".claude" + "/worktrees/agent-1"


DENY_CASES = [
    ("git worktree add .claude/worktrees/x", "/r"),
    ("git -C /r worktree add -b b /r/.claude/worktrees/x HEAD", "/r"),
    ("cd /r && git worktree add --detach .claude/w/y", "/r"),
    # harmless target text: only the payload cwd, a `cd` base or a `-C` base is under .claude
    ("git worktree add ../x", CLW),
    ("git worktree add -b b ../x HEAD", CLW),
    ("cd " + CLW + " && git worktree add ../x", "/r"),
    ("cd " + CLW + " && git worktree add -B b x", "/r"),
    ("git -C " + CLW + " worktree add x", "/r"),
    ("git -C " + CLW + " worktree add -b b x HEAD", "/r"),
    ("git -c k=v -C " + CLW + " worktree add --detach x", "/r"),
]


def test_claude_worktree_add_denied(repo):
    """One testcase: every case must deny; each failure names the marker and the case."""
    marker = 'out["permissionDecision"] == "deny"'
    for cmd, cwd in DENY_CASES:
        where = f"{cmd!r} cwd={cwd}"
        proc = _run(_bash(cmd, cwd))
        assert proc.stdout.strip(), f"{marker} expected, hook allowed: {where}"
        try:
            out = json.loads(proc.stdout)["hookSpecificOutput"]
        except (ValueError, KeyError, TypeError) as exc:
            pytest.fail(f"{marker} expected, hook output unparseable ({exc!r}): {where}")
        assert out.get("permissionDecision") == "deny", \
            f"{marker} expected, got {out.get('permissionDecision')!r}: {where}"
        reason = out.get("permissionDecisionReason", "")
        assert "wt_root.py open" in reason, f"{marker}: reason lacks wt_root.py open: {where}"


@pytest.mark.parametrize("cmd", [
    "git worktree add ../repo-wt/x",
    "git worktree add -b .claude-ish ../repo-wt/y",
    "git worktree list",
    "ls .claude",
])
def test_ordinary_commands_allowed(repo, cmd):
    _assert_allow(_run(_bash(cmd, repo)))


def test_other_tool_allowed(repo):
    _assert_allow(_run({"tool_name": "Read", "tool_input": {"file_path": ".claude/x"},
                        "cwd": str(repo)}))


@pytest.mark.parametrize("raw", ["{not json", None])
def test_bad_input_allows_with_one_stderr_line(repo, raw):
    if raw is None:
        proc = _run(_bash("git worktree add 'unterminated", repo))
    else:
        proc = _run(None, raw=raw)
    _assert_allow(proc)
    assert len(proc.stderr.strip().splitlines()) == 1
