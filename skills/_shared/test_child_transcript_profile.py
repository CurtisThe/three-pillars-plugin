"""Tests for child_transcript.py — the lookup polls the pinned profile, then its siblings.

child-spawn-profile-inherit task 1.3: a child spawned with its profile pinned writes under
the parent's own profile dir, so `cfg=None` finds it there. When the pin did not hold and the
child landed under a *sibling* profile, the same calls still find it there — and say so once
on stderr per looked-up id. A config dir that is not a profile dir keeps today's single-dir
lookup, and an explicit `cfg` never widens the search. Every fixture is JSONL under
`tmp_path`; nothing launches a live `claude`, router or GPU job.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import child_profile  # noqa: E402
import child_transcript  # noqa: E402

CHILD = "c0ffee00-1111-2222-3333-444455556666"
AGENT_ID = "abc12345"
AGENT_REF = "three-pillars:tp-runbook"
MODEL = "haiku"


@pytest.fixture(autouse=True)
def _clear_notes():
    child_profile._noted.clear()
    yield
    child_profile._noted.clear()


def _write_jsonl(path: Path, records: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")
    return path


def _agent_call() -> dict:
    return {"type": "assistant", "message": {"id": "msg_1", "content": [
        {"type": "tool_use", "id": "tu_1", "name": "Agent",
         "input": {"subagent_type": AGENT_REF, "model": MODEL,
                   "prompt": "implement task 1.3"}}]}}


def _text(msg_id: str, text: str, stop_reason: str | None = None) -> dict:
    msg = {"id": msg_id, "role": "assistant", "content": [{"type": "text", "text": text}]}
    if stop_reason is not None:
        msg["stop_reason"] = stop_reason
    return {"type": "assistant", "message": msg}


def _write_child(cfg: Path) -> tuple[Path, Path]:
    """The host transcript (one `Agent` call) and the inner transcript that ends its turn."""
    host = _write_jsonl(cfg / "projects" / "-p" / f"{CHILD}.jsonl", [_agent_call()])
    inner = _write_jsonl(cfg / "projects" / "-p" / CHILD / "subagents" / f"agent-{AGENT_ID}.jsonl",
                         [_text("msg_1", "done", stop_reason="end_turn")])
    return host, inner


def _profiles(tmp_path: Path) -> tuple[Path, Path]:
    aris = tmp_path / ".claude-profiles" / "aris"
    personal = tmp_path / ".claude-profiles" / "personal"
    aris.mkdir(parents=True)
    personal.mkdir(parents=True)
    return aris, personal


def test_child_under_pinned_profile_needs_no_note(tmp_path: Path, monkeypatch, capsys) -> None:
    aris, _personal = _profiles(tmp_path)
    host, _inner = _write_child(aris)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(aris))

    assert child_transcript.host_path(CHILD) == host
    assert child_transcript.inner_ids(CHILD) == [AGENT_ID]
    assert child_transcript.inner_done(AGENT_ID) is True
    assert child_transcript.last_text(AGENT_ID) == "done"
    assert capsys.readouterr().err == ""


def test_child_under_sibling_profile_notes_once_per_id(tmp_path: Path, monkeypatch, capsys) -> None:
    aris, personal = _profiles(tmp_path)
    host, _inner = _write_child(personal)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(aris))

    assert child_transcript.host_path(CHILD) == host
    assert child_transcript.inner_ids(CHILD) == [AGENT_ID]
    assert child_transcript.inner_done(AGENT_ID) is True
    assert child_transcript.last_text(AGENT_ID) == "done"

    err = capsys.readouterr().err.strip().splitlines()
    assert len(err) == 2, err
    assert all(str(personal) in line for line in err), err
    assert any(CHILD in line for line in err), err
    assert any(AGENT_ID in line for line in err), err


def test_child_under_both_profiles_prefers_pinned(tmp_path: Path, monkeypatch, capsys) -> None:
    aris, personal = _profiles(tmp_path)
    host, _inner = _write_child(aris)
    _write_child(personal)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(aris))

    assert child_transcript.host_path(CHILD) == host
    assert child_transcript.inner_ids(CHILD) == [AGENT_ID]
    assert child_transcript.inner_done(AGENT_ID) is True
    assert child_transcript.last_text(AGENT_ID) == "done"
    assert capsys.readouterr().err == ""


def test_non_profile_config_dir_stays_single_dir(tmp_path: Path, monkeypatch, capsys) -> None:
    cfg = tmp_path / "cfg"
    _write_child(tmp_path / "other")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))

    assert child_transcript.host_path(CHILD) is None
    assert child_transcript.inner_ids(CHILD) == []
    assert child_transcript.inner_done(AGENT_ID) is False
    assert child_transcript.last_text(AGENT_ID) == ""
    assert capsys.readouterr().err == ""


def test_explicit_cfg_does_not_widen_the_search(tmp_path: Path, monkeypatch, capsys) -> None:
    aris, personal = _profiles(tmp_path)
    _write_child(personal)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(aris))

    assert child_transcript.host_path(CHILD, aris) is None
    assert child_transcript.inner_ids(CHILD, aris) == []
    assert capsys.readouterr().err == ""
