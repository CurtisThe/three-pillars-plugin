"""Tests for transcript_usage.py — per-message final usage with a source marker (task 1.2)."""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import transcript_tail  # noqa: E402
import transcript_usage as tu  # noqa: E402

FIXTURE = HERE / "fixtures" / "transcript_usage" / "agent-mixed.jsonl"


def _summarize(fixture: Path = FIXTURE) -> dict:
    return tu.summarize(transcript_tail.read_records(fixture))


def test_mixed_fixture_counts_every_usage_field():
    s = _summarize()
    # Output: per-id max (final wins); 1840 + 612 + 97 + 4 + 250.
    assert s["output_tokens"] == 2803
    # Cache fields: today's reader drops them; E's final lacks them, so the field-by-field
    # merge keeps the snapshot values (D's 700 creation, E's 400 creation + 18000 read).
    assert s["cache_creation_input_tokens"] == 3100 + 500 + 0 + 700 + 400
    assert s["cache_read_input_tokens"] == 20000 + 12000 + 0 + 0 + 18000
    assert s["input_tokens"] == 14
    # The discriminating delta: cache fields make fresh > legacy.
    assert s["fresh_tokens"] == s["input_tokens"] + s["cache_creation_input_tokens"] + s["output_tokens"]
    assert s["fresh_tokens"] == 7517
    assert s["fresh_tokens"] > s["legacy"]["input"] + s["legacy"]["output"]
    # Thinking sums where reported; it is a breakdown of output, never added to it.
    assert s["thinking_tokens"] == 1210
    assert s["messages"] == 5
    assert s["final_messages"] == 4
    assert s["source"] == "mixed"


def test_mixed_fixture_legacy_matches_today_reader():
    s = _summarize()
    # Pinned literals from today's attempt_scan._token_totals on the same records
    # (per-id max of input_tokens / output_tokens); the audit bars importing it here.
    assert s["legacy"] == {"input": 14, "output": 2803}
    assert s["legacy"]["output"] == s["output_tokens"]


def _assistant(msg_id: str, usage: dict, stop_reason=None) -> dict:
    msg = {"id": msg_id, "role": "assistant", "usage": usage}
    if stop_reason is not None:
        msg["stop_reason"] = stop_reason
    return {"type": "assistant", "message": msg}


def test_all_final_is_source_final():
    records = [
        _assistant("A", {"output_tokens": 10}, "end_turn"),
        _assistant("B", {"output_tokens": 20, "output_tokens_details": {"thinking_tokens": 5}},
                   "tool_use"),
    ]
    s = tu.summarize(records)
    assert s["source"] == "final"
    assert s["output_tokens"] == 30
    assert s["thinking_tokens"] == 5
    assert s["messages"] == 2
    assert s["final_messages"] == 2


def test_all_snapshot_is_source_message_start():
    records = [
        _assistant("A", {"output_tokens": 5}),
        _assistant("A", {"output_tokens": 8}),
        _assistant("B", {"output_tokens": 3}),
    ]
    s = tu.summarize(records)
    assert s["source"] == "message_start"
    assert s["output_tokens"] == 8 + 3
    assert s["final_messages"] == 0


def test_thinking_tokens_none_when_unreported():
    s = tu.summarize([_assistant("A", {"output_tokens": 7}, "end_turn")])
    assert s["thinking_tokens"] is None
    assert s["output_tokens"] == 7


def test_empty_records_zero_totals_and_none_source():
    s = tu.summarize([])
    assert s["source"] is None
    assert s["thinking_tokens"] is None
    assert s["input_tokens"] == 0
    assert s["cache_creation_input_tokens"] == 0
    assert s["cache_read_input_tokens"] == 0
    assert s["output_tokens"] == 0
    assert s["fresh_tokens"] == 0
    assert s["messages"] == 0
    assert s["final_messages"] == 0
    assert s["legacy"] == {"input": 0, "output": 0}


def test_garbage_records_are_skipped_without_raising():
    records = [
        {"type": "assistant", "message": "not-a-dict"},
        {"type": "assistant", "message": {"id": "G1", "usage": "a-string"}},
        {"type": "assistant", "message": {"id": "G2", "usage": {"output_tokens": True}}},
        {"type": "assistant", "message": {"id": "G3", "usage": {"output_tokens": "42"}}},
        {"type": "assistant", "requestId": None},
        _assistant("OK", {"output_tokens": 9}, "end_turn"),
    ]
    # Runs without raising; every garbage record contributes zero to the totals.
    s = tu.summarize(records)
    assert s["output_tokens"] == 9
    assert s["input_tokens"] == 0
    assert s["cache_creation_input_tokens"] == 0
    assert s["cache_read_input_tokens"] == 0
    assert s["thinking_tokens"] is None


def test_token_total_rule():
    assert tu.token_total({"input": 100, "cache_write": 500, "output": 400, "source": "final"}) == 1000
    assert tu.token_total({"input": 10, "output": 5}) == 15
    assert tu.token_total(42) == 42
    assert tu.token_total(0) is None
    assert tu.token_total({"input": 0, "cache_write": 0, "output": 0, "source": "final"}) is None
    assert tu.token_total(None) is None
    assert tu.token_total("lots") is None
