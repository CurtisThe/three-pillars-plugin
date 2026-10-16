"""Tests for reviewer_delete_hook: scope, deny JSON, fail-closed, latency.
(Fixture commands use a neutral root: invariant 3 bars literal temp paths under skills/.)"""
import builtins
import io
import json
import os
import subprocess
import sys
import time

import pytest

import reviewer_delete_hook as hook

TOP_LEVEL_KEYS = {"cwd", "effort", "hook_event_name", "permission_mode", "prompt_id",
                  "session_id", "tool_input", "tool_name", "tool_use_id", "transcript_path"}
SUBAGENT_KEYS = TOP_LEVEL_KEYS | {"agent_id", "agent_type"}
RM = "rm -rf /x/claude-1000/tmp*"
# The delete sits past the 120-char display slice, so a hook that classifies
# only a prefix of the command is caught.
LONG_RM = "echo " + "benign-review-note " * 7 + "&& " + RM
SCOPED = ("tp-review-confirmer", "tp-review-confirmer-deep",
          "tp-readonly-auditor", "tp-impl-auditor", "tp-phase-checker")


def payload(command, agent=None, tool="Bash"):
    p = {k: "v" for k in (SUBAGENT_KEYS if agent else TOP_LEVEL_KEYS)}
    p.update(tool_name=tool, tool_input={"command": command}, cwd="/x",
             transcript_path="/nonexistent/projects/p/s.jsonl", session_id="s")
    if agent:
        p.update(agent_type=agent, agent_id="a1")
    return p


def test_top_level_allows_without_file_read(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("open called")
    monkeypatch.setattr(builtins, "open", boom)
    assert hook.run(payload(RM)) == ("", 0)


def test_general_purpose_allows():
    assert hook.run(payload(RM, "general-purpose")) == ("", 0)


def test_denies_confirmer():
    out, code = hook.run(payload(RM, "three-pillars:tp-review-confirmer"))
    assert code == 0
    d = json.loads(out)["hookSpecificOutput"]
    assert d["permissionDecision"] == "deny" and d["hookEventName"] == "PreToolUse"
    r = d["permissionDecisionReason"]
    assert r.startswith("reviewer-delete-guard: refused")
    assert RM in r and "orchestrator" in r
    assert any(root in r for root in hook.shared_roots() if "pytest-of-" in root)


def test_denies_scoped_names():
    """One node for the whole read-mostly set: every name bare and plugin-prefixed,
    the delete short and past the 120-char display slice, so any miss is named."""
    missed = []
    for name in SCOPED:
        for agent in (name, "three-pillars:" + name):
            for cmd in (RM, LONG_RM):
                out = hook.run(payload(cmd, agent))[0]
                d = json.loads(out)["hookSpecificOutput"]["permissionDecision"] if out else None
                if d != "deny":
                    missed.append((agent, cmd[:12]))
    assert not missed, f"scoped agent not denied a delete outside scratch: {missed}"


@pytest.mark.parametrize("agent,cmd", [("three-pillars:tp-worker", "git worktree remove ../wt"),
                                       ("tp-task-worker", RM)])
def test_unscoped_allows(agent, cmd):
    assert hook.run(payload(cmd, agent)) == ("", 0)


@pytest.mark.parametrize("cmd", ["pytest -q", "git diff a...b"])
def test_scoped_benign_allows(cmd):
    assert hook.run(payload(cmd, "tp-readonly-auditor")) == ("", 0)


def test_non_bash_allows():
    assert hook.run(payload(RM, "tp-readonly-auditor", tool="Read")) == ("", 0)


def test_classify_crash(monkeypatch):
    import reviewer_delete_guard as g

    def boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(g, "classify", boom)
    out, _ = hook.run(payload("ls", "tp-readonly-auditor"))
    assert "crashed:" in json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"]
    assert hook.run(payload("ls", "tp-worker")) == ("", 0)


def _main(monkeypatch, capsys, raw):
    monkeypatch.setattr(sys, "stdin", io.StringIO(raw))
    with pytest.raises(SystemExit) as e:
        hook.main()
    return capsys.readouterr().out, e.value.code


def test_import_failure(capsys):
    """One node for both missing modules and both scopes, so any miss is named
    and one junit failure pins it. Unscoped means silent for a top-level
    session AND for a write-capable subagent."""
    for mod in ("reviewer_delete_guard", "reviewer_delete_shell"):
        with pytest.MonkeyPatch.context() as mp:
            mp.setitem(sys.modules, mod, None)
            out, code = _main(mp, capsys, json.dumps(payload("ls", "tp-impl-auditor")))
            assert code == 0 and "crashed: ImportError" in out, (
                f"{mod} missing: scoped agent got no 'crashed: ImportError' deny: {out!r}")
            for unscoped in (payload("ls"), payload("ls", "three-pillars:tp-worker")):
                out, code = _main(mp, capsys, json.dumps(unscoped))
                assert (out, code) == ("", 0), (
                    f"{mod} missing: unscoped {unscoped.get('agent_type')} "
                    f"not allowed silently: {out}")


def test_garbage_stdin(monkeypatch, capsys):
    out, code = _main(monkeypatch, capsys,
                      'not json {"agent_type": "three-pillars:tp-readonly-auditor"')
    assert code == 0 and "deny" in out
    assert _main(monkeypatch, capsys, "not json") == ("", 0)


def test_subprocess_top_level_fast():
    script = os.path.join(os.path.dirname(__file__), "reviewer_delete_hook.py")
    t = time.time()
    r = subprocess.run([sys.executable, script], input=json.dumps(payload(RM)),
                       capture_output=True, text=True)
    assert (r.returncode, r.stdout) == (0, "") and time.time() - t < 2
