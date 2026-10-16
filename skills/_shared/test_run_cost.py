#!/usr/bin/env python3
"""test_run_cost.py — per-run cost breakdown at API-equivalent prices.

design: strata-spend-leaks (Task 3.3)

The seed's investigation scripts were not kept, so `run_cost.py` is the kept
script: what a design run cost, per role, from its transcripts. These tests pin
the seed weights (Opus $5 in / $25 out per Mtok, Sonnet $3 / $15, cache write
1.25x input, 1h cache write 2x, cache read 0.1x input, a local model $0), the
cache-expiry waste (a cache write after the 5-minute TTL has lapsed re-wrote
tokens already paid for), the per-role buckets over the main transcript and its
subagents, and that the transcript reader is an injectable seam.
"""
from __future__ import annotations

import json

import pytest

import run_cost


def usage(**fields):
    """A usage dict with only the fields the test names."""
    return dict(fields)


def turn(model, at, **fields):
    """One final assistant record: `model`, ISO `at`, and its usage fields."""
    return {"type": "assistant", "timestamp": at,
            "message": {"id": "msg_" + at, "model": model, "role": "assistant",
                        "stop_reason": "end_turn", "content": [],
                        "usage": usage(**fields)}}


# ---------------------------------------------------------------------------
# the seed weights
# ---------------------------------------------------------------------------


def test_opus_prices():
    """1M Opus input -> $5.00, output -> $25.00, cache read -> $0.50, and a
    5-minute cache write is 1.25x input -> $6.25."""
    assert run_cost.message_cost("claude-opus-4-8", usage(input_tokens=1_000_000)) == 5.00
    assert run_cost.message_cost("opus", usage(output_tokens=1_000_000)) == 25.00
    assert run_cost.message_cost("opus", usage(cache_read_input_tokens=1_000_000)) == 0.50
    assert run_cost.message_cost(
        "opus", usage(cache_creation_input_tokens=1_000_000)) == 6.25
    # a mixed turn prices each field on its own weight
    assert run_cost.message_cost("opus", usage(
        input_tokens=100_000, cache_creation_input_tokens=200_000,
        cache_read_input_tokens=700_000, output_tokens=5_000)) == pytest.approx(
            0.1 * 5 + 0.2 * 5 * 1.25 + 0.7 * 5 * 0.1 + 0.005 * 25)


def test_sonnet_prices():
    """1M Sonnet input -> $3.00, output -> $15.00, cache read -> $0.30, 5m cache
    write -> $3.75."""
    assert run_cost.message_cost("sonnet", usage(input_tokens=1_000_000)) == 3.00
    assert run_cost.message_cost("claude-sonnet-4-5", usage(output_tokens=1_000_000)) == 15.00
    assert run_cost.message_cost("sonnet", usage(cache_read_input_tokens=1_000_000)) == 0.30
    assert run_cost.message_cost(
        "sonnet", usage(cache_creation_input_tokens=1_000_000)) == 3.75


def test_local_model_costs_zero():
    """Strata / any non-Claude family is $0 — the GPU was paid for already."""
    for model in ("strata", "qwen3-coder", "local-xhigh", "local-medium", ""):
        assert run_cost.message_cost(model, usage(
            input_tokens=1_000_000, cache_creation_input_tokens=1_000_000,
            cache_read_input_tokens=1_000_000, output_tokens=1_000_000)) == 0.0


def test_one_hour_cache_write_is_double():
    """`usage.cache_creation.ephemeral_1h_input_tokens` prices at 2x input and the
    rest of the write at 1.25x; with no breakdown the whole write is 1.25x."""
    assert run_cost.message_cost(
        "opus", usage(cache_creation_input_tokens=1_000_000,
                      cache_creation={"ephemeral_1h_input_tokens": 1_000_000})) == 10.00
    assert run_cost.message_cost(
        "opus", usage(cache_creation_input_tokens=1_000_000,
                      cache_creation={"ephemeral_1h_input_tokens": 400_000})) == pytest.approx(
                          0.6 * 5 * 1.25 + 0.4 * 5 * 2.0)
    assert run_cost.message_cost(
        "opus", usage(cache_creation_input_tokens=1_000_000)) == 6.25


# ---------------------------------------------------------------------------
# the cache-expiry waste
# ---------------------------------------------------------------------------


def test_expiry_waste_counts_cache_writes_after_ttl_gap():
    """Two Opus turns 301 s apart: the second's 100k cache write re-wrote a prefix
    whose TTL had lapsed, so it is $0.625 of waste. 299 s apart -> $0."""
    far = [turn("opus", "2026-10-13T10:00:00.000Z", cache_creation_input_tokens=10_000),
           turn("opus", "2026-10-13T10:05:01.000Z", cache_creation_input_tokens=100_000)]
    near = [turn("opus", "2026-10-13T10:00:00.000Z", cache_creation_input_tokens=10_000),
            turn("opus", "2026-10-13T10:04:59.000Z", cache_creation_input_tokens=100_000)]
    assert run_cost.expiry_waste(far) == pytest.approx(0.625)
    assert run_cost.expiry_waste(near) == 0.0
    # a local model's re-write is not Claude spend, so it is not waste either
    local = [turn("strata", "2026-10-13T10:00:00.000Z", cache_creation_input_tokens=10_000),
             turn("strata", "2026-10-13T10:20:00.000Z", cache_creation_input_tokens=100_000)]
    assert run_cost.expiry_waste(local) == 0.0


# ---------------------------------------------------------------------------
# the run breakdown
# ---------------------------------------------------------------------------


def _write_agent(dir_, stem, agent_type, records):
    """One subagent transcript plus its sibling `.meta.json`, as on disk."""
    (dir_ / (stem + ".jsonl")).write_text("".join(
        json.dumps(rec) + "\n" for rec in records), encoding="utf-8")
    if agent_type is not None:
        (dir_ / (stem + ".meta.json")).write_text(
            json.dumps({"agentType": agent_type}), encoding="utf-8")
    return dir_ / (stem + ".jsonl")


def test_breakdown_buckets_main_and_subagents_by_role(tmp_path):
    """One main transcript and two subagents bucket as `orchestrator`, `tp-worker`
    and `tp-task-worker`, and the buckets sum to the total."""
    main = tmp_path / "main.jsonl"
    main.write_text(json.dumps(turn(
        "opus", "2026-10-13T10:00:00.000Z", input_tokens=1_000_000)) + "\n", encoding="utf-8")
    subs = tmp_path / "subagents"
    subs.mkdir()
    worker = turn("sonnet", "2026-10-13T10:01:00.000Z", output_tokens=1_000_000)
    task = turn("opus", "2026-10-13T10:02:00.000Z", input_tokens=100_000,
                output_tokens=100_000)
    paths = [_write_agent(subs, "agent-1", "tp-worker", [worker]),
             _write_agent(subs, "agent-2", "tp-task-worker", [task])]

    result = run_cost.breakdown(main, paths)

    assert result["roles"] == {"orchestrator": 5.0, "tp-worker": 15.0,
                               "tp-task-worker": 3.0}
    assert result["total"] == pytest.approx(sum(result["roles"].values()))
    assert result["turns"] == 3
    assert set(result) >= {"total", "roles", "cache_expiry_waste", "turns"}
    # with no meta file the role falls back to the transcript's file stem
    no_meta = _write_agent(subs, "bare-transcript", None, [worker])
    assert run_cost.breakdown(main, [no_meta])["roles"]["bare-transcript"] == 15.0


def test_reader_seam_is_injectable(tmp_path):
    """`reader` replaces the transcript reader; a canned record set still dedupes
    the streamed snapshot + final pair sharing one `message.id`."""
    seen = []

    def reader(path):
        seen.append(str(path))
        return [
            {"type": "assistant", "timestamp": "2026-10-13T10:00:00.000Z",
             "message": {"id": "m1", "model": "opus", "role": "assistant",
                         "usage": {"input_tokens": 10, "output_tokens": 1}}},
            {"type": "assistant", "timestamp": "2026-10-13T10:00:01.000Z",
             "message": {"id": "m1", "model": "opus", "role": "assistant",
                         "stop_reason": "end_turn",
                         "usage": {"input_tokens": 1_000_000, "output_tokens": 90}}},
        ]

    main = tmp_path / "main.jsonl"
    result = run_cost.breakdown(main, [], reader=reader)
    assert seen == [str(main)]
    assert result["turns"] == 1
    assert result["total"] == pytest.approx(5.0 + 90 * 25 / 1_000_000)
