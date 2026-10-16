"""test_dispatch_tasks_fallback.py — fallback cause and lease wait ride onto the task rows.

design: cheap-tier-local-routing (task 3.2; detailed-design §Interfaces, §Notes 1)

A ladder verdict's ``reason`` (never ``why``: that stays the row's ``reason`` field) maps through
``served_rung.FALLBACKS`` (a ``runaway:`` prefix -> ``runaway``) to the row's ``fallback``, set
only for an ``unavailable`` / ``env-error`` outcome or a listed cause. ``lease_wait_s`` is copied
when the verdict carries it, through ``ladder_entry.to_telemetry`` too (the fleet path).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import dispatch_log  # noqa: E402
import dispatch_tasks  # noqa: E402
import ladder_entry  # noqa: E402


def _verdict(outcome: str, reason: str = "", **extra) -> dict:
    return {"tier": "sonnet-medium", "rung": "sonnet-medium", "outcome": outcome,
            "reason": reason, "class": "", "fingerprint": "", "stuck": None, "flags": [],
            "tokens": None, "wall_s": 12.0, "started_at": None, "ended_at": None, **extra}


def _record(*verdicts: dict) -> dict:
    return {"task_id": "3.2", "final": None, "tier_path": ["sonnet-medium"],
            "attempts": {"sonnet-medium": len(verdicts)}, "escalated": False,
            "verdicts": list(verdicts), "route": "sonnet-medium"}


def _row(verdict: dict) -> dict:
    (row,) = dispatch_tasks.rows(_record(verdict))
    return row


def _fleet_rows(tmp_path: Path, *verdicts: dict) -> list[dict]:
    """The fleet path: a ladder record -> ``to_telemetry`` -> ``write_task_tiers`` -> the ndjson."""
    item = ladder_entry.to_telemetry(_record(*verdicts))
    out = dispatch_tasks.write_task_tiers(tmp_path, {"task_tiers": [item]})
    assert out["written"] == len(verdicts)
    text = (tmp_path / dispatch_log.NDJSON_NAME).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines()]


def test_unavailable_local_busy_is_the_rows_fallback():
    assert _row(_verdict("unavailable", "local-busy"))["fallback"] == "local-busy"


def test_measure_variant_keeps_its_own_label():
    row = _row(_verdict("unavailable", "local-busy-measure"))
    assert row["fallback"] == "local-busy-measure"


def test_runaway_fail_with_a_wall_clock_reason_maps_to_runaway():
    row = _row(_verdict("FAIL", "runaway: wall-clock 1207s ≥ 1200s"))
    assert row["fallback"] == "runaway"


def test_a_listed_cause_on_a_fail_is_the_fallback():
    assert _row(_verdict("FAIL", "watchdog-error"))["fallback"] == "watchdog-error"


def test_unavailable_with_an_unlisted_reason_is_unrecorded():
    assert _row(_verdict("unavailable", "no such slot"))["fallback"] == "unrecorded"


def test_env_error_without_a_listed_reason_is_unrecorded():
    row = _row(_verdict("env-error", "agent-unresolved: tp-task-worker-x"))
    assert row["fallback"] == "unrecorded"


def test_a_passing_retry_has_no_fallback_and_keeps_why_as_its_reason():
    row = _row(_verdict("PASS", "", why="retry"))
    assert "fallback" not in row
    assert row["reason"] == "retry"


def test_a_pass_with_a_free_text_reason_has_no_fallback():
    assert "fallback" not in _row(_verdict("PASS", "ok"))


def test_why_never_feeds_the_fallback():
    row = _row(_verdict("FAIL", "red test", why="local-busy"))
    assert "fallback" not in row and row["reason"] == "local-busy"


def test_lease_wait_s_is_copied_onto_the_row():
    assert _row(_verdict("PASS", "ok", lease_wait_s=240))["lease_wait_s"] == 240


def test_a_verdict_without_lease_wait_s_adds_no_key():
    row = _row(_verdict("PASS", "ok"))
    assert "lease_wait_s" not in row and "fallback" not in row


def test_fleet_path_keeps_lease_wait_s_and_fallback(tmp_path):
    busy, ran = _fleet_rows(tmp_path, _verdict("unavailable", "local-busy", lease_wait_s=240.0),
                            _verdict("PASS", "ok", why="fallback"))
    assert (busy["fallback"], busy["lease_wait_s"]) == ("local-busy", 240.0)
    assert "fallback" not in ran and "lease_wait_s" not in ran


def test_to_telemetry_copies_lease_wait_s_only_when_the_verdict_has_a_value():
    with_wait = ladder_entry.to_telemetry(_record(_verdict("PASS", "ok", lease_wait_s=240.0)))
    assert with_wait["verdicts"][0]["lease_wait_s"] == 240.0
    for v in (_verdict("PASS", "ok"), _verdict("PASS", "ok", lease_wait_s=None)):
        assert "lease_wait_s" not in ladder_entry.to_telemetry(_record(v))["verdicts"][0]


def test_an_old_verdict_gives_todays_telemetry_shape():
    old = {"tier": "sonnet-medium", "rung": "sonnet-medium", "outcome": "PASS", "reason": "ok"}
    tele = ladder_entry.to_telemetry(_record(old))["verdicts"][0]
    assert "lease_wait_s" not in tele
    assert tele["stuck"] is None and tele["served_by"] is None
