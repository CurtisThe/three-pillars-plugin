#!/usr/bin/env python3
"""context_rollover.py — the read side of the ~300k orchestrator rollover.

design: strata-spend-leaks (Task 3.1). A design run's orchestrator pays its whole
context again as cache reads on every turn, so the seat rolls it over (save -> /clear
-> restore) once the next turn would re-read at least `DEFAULT_THRESHOLD` tokens AND
the session is genuinely at a turn boundary — never mid-tool, never over background
agents, never before it has been idle for `idle_s`.

Four pure questions, no tmux, no git, no clock:
- `read_records(path)` — the readable tail of a session's JSONL transcript (bad and
  half-written lines are skipped, a missing file is `[]`; it never raises);
- `context_size(records)` — the last main-chain assistant turn's
  `input_tokens + cache_read_input_tokens + cache_creation_input_tokens` (the tokens
  the next request re-reads; `output_tokens` is not part of them), or None when the
  transcript reports no usage. Sidechain records (a subagent's turns) are skipped, and
  the streamed snapshot + final records of one `message.id` count once, final winning;
- `at_turn_boundary(records, pane, idle_for_s, idle_s)` — `(True, "")` when the last
  main-chain turn stopped on `end_turn` with nothing after it, the pane shows no
  background agents and the session has been idle for `idle_s`; otherwise
  `(False, why-we-wait)` so the caller can print the reason it held off;
- `due(size, threshold)` — size >= threshold (inclusive); an unknown size is never due.

`context_rollover_drive.py` (Task 4.1) owns the tmux side; this module only answers.
"""
from __future__ import annotations

import json
import os

import design_run_watch as drw

__all__ = ["DEFAULT_THRESHOLD", "read_records", "context_size",
           "at_turn_boundary", "due"]

DEFAULT_THRESHOLD = 300_000
TAIL_BYTES = 1 << 20  # only the last turn is read; a transcript is append-only
SIZE_FIELDS = ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")


def read_records(path) -> "list[dict]":
    """The decodable JSON objects in the readable tail of a JSONL transcript.

    Undecodable, empty and half-written (still being appended) lines are skipped; a
    missing or unreadable file gives `[]`. Never raises.
    """
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            span = min(size, TAIL_BYTES)
            fh.seek(size - span)
            data = fh.read(span)
    except OSError:
        return []
    if span < size:  # the window started mid-line: drop that partial line
        first = data.find(b"\n")
        if first < 0:
            return []
        data = data[first + 1:]
    out: "list[dict]" = []
    for raw in data.splitlines():
        try:
            rec = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


def _message(rec: dict) -> dict:
    return rec["message"] if isinstance(rec.get("message"), dict) else {}


def _usage(msg: dict) -> dict:
    return msg["usage"] if isinstance(msg.get("usage"), dict) else {}


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_main_assistant(rec: dict) -> bool:
    """An `assistant` record of the session itself, not of one of its subagents."""
    return rec.get("type") == "assistant" and not rec.get("isSidechain")


def _turns(records: "list[dict]") -> "list[dict]":
    """Main-chain assistant records grouped by `message.id` (fallback `requestId`), in
    first-seen order. One group is one reply: its streamed snapshot record and its
    final record share an id, so the reply counts once.

    Each turn: {msgs, stop_reason (last non-null in the group), has_tool_use,
    last_index (this group's last record)}.
    """
    groups: "dict[str, dict]" = {}
    for index, rec in enumerate(records):
        if not _is_main_assistant(rec):
            continue
        msg = _message(rec)
        key = msg.get("id") or rec.get("requestId") or f"#{index}"
        turn = groups.setdefault(key, {"msgs": [], "stop_reason": None,
                                       "has_tool_use": False, "last_index": index})
        turn["msgs"].append(msg)
        if msg.get("stop_reason") is not None:
            turn["stop_reason"] = msg["stop_reason"]
        content = msg.get("content")
        if isinstance(content, list):
            turn["has_tool_use"] = turn["has_tool_use"] or any(
                b.get("type") == "tool_use" for b in content if isinstance(b, dict))
        turn["last_index"] = index
    return list(groups.values())


def _field(turn: dict, field: str):
    """The last record of the turn that reports `field` — the final record wins, since
    it is written last; None when no record in the turn reports it."""
    for msg in reversed(turn["msgs"]):
        value = _usage(msg).get(field)
        if _is_int(value):
            return value
    return None


def context_size(records: "list[dict]") -> "int | None":
    """The tokens the next request re-reads, from the last main-chain assistant turn.

    None when the transcript has no main-chain assistant turn or none of the size
    fields is reported — an unknown size, never a 0 that reads as "small".
    """
    turns = _turns(records)
    if not turns:
        return None
    turn = turns[-1]
    values = [_field(turn, field) for field in SIZE_FIELDS]
    if all(v is None for v in values):
        return None
    return sum(v for v in values if v is not None)


def at_turn_boundary(records: "list[dict]", pane, idle_for_s: float,
                     idle_s: float) -> "tuple[bool, str]":
    """May this session be rolled over now? `(True, "")` or `(False, why-we-wait)`.

    `pane` is the run window's visible text (None when unreadable), `idle_for_s` how
    long it has been unchanged, `idle_s` the idle stretch the caller requires. A
    trailing `system` / attachment record is allowed; a `user` record (including a
    `tool_result` answer) means the next turn has already started.
    """
    if idle_for_s < idle_s:
        return False, f"idle {idle_for_s:.0f}s < required {idle_s:.0f}s"
    if pane is None:
        return False, "pane unreadable"
    if drw.BACKGROUND_MARKER in pane:
        return False, "background agents in the pane"
    turns = _turns(records)
    if not turns:
        return False, "no main-chain assistant turn in the transcript"
    turn = turns[-1]
    if turn["has_tool_use"]:
        return False, "the last turn calls a tool"
    if turn["stop_reason"] != "end_turn":
        return False, f"last turn stopped on {turn['stop_reason']!r}, not 'end_turn'"
    for rec in records[turn["last_index"] + 1:]:
        if rec.get("type") == "user":
            return False, "a user record follows the last assistant turn"
    return True, ""


def due(size, threshold: int = DEFAULT_THRESHOLD) -> bool:
    """Over the threshold, inclusive. An unknown size is never due."""
    return _is_int(size) and size >= threshold
