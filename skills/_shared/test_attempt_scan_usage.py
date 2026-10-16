"""Tests for attempt_scan.py — scan()'s final-usage `tokens` (task 1.3)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import attempt_scan  # noqa: E402

FIXTURE = HERE / "fixtures" / "transcript_usage" / "agent-mixed.jsonl"
CASES = HERE / "fixtures" / "attempt_scan" / "transcripts.json"


def test_scan_tokens_is_full_breakdown_with_source_and_legacy():
    out = attempt_scan.scan(FIXTURE)
    tokens = out["tokens"]
    assert set(tokens) == {"input", "output", "cache_write", "cache_read",
                           "thinking", "source", "legacy"}
    assert tokens["output"] == 2803 == tokens["legacy"]["output"]  # unchanged, by design
    assert tokens["cache_write"] == 4700  # includes D's 700 and E's 400
    assert tokens["cache_read"] == 50000  # includes E's 18000
    assert tokens["thinking"] == 1210
    assert tokens["source"] == "mixed"
    assert tokens["legacy"] == {"input": 14, "output": 2803}  # the pre-change {input, output}


def test_scan_tokens_sum_exceeds_legacy_sum():
    # The discriminating assertion: the cache breakdown adds tokens the legacy
    # two-field total never saw.
    tokens = attempt_scan.scan(FIXTURE)["tokens"]
    assert tokens["input"] + tokens["cache_write"] + tokens["output"] > \
        tokens["legacy"]["input"] + tokens["legacy"]["output"]


def test_scan_keeps_existing_fixture_case_flags_exactly():
    name = "identical_calls_total_5"
    records = json.loads(CASES.read_text(encoding="utf-8"))["cases"][name]
    path = HERE / f".attempt_scan_usage_{name}.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    try:
        out = attempt_scan.scan(path)
        assert out["flags"] == ["identical-calls 5x Bash"]
    finally:
        path.unlink(missing_ok=True)
