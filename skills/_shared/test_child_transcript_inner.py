"""Tests for child_transcript.py — the inner subagent's end-of-turn and final text.

strata-session-isolation task 1.3: the dispatcher's wait loop asks two questions about a
child's inner subagent transcript (`projects/*/*/subagents/agent-<id>.jsonl`): has the turn
ended, and what did the agent finally say. `inner_done` answers the first with the same
predicate the watchdog uses (`transcript_tail.end_of_turn`), so the two readers cannot
disagree; `last_text` answers the second. Both take `cfg` (the Claude config dir) and both
return a value instead of raising when the transcript is missing. Every fixture is JSONL
written under `tmp_path`; nothing here launches a live `claude`, router or GPU job.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import child_transcript  # noqa: E402

AGENT_ID = "abc12345"


def _write_jsonl(path: Path, records: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")
    return path


def _inner_path(tmp_path: Path, agent_id: str = AGENT_ID) -> Path:
    return tmp_path / "projects" / "-p" / "c0ffee00-host" / "subagents" / f"agent-{agent_id}.jsonl"


def _text(msg_id: str, text: str, stop_reason: str | None = None) -> dict:
    msg = {"id": msg_id, "role": "assistant", "content": [{"type": "text", "text": text}]}
    if stop_reason is not None:
        msg["stop_reason"] = stop_reason
    return {"type": "assistant", "message": msg}


def _tool_use(msg_id: str, tool_use_id: str = "tu_1") -> dict:
    return {"type": "assistant", "message": {
        "id": msg_id, "role": "assistant", "stop_reason": "tool_use",
        "content": [{"type": "tool_use", "id": tool_use_id, "name": "Bash",
                     "input": {"command": "pytest -q"}}]}}


def test_inner_done_true_after_end_turn(tmp_path: Path) -> None:
    _write_jsonl(_inner_path(tmp_path), [
        _text("msg_1", "working on it"),
        _text("msg_2", "final reply", stop_reason="end_turn"),
    ])
    assert child_transcript.inner_done(AGENT_ID, tmp_path) is True

    _write_jsonl(_inner_path(tmp_path), [
        _text("msg_1", "working on it"),
        _tool_use("msg_2"),
    ])
    assert child_transcript.inner_done(AGENT_ID, tmp_path) is False

    assert child_transcript.inner_done("deadbeef", tmp_path) is False


def test_last_text_picks_final_text(tmp_path: Path) -> None:
    _write_jsonl(_inner_path(tmp_path), [
        _text("msg_1", "first"),
        _text("msg_2", "final reply", stop_reason="end_turn"),
    ])
    assert child_transcript.last_text(AGENT_ID, tmp_path) == "final reply"


def test_last_text_missing_is_empty(tmp_path: Path) -> None:
    assert child_transcript.last_text(AGENT_ID, tmp_path) == ""


HANDBACK = HERE / "fixtures" / "transcript_tail" / "handback.jsonl"
HANDBACK_ID = "a0000009"
HANDBACK_REPLY = "Task 9.9 done, green (scrubbed)"


def test_last_text_is_the_handback_message(tmp_path: Path) -> None:
    """CLI 2.1.285+: an inner agent that ends via `SubagentHandback` replies with that
    call's `input.message` (what the watchdog's `reply_text` reads), never ""."""
    inner = _inner_path(tmp_path, HANDBACK_ID)
    inner.parent.mkdir(parents=True)
    inner.write_bytes(HANDBACK.read_bytes())
    assert child_transcript.inner_done(HANDBACK_ID, tmp_path) is True
    assert child_transcript.last_text(HANDBACK_ID, tmp_path) == HANDBACK_REPLY


def test_wait_reply_is_the_handback_message(tmp_path: Path, monkeypatch) -> None:
    """`child_spawn.py wait` writes the hand-back message to the reply file that the S3
    council members and the S4 scout read as the child's reply."""
    import child_slot
    import child_spawn
    import child_state

    cfg = tmp_path / "cfg"
    inner = _inner_path(cfg, HANDBACK_ID)
    inner.parent.mkdir(parents=True)
    inner.write_bytes(HANDBACK.read_bytes())
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    monkeypatch.setattr(child_slot, "release",
                        lambda *a, **k: {"agent": "ok", "session": "released"})
    state = tmp_path / "c0ffee00.json"
    child_state.write(state, {"child_session": "c0ffee00-host", "pid": 999999, "pgid": 999999,
                              "start_ticks": 1, "inner_agent_id": HANDBACK_ID,
                              "state": "running", "deadline_at": 9e12})
    reply = tmp_path / "reply.txt"
    out = child_spawn.cmd_wait(state, budget_s=5, reply_out=str(reply))
    assert out["state"] == "done", out
    assert reply.read_text(encoding="utf-8") == HANDBACK_REPLY
