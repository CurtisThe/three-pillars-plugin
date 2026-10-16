"""Tests for child_transcript.py — host/inner transcript lookup and host verification.

strata-session-isolation task 1.2: a child session is a second `claude -p` process whose
transcripts land under the same Claude config dir as the orchestrator's. `host_path` finds
the child's own host transcript (`projects/*/<child>.jsonl`), `inner_ids` lists the inner
subagent transcripts the host spawned (`projects/*/<child>/subagents/agent-*.jsonl`), and
`verify_host` proves the host did exactly one thing: one `Agent`/`Task` call naming the
requested subagent and model. Every fixture is JSONL written under `tmp_path`; nothing here
launches a live `claude`, router or GPU job.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import child_transcript  # noqa: E402

AGENT_REF = "three-pillars:tp-runbook"
MODEL = "haiku"
CHILD = "c0ffee00-1111-2222-3333-444455556666"


def _write_jsonl(path: Path, records: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")
    return path


def _agent_call(name: str = "Agent", agent_ref: str = AGENT_REF, model: str = MODEL) -> dict:
    return {"type": "assistant", "message": {"id": "msg_1", "content": [
        {"type": "tool_use", "id": "tu_1", "name": name,
         "input": {"subagent_type": agent_ref, "model": model,
                   "prompt": "implement task 1.2"}}]}}


def _bash_call(command: str = "pytest -q") -> dict:
    return {"type": "assistant", "message": {"id": "msg_2", "content": [
        {"type": "tool_use", "id": "tu_2", "name": "Bash", "input": {"command": command}}]}}


def test_host_path_found_and_missing(tmp_path: Path) -> None:
    host = _write_jsonl(tmp_path / "projects" / "-p" / f"{CHILD}.jsonl", [_agent_call()])

    assert child_transcript.host_path(CHILD, tmp_path) == host
    assert child_transcript.host_path("deadbeef-0000", tmp_path) is None


def test_inner_ids_zero_one_two(tmp_path: Path) -> None:
    inner = tmp_path / "projects" / "-p" / CHILD / "subagents"

    assert child_transcript.inner_ids(CHILD, tmp_path) == []

    _write_jsonl(inner / "agent-abc12345.jsonl", [])
    assert child_transcript.inner_ids(CHILD, tmp_path) == ["abc12345"]

    _write_jsonl(inner / "agent-99zz0011.jsonl", [])
    assert child_transcript.inner_ids(CHILD, tmp_path) == ["99zz0011", "abc12345"]


def test_verify_host_one_matching_call() -> None:
    ok, why = child_transcript.verify_host([_agent_call()], AGENT_REF, MODEL)
    assert ok is True
    assert isinstance(why, str)

    ok_task, _ = child_transcript.verify_host([_agent_call(name="Task")], AGENT_REF, MODEL)
    assert ok_task is True


def test_verify_host_rejects() -> None:
    cases = [
        ([], "no Agent call"),
        ([_agent_call(), _agent_call()], "2 tool calls"),
        ([_agent_call(), _bash_call()], "2 tool calls"),
        ([_agent_call(agent_ref="three-pillars:other")], "subagent_type"),
        ([_agent_call(model="opus")], "model"),
    ]
    for records, needle in cases:
        ok, why = child_transcript.verify_host(records, AGENT_REF, MODEL)
        assert ok is False, records
        assert needle in why, (records, why)


def test_config_dir_default(tmp_path: Path, monkeypatch) -> None:
    cfg = tmp_path / "cfg"
    _write_jsonl(cfg / "projects" / "-p" / f"{CHILD}.jsonl", [_agent_call()])
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    assert child_transcript.host_path(CHILD) == cfg / "projects" / "-p" / f"{CHILD}.jsonl"

    home = tmp_path / "home"
    _write_jsonl(home / ".claude" / "projects" / "-p" / f"{CHILD}.jsonl", [_agent_call()])
    monkeypatch.delenv("CLAUDE_CONFIG_DIR")
    monkeypatch.setenv("HOME", str(home))
    assert child_transcript.host_path(CHILD) == home / ".claude" / "projects" / "-p" / f"{CHILD}.jsonl"
