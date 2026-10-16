#!/usr/bin/env python3
"""transcript_tail.py — the one end-of-turn predicate over a Claude Code JSONL transcript.

design: run-throughput (Part S, runaway ceiling)

Claude Code writes one JSONL record per content block; one reply's records share
`message.id`, so `turns()` groups assistant records by it (fallback `requestId`): one
group, one request. `end_of_turn()`: the final turn stopped on `end_turn` with no `user`
record or `tool_use` after it, or (a 2.1.285+ subagent) its tool call was answered by a
`toolEndsTurn` tool_result (`SubagentHandback`; its `message` is the reply). Trailing
system / attachment / stop-hook / turn-duration records are allowed. No mtime-stability
(`stage_reset.idle()` adds its own). Stdlib only; never raises on bad lines.
"""
from __future__ import annotations

import json


def read_records(path) -> list[dict]:
    """Every decodable JSON object in the JSONL file; undecodable lines are skipped."""
    out = []
    with open(path, "rb") as fh:
        for raw in fh:
            try:
                rec = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                continue
            if isinstance(rec, dict):
                out.append(rec)
    return out


def _message(rec: dict) -> dict:
    return rec["message"] if isinstance(rec.get("message"), dict) else {}


def _blocks(rec: dict) -> list[dict]:
    content = _message(rec).get("content")
    return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []


def _has_tool_use(rec: dict) -> bool:
    return any(b.get("type") == "tool_use" for b in _blocks(rec))


def turns(records: list[dict]) -> list[dict]:
    """Assistant records grouped by `message.id` (fallback `requestId`), in first-seen order.

    Each turn: {id, model, output_tokens (max over the group), stop_reason (last
    non-null), text, has_tool_use, ts_last, last_index}.
    """
    groups: dict = {}
    for index, rec in enumerate(records):
        if rec.get("type") != "assistant":
            continue
        msg = _message(rec)
        key = msg.get("id") or rec.get("requestId") or f"#{index}"
        turn = groups.setdefault(key, {"id": key, "model": msg.get("model"), "output_tokens": 0,
                                       "stop_reason": None, "text": "", "has_tool_use": False,
                                       "ts_last": None, "last_index": index})
        tokens = (msg.get("usage") if isinstance(msg.get("usage"), dict) else {}).get("output_tokens")
        if isinstance(tokens, int) and not isinstance(tokens, bool):
            turn["output_tokens"] = max(turn["output_tokens"], tokens)
        if msg.get("stop_reason") is not None:
            turn["stop_reason"] = msg["stop_reason"]
        turn["text"] += "".join(b.get("text", "") for b in _blocks(rec)
                                if b.get("type") == "text" and isinstance(b.get("text"), str))
        turn["has_tool_use"] = turn["has_tool_use"] or _has_tool_use(rec)
        turn["ts_last"] = rec.get("timestamp") or turn["ts_last"]
        turn["last_index"] = index
    return list(groups.values())


def end_of_turn(records: list[dict]) -> dict | None:
    """The final turn when it ended the agent's turn, else None."""
    all_turns = turns(records)
    if not all_turns:
        return None
    final = max(all_turns, key=lambda t: t["last_index"])
    if final["stop_reason"] != "end_turn" or final["has_tool_use"]:
        return _handed_back(records, final)
    for rec in records[final["last_index"] + 1:]:
        if rec.get("type") == "user" or _has_tool_use(rec):
            return None
    return final


def _handed_back(records: list[dict], final: dict) -> dict | None:
    """``final`` + the hand-back's ``message`` as ``text`` and its ``ts_last``, else None."""
    after = records[final["last_index"] + 1:]
    at = next((i for i, rec in enumerate(after) if rec.get("type") == "user"), None)
    if at is None or not after[at].get("toolEndsTurn") or any(
            rec.get("type") == "user" or _has_tool_use(rec) for rec in after[at + 1:]):
        return None
    answered = {b.get("tool_use_id") for b in _blocks(after[at])}
    message = next((b["input"].get("message") for rec in records[:final["last_index"] + 1]
                    for b in _blocks(rec) if b.get("type") == "tool_use"
                    and b.get("id") in answered and isinstance(b.get("input"), dict)), None)
    return {**final, "text": message if isinstance(message, str) else final["text"],
            "ts_last": after[at].get("timestamp") or final["ts_last"]}
