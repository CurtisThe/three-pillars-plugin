"""Tests for review_prep_budget.py — cheap-tier-review-prep (Task 3.4).

All timing is driven through the `now` seam (no sleeps). Covers interval union
(overlap once, sequential add, gap not counted), `start` refusing at/after the
budget, `stop_batch` returning and persisting `late` flags, the three-unit +
120s-oracle scenario (D4), a never-stopped id reading late, and open intervals
ending at `now` in `spent`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import review_prep_budget as budget  # noqa: E402


def _work(tmp_path: Path) -> Path:
    work = tmp_path / "W"
    work.mkdir(parents=True, exist_ok=True)
    return work


def test_begin_writes_empty_budget(tmp_path):
    work = _work(tmp_path)
    budget.begin(work, now=0.0)
    data = json.loads((work / "budget.json").read_text(encoding="utf-8"))
    assert data == {"intervals": [], "sec": 300}


def test_sequential_intervals_add(tmp_path):
    work = _work(tmp_path)
    budget.begin(work, now=0.0)
    budget.start(work, "a", now=0.0)
    budget.stop_batch(work, ["a"], now=50.0)
    budget.start(work, "b", now=60.0)
    budget.stop_batch(work, ["b"], now=100.0)
    # union: [0,50] + [60,100] = 50 + 40 = 90
    assert budget.spent(work, now=100.0) == 90.0


def test_overlapping_intervals_count_once(tmp_path):
    work = _work(tmp_path)
    budget.begin(work, now=0.0)
    budget.start(work, "a", now=0.0)
    budget.start(work, "b", now=10.0)
    budget.stop_batch(work, ["a", "b"], now=60.0)
    # union of [0,60] and [10,60] is [0,60] = 60
    assert budget.spent(work, now=60.0) == 60.0


def test_gap_between_intervals_not_counted(tmp_path):
    work = _work(tmp_path)
    budget.begin(work, now=0.0)
    budget.start(work, "a", now=0.0)
    budget.stop_batch(work, ["a"], now=10.0)
    budget.start(work, "b", now=50.0)
    budget.stop_batch(work, ["b"], now=60.0)
    # union: [0,10] + [50,60] = 10 + 10 = 20, the [10,50] gap is not counted
    assert budget.spent(work, now=60.0) == 20.0


def test_open_interval_ends_at_now_in_spent(tmp_path):
    work = _work(tmp_path)
    budget.begin(work, now=0.0)
    budget.start(work, "a", now=0.0)
    # never stopped: spent should treat the interval as ending at `now`
    assert budget.spent(work, now=30.0) == 30.0


def test_start_refuses_at_budget_and_writes_no_interval(tmp_path):
    work = _work(tmp_path)
    budget.begin(work, now=0.0)
    budget.start(work, "a", now=0.0)
    budget.stop_batch(work, ["a"], now=300.0)
    before = json.loads((work / "budget.json").read_text(encoding="utf-8"))
    ok = budget.start(work, "b", now=300.0)
    assert ok is False
    after = json.loads((work / "budget.json").read_text(encoding="utf-8"))
    assert after["intervals"] == before["intervals"]


def test_start_refuses_after_budget(tmp_path):
    work = _work(tmp_path)
    budget.begin(work, now=0.0)
    budget.start(work, "a", now=0.0)
    budget.stop_batch(work, ["a"], now=400.0)
    assert budget.start(work, "b", now=400.0) is False


def test_stop_batch_returns_and_persists_flags(tmp_path):
    work = _work(tmp_path)
    budget.begin(work, now=0.0)
    budget.start(work, "a", now=0.0)
    budget.start(work, "b", now=0.0)
    result = budget.stop_batch(work, ["a", "b"], now=100.0)
    assert result == {"a": False, "b": False}
    assert budget.late(work, "a") is False
    assert budget.late(work, "b") is False


def test_batch_whose_union_passes_budget_is_late(tmp_path):
    work = _work(tmp_path)
    budget.begin(work, now=0.0)
    budget.start(work, "a", now=0.0)
    budget.start(work, "b", now=0.0)
    result = budget.stop_batch(work, ["a", "b"], now=301.0)
    assert result == {"a": True, "b": True}
    assert budget.late(work, "a") is True
    assert budget.late(work, "b") is True


def test_three_units_stop_batch_then_oracle_on_first_leaves_others_not_late(tmp_path):
    work = _work(tmp_path)
    budget.begin(work, now=0.0)
    budget.start(work, "a", now=0.0)
    budget.start(work, "b", now=0.0)
    budget.start(work, "c", now=0.0)
    result = budget.stop_batch(work, ["a", "b", "c"], now=200.0)
    assert result == {"a": False, "b": False, "c": False}

    # 120s oracle run on "a" happens after stop_batch: settle only reads `late`,
    # never reopens a clock, so it must not affect b/c or the recorded spend.
    assert budget.late(work, "b") is False
    assert budget.late(work, "c") is False
    assert budget.spent(work, now=320.0) == 200.0


def test_never_stopped_id_reads_late(tmp_path):
    work = _work(tmp_path)
    budget.begin(work, now=0.0)
    budget.start(work, "a", now=0.0)
    assert budget.late(work, "a") is True


def test_already_stopped_id_stays_unless_restopped(tmp_path):
    work = _work(tmp_path)
    budget.begin(work, now=0.0)
    budget.start(work, "a", now=0.0)
    budget.start(work, "b", now=0.0)
    budget.stop_batch(work, ["a"], now=50.0)
    assert budget.late(work, "a") is False
    # re-stop "a" alone at a time that would be late; only "a" is affected
    budget.start(work, "c", now=50.0)
    budget.stop_batch(work, ["c"], now=400.0)
    assert budget.late(work, "a") is False
    assert budget.late(work, "c") is True


def test_missing_budget_file_fails_safe(tmp_path):
    work = _work(tmp_path)
    assert budget.spent(work, now=10.0) == 300
    assert budget.start(work, "a", now=10.0) is False
    assert budget.late(work, "a") is True


def test_corrupt_budget_file_fails_safe(tmp_path):
    work = _work(tmp_path)
    (work / "budget.json").write_text("not json", encoding="utf-8")
    assert budget.spent(work, now=10.0) == 300
    assert budget.start(work, "a", now=10.0) is False
    assert budget.late(work, "a") is True
