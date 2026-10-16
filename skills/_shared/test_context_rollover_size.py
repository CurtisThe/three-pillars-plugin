"""test_context_rollover_size.py — the context size of a design-run transcript.

design: strata-spend-leaks (Task 3.1) — the rollover decision starts from what the
session's next turn re-reads: the last main-chain assistant turn's
`input_tokens + cache_read_input_tokens + cache_creation_input_tokens`.

The records are canned dicts in the JSONL shape Claude Code writes (top-level `type`
/ `isSidechain`, a `message` with `id` / `usage` / `stop_reason`), so no real
transcript and no config dir is read here.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import context_rollover as rollover  # noqa: E402


def _assistant(msg_id, usage=None, stop_reason=None, sidechain=False):
    """One main-chain (or sidechain) assistant record as Claude Code writes it."""
    msg = {"id": msg_id, "role": "assistant", "content": [{"type": "text", "text": "hi"}]}
    if usage is not None:
        msg["usage"] = usage
    if stop_reason is not None:
        msg["stop_reason"] = stop_reason
    return {"type": "assistant", "isSidechain": sidechain, "message": msg}


def test_size_sums_input_and_cache_fields():
    """The design's example: 2_000 + 290_000 + 8_000 -> 300_000 (output excluded)."""
    usage = {"input_tokens": 2_000, "cache_read_input_tokens": 290_000,
             "cache_creation_input_tokens": 8_000, "output_tokens": 120}
    assert rollover.context_size([_assistant("m1", usage, "end_turn")]) == 300_000


def test_size_uses_last_assistant_turn():
    """The newest turn is the one the next request re-reads, and one `message.id`
    counts once: the final (stop_reason) record wins over its streamed snapshot."""
    older = {"input_tokens": 1_000, "cache_read_input_tokens": 50_000,
             "cache_creation_input_tokens": 5_000}
    snapshot = {"input_tokens": 2_000, "cache_read_input_tokens": 100_000,
                "cache_creation_input_tokens": 10_000}
    final = {"input_tokens": 2_000, "cache_read_input_tokens": 150_000,
             "cache_creation_input_tokens": 12_000, "output_tokens": 400}
    records = [
        _assistant("m1", older, "end_turn"),
        _assistant("m2", snapshot),               # streamed snapshot, no stop_reason
        _assistant("m2", final, "end_turn"),      # the same message, final record
    ]
    assert rollover.context_size(records) == 164_000


def test_size_ignores_sidechain_records():
    """A subagent's turn is not the orchestrator's context."""
    main = {"input_tokens": 1_000, "cache_read_input_tokens": 40_000,
            "cache_creation_input_tokens": 1_000}
    side = {"input_tokens": 9_000, "cache_read_input_tokens": 900_000,
            "cache_creation_input_tokens": 90_000}
    records = [
        _assistant("m1", main, "end_turn"),
        _assistant("m2", side, "end_turn", sidechain=True),
    ]
    assert rollover.context_size(records) == 42_000


def test_size_none_without_usage():
    """No usage anywhere (no records, a record with no `usage`, no assistant record)
    is an unknown size — never a 0 that reads as "small"."""
    assert rollover.context_size([]) is None
    assert rollover.context_size([_assistant("m1", None, "end_turn")]) is None
    assert rollover.context_size([{"type": "user", "message": {"role": "user"}}]) is None


def test_bad_lines_skipped(tmp_path):
    """`read_records` is fail-open: garbage lines and a missing file give records / []."""
    path = tmp_path / "session.jsonl"
    good = json.dumps({"type": "assistant", "isSidechain": False,
                       "message": {"id": "m1", "role": "assistant",
                                   "usage": {"input_tokens": 5}}})
    path.write_text("\n".join([
        "{not json at all",
        '"just a string"',
        "",
        good,
        '{"type": "assistant", "mess',  # a line still being written
    ]) + "\n", encoding="utf-8")
    assert [rec["message"]["id"] for rec in rollover.read_records(path)] == ["m1"]
    assert rollover.read_records(tmp_path / "missing.jsonl") == []
