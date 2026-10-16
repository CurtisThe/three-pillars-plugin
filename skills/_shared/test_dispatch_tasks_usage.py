"""test_dispatch_tasks_usage.py — task-attempt rows total the final usage and mark its source.

design: task-worker-sonnet (task 1.4)

A verdict whose `tokens` is the Task 1.3 dict (`attempt_scan`'s final-usage breakdown) gives a
row with the cumulative `input + cache_write + output` total, the usage breakdown, the source and
the legacy two-field total. An old-shape verdict row keeps its value, with the new keys null.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import dispatch_log  # noqa: E402
import dispatch_tasks  # noqa: E402
import transcript_usage  # noqa: E402

NEW_TOKENS = {"input": 14, "output": 2803, "cache_write": 4700, "cache_read": 50000,
              "thinking": 1210, "source": "mixed", "legacy": {"input": 14, "output": 2803}}


def _row(tokens, **extra) -> dict:
    verdict = {"rung": "sonnet-medium", "outcome": "PASS", "served_by": "sonnet",
               "wall_s": 12.0, "fingerprint": "pass||", **extra}
    if tokens != "absent":
        verdict["tokens"] = tokens
    (row,) = dispatch_tasks.rows({"task_id": "1.4", "verdicts": [verdict]})
    return row


def test_new_shape_verdict_totals_input_cache_write_and_output():
    row = _row(NEW_TOKENS)
    assert row["tokens"] == 14 + 4700 + 2803 == 7517  # cache_read and thinking never added
    assert row["tokens_reason"] is None
    assert row["usage"] == {"input_tokens": 14, "cache_creation_input_tokens": 4700,
                            "cache_read_input_tokens": 50000, "output_tokens": 2803,
                            "thinking_tokens": 1210}
    assert row["usage_source"] == "mixed"
    assert row["tokens_legacy"] == 14 + 2803 == 2817


def test_old_shape_verdict_row_is_unchanged_with_new_keys_null():
    row = _row({"input": 8, "output": 1511})
    assert row["tokens"] == 1519 and row["tokens_reason"] is None
    assert (row["usage"], row["usage_source"], row["tokens_legacy"]) == (None, None, None)


def test_verdict_with_no_tokens_is_null_with_a_reason_never_zero():
    for row in (_row("absent"), _row(None)):
        assert row["tokens"] is None and row["tokens_reason"]
        assert (row["usage"], row["usage_source"], row["tokens_legacy"]) == (None, None, None)


def test_zero_token_dict_is_null_with_a_reason():
    row = _row({"input": 0, "output": 0})
    assert row["tokens"] is None and row["tokens_reason"]
    assert row["usage"] is None and row["usage_source"] is None


def test_plain_int_verdict_tokens_stay_an_old_shape_total():
    row = _row(900)
    assert row["tokens"] == 900 and row["usage_source"] is None and row["usage"] is None


def test_tokens_helper_is_the_one_transcript_usage_rule():
    assert dispatch_tasks._tokens(NEW_TOKENS) == transcript_usage.token_total(NEW_TOKENS) == 7517
    assert dispatch_tasks._tokens({"input": 0, "output": 0}) is None  # 0 is never a total


def test_attempt_key_still_hashes_the_verdicts_tokens_value(tmp_path):
    verdict = {"rung": "sonnet-medium", "outcome": "PASS", "fingerprint": "pass||",
               "wall_s": 12.0, "tokens": NEW_TOKENS}
    other = {**verdict, "tokens": {**NEW_TOKENS, "output": 2804}}
    assert (dispatch_tasks.attempt_key("1.4", 0, verdict)
            != dispatch_tasks.attempt_key("1.4", 0, other))
    record = {"task_id": "1.4", "verdicts": [verdict]}
    design = tmp_path / "design"
    design.mkdir()
    assert dispatch_tasks.write(design, [record]) == {"written": 1, "skipped": 0}
    telemetry = {"task_tiers": [json.loads(json.dumps(record))]}  # a re-fed envelope
    assert dispatch_tasks.write_task_tiers(design, telemetry) == {"written": 0, "skipped": 1}
    (line,) = (design / dispatch_log.NDJSON_NAME).read_text(encoding="utf-8").splitlines()
    assert json.loads(line)["usage_source"] == "mixed"
