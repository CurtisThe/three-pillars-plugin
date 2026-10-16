"""Tests for the hook's scratch lookup (fixture transcripts under tmp_path)."""
import json
import os

import pytest

import reviewer_delete_hook as hook

AGENT = "three-pillars:tp-readonly-auditor"


def rec(kind, content):
    return json.dumps({"type": kind, "message": {"content": content}}) + "\n"


@pytest.fixture
def env(tmp_path):
    proj = tmp_path / "projects" / "p"
    sub = proj / "sid" / "subagents"
    sub.mkdir(parents=True)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    pl = {"transcript_path": str(proj / "sid.jsonl"), "session_id": "sid", "agent_id": "a1",
          "agent_type": AGENT, "tool_name": "Bash", "cwd": str(scratch)}
    return pl, sub / "agent-a1.jsonl", scratch, proj / "sid.jsonl"


def test_transcript_file(env, tmp_path):
    pl, sub, _, parent = env
    sub.write_text("")
    assert hook.transcript_file(pl) == str(sub)
    sub.unlink()
    parent.write_text("")
    assert hook.transcript_file(pl) is None
    other = tmp_path / "projects" / "p" / "sid2" / "subagents" / "agent-a1.jsonl"
    other.parent.mkdir(parents=True)
    other.write_text("")
    assert hook.transcript_file(pl) == str(other)
    twin = tmp_path / "projects" / "p" / "sid3" / "subagents" / "agent-a1.jsonl"
    twin.parent.mkdir(parents=True)
    twin.write_text("")
    assert hook.transcript_file(pl) is None  # ambiguous: fail closed


def test_fallback_bounded_to_project_dir(env, tmp_path):
    pl, _, _, _ = env
    elsewhere = tmp_path / "projects" / "q" / "sid" / "subagents" / "agent-a1.jsonl"
    elsewhere.parent.mkdir(parents=True)
    elsewhere.write_text("")
    assert hook.transcript_file(pl) is None
    for bad in ("../a1", "*", "a1/../../x", ""):
        assert hook.transcript_file(dict(pl, agent_id=bad)) is None, bad


def test_scratch_lookup_is_lazy(monkeypatch):
    def boom(_):
        raise RuntimeError("lookup broke")
    monkeypatch.setattr(hook, "scratch_for", boom)
    pl = {"agent_type": AGENT, "tool_name": "Bash", "cwd": "/x"}
    for cmd in ("git diff a...b", "pytest -q", "find . -name a -exec grep x {} +"):
        assert hook.run(dict(pl, tool_input={"command": cmd})) == ("", 0), cmd
    out, _ = hook.run(dict(pl, tool_input={"command": "rm -rf /x/y"}))
    assert "crashed: RuntimeError" in out


def test_extract_marker():
    assert hook.extract_marker("TP_SCRATCH: /a/b\n\nhi\nTP_SCRATCH: /c") == "/a/b"
    assert hook.extract_marker("TP_SCRATCH: rel/x") is None
    assert hook.extract_marker("no marker") is None


def test_scratch_first_user_only(env):
    pl, sub, scratch, parent = env
    sub.write_text(rec("system", "TP_SCRATCH: /elsewhere")
                   + rec("user", f"TP_SCRATCH: {scratch}\n\nhi")
                   + rec("user", "TP_SCRATCH: /forged"))
    parent.write_text(rec("user", "TP_SCRATCH: /parent"))
    assert hook.scratch_for(pl) == os.path.realpath(scratch)


def test_scratch_text_blocks(env):
    pl, sub, scratch, _ = env
    sub.write_text(rec("user", [{"type": "text", "text": f"TP_SCRATCH: {scratch}\nx"}]))
    assert hook.scratch_for(pl) == os.path.realpath(scratch)


def test_scratch_none_cases(env, tmp_path, monkeypatch):
    pl, sub, scratch, _ = env
    assert hook.scratch_for(pl) is None
    sub.write_text(rec("user", f"TP_SCRATCH: {tmp_path}/missing\n"))
    assert hook.scratch_for(pl) is None
    tmpdir = tmp_path / "tmproot"
    tmpdir.mkdir()
    monkeypatch.setenv("TMPDIR", str(tmpdir))
    for bad in ["/", hook._TMP_BASE, os.path.expanduser("~"), str(tmpdir), str(tmp_path)]:
        sub.write_text(rec("user", f"TP_SCRATCH: {bad}\n"))
        assert hook.scratch_for(pl) is None, bad


def test_end_to_end(env):
    pl, sub, scratch, _ = env
    sub.write_text(rec("user", f"TP_SCRATCH: {scratch}\n\ngo"))
    pl["tool_input"] = {"command": f"rm -rf {scratch}/out"}
    assert hook.run(pl) == ("", 0)
    pl["tool_input"] = {"command": f"rm -rf {scratch}/../x"}
    assert "deny" in hook.run(pl)[0]
    sub.unlink()
    pl["tool_input"] = {"command": f"rm -rf {scratch}/out"}
    assert "deny" in hook.run(pl)[0]
