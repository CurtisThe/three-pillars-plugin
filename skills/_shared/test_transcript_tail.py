"""Tests for transcript_tail.py — turns and the end-of-turn predicate (run-throughput 1.2)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import transcript_tail as tt  # noqa: E402

CASES = json.loads((HERE / "fixtures" / "transcript_tail" / "tails.json").read_text(encoding="utf-8"))["cases"]


def _write(tmp_path, records, extra_lines=()):
    path = tmp_path / "agent-x.jsonl"
    lines = [json.dumps(r) for r in records] + list(extra_lines)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_end_turn_with_trailing_system_records_is_the_final_turn(tmp_path):
    records = tt.read_records(_write(tmp_path, CASES["end_turn_trailing"]))
    final = tt.end_of_turn(records)
    assert final is not None
    assert final["id"] == "msg_0002"
    assert final["stop_reason"] == "end_turn"
    assert final["text"] == '{"claimed": "done"}'
    assert final["ts_last"] == "2026-09-28T15:00:18.400Z"
    assert final["has_tool_use"] is False


def test_split_blocks_of_one_reply_are_one_turn(tmp_path):
    records = tt.read_records(_write(tmp_path, CASES["split_reply"]))
    all_turns = tt.turns(records)
    assert len(all_turns) == 1
    turn = all_turns[0]
    assert turn["output_tokens"] == 95
    assert turn["stop_reason"] == "end_turn"
    assert turn["text"] == "part one part two"
    assert tt.end_of_turn(records)["id"] == "msg_0003"


def test_two_block_tool_reply_counts_one_request(tmp_path):
    records = tt.read_records(_write(tmp_path, CASES["end_turn_trailing"]))
    all_turns = tt.turns(records)
    assert [t["id"] for t in all_turns] == ["msg_0001", "msg_0002"]
    assert all_turns[0]["has_tool_use"] is True
    assert all_turns[0]["stop_reason"] == "tool_use"


def test_tool_use_after_end_turn_is_not_done():
    assert tt.end_of_turn(CASES["tool_use_after_end_turn"]) is None


def test_user_after_end_turn_is_not_done():
    assert tt.end_of_turn(CASES["user_after_end_turn"]) is None


def test_mid_tool_call_is_not_done():
    assert tt.end_of_turn(CASES["mid_tool_call"]) is None


def test_undecodable_lines_are_skipped(tmp_path):
    path = _write(tmp_path, CASES["end_turn_trailing"], extra_lines=["{not json", "[1, 2]"])
    with open(path, "ab") as fh:
        fh.write(b"\xff\xfe broken\n")
    records = tt.read_records(path)
    assert len(records) == len(CASES["end_turn_trailing"])
    assert tt.end_of_turn(records)["id"] == "msg_0002"


def test_empty_and_no_assistant():
    assert tt.turns([]) == []
    assert tt.end_of_turn([]) is None
    assert tt.end_of_turn([{"type": "user"}, {"type": "system"}]) is None


def test_request_id_fallback_groups_records():
    recs = [{"type": "assistant", "requestId": "req_1",
             "message": {"stop_reason": None, "usage": {"output_tokens": 3}, "content": []}},
            {"type": "assistant", "requestId": "req_1",
             "message": {"stop_reason": "end_turn", "usage": {"output_tokens": 7},
                         "content": [{"type": "text", "text": "ok"}]}}]
    all_turns = tt.turns(recs)
    assert len(all_turns) == 1 and all_turns[0]["output_tokens"] == 7
    assert tt.end_of_turn(recs)["text"] == "ok"


def test_module_is_small():
    assert len((HERE / "transcript_tail.py").read_text(encoding="utf-8").splitlines()) <= 100
