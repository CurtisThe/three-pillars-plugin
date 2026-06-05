"""Tests for `eval/comments.jsonl` — the curated eval set for judge-prompt iteration.

Structural assertions only — these guard the file shape, not the labels.
Label quality is gated by human review at curation time (Phase 8.1) and
empirically measured by `eval/run_eval.py` against the live judge (Phase 8.2).

Run with: pytest skills/tp-pr-iterate/scripts/test_eval_set.py -q
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

EVAL_PATH = (
    Path(__file__).parent.parent / "eval" / "comments.jsonl"
)

REQUIRED_FIELDS = {
    "comment_id",
    "body",
    "diff_hunk",
    "ground_truth",
    "source_repo",
    "source_pr_url",
}

VALID_LABELS = {"structural", "minor", "unclear"}


def _read_entries() -> list[dict]:
    if not EVAL_PATH.exists():
        pytest.fail(f"eval file missing: {EVAL_PATH}")
    lines = EVAL_PATH.read_text().splitlines()
    entries: list[dict] = []
    for i, raw in enumerate(lines, start=1):
        if not raw.strip():
            continue
        try:
            entries.append(json.loads(raw))
        except json.JSONDecodeError as e:
            pytest.fail(f"line {i} not valid JSON: {e}")
    return entries


def test_has_at_least_20_entries() -> None:
    entries = _read_entries()
    assert len(entries) >= 20, (
        f"eval/comments.jsonl has {len(entries)} entries; need ≥ 20 for calibration"
    )


def test_each_entry_has_required_fields() -> None:
    entries = _read_entries()
    for i, entry in enumerate(entries, start=1):
        missing = REQUIRED_FIELDS - set(entry.keys())
        assert not missing, f"entry {i} missing fields: {missing}"


def test_ground_truth_label_in_valid_set() -> None:
    entries = _read_entries()
    for i, entry in enumerate(entries, start=1):
        gt = entry.get("ground_truth")
        assert gt in VALID_LABELS, (
            f"entry {i} ground_truth={gt!r} not in {VALID_LABELS}"
        )
