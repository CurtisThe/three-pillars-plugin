"""H2 stamps only attempts that ran (run-throughput, PR #178 round-4 notes).

An `unavailable` or `agent-unresolved:` env-error attempt never spawned, so its ndjson row
must carry no span and no `wall_s` (the report would credit the rung with time it never
ran) and a `timing_reason` that says so. A scan of a transcript with no timestamps reports
no `wall_s` either, so the row's `wall_s` is derived from the same bracket its stamps span.
"""
from __future__ import annotations

import datetime
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import dispatch_report  # noqa: E402
import dispatch_tasks  # noqa: E402


def _run(script: str, *args: str) -> str:
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_BASE_URL"}
    return subprocess.run([sys.executable, str(HERE / script), *args], capture_output=True,
                          text=True, timeout=60, env=env, check=True).stdout


def _ladder(tmp_path: Path, *outcomes: tuple[str, ...]) -> list[dict]:
    """start sonnet-medium, feed each ``(outcome, *extra_args)``; → the record's ndjson rows."""
    rec, bare = tmp_path / "R.json", tmp_path / "bare"
    bare.mkdir()
    _run("tier_ladder.py", "start", "--task", "1.1", "--tier", "sonnet-medium", "--record",
         str(rec), "--root", str(bare))
    for outcome, *extra in outcomes:
        _run("tier_ladder.py", "next", "--record", str(rec), "--root", str(bare),
             "--outcome", outcome, *extra)
    return dispatch_tasks.rows(json.loads(rec.read_text(encoding="utf-8")))


def _assert_unspawned(row: dict) -> None:
    assert (row["started_at"], row["ended_at"], row["wall_s"]) == (None, None, None)
    assert row["served_by"] is None
    assert row["timing_reason"] == dispatch_tasks.NEVER_SPAWNED


def test_unavailable_attempt_carries_no_span_but_the_retry_does(tmp_path):
    unavailable, ran = _ladder(tmp_path, ("unavailable",), ("PASS",))
    _assert_unspawned(unavailable)
    assert ran["timing_reason"] is None and ran["started_at"] and ran["ended_at"]
    assert ran["wall_s"] is not None and ran["wall_s"] >= 0


def test_agent_unresolved_env_error_carries_no_span(tmp_path):
    (row,) = _ladder(tmp_path, ("env-error", "--reason", "agent-unresolved: tp-task-worker-x"))
    _assert_unspawned(row)


def test_report_credits_no_wall_time_to_a_rung_that_never_ran(tmp_path):
    rows = _ladder(tmp_path, ("unavailable",), ("PASS",))
    ndjson = tmp_path / "dispatch-telemetry.ndjson"
    ndjson.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    by_rung = dispatch_report.totals(ndjson)["rung"]
    unavailable, ran = rows
    assert by_rung[unavailable["rung"]]["count"] >= 1
    credited = round(sum(row["wall_s"] for row in by_rung.values()), 1)
    assert credited == ran["wall_s"]  # only the attempt that ran contributes wall time


def test_scan_of_a_transcript_without_timestamps_has_no_wall_s_and_a_consistent_row(tmp_path):
    transcript = tmp_path / "agent.jsonl"
    transcript.write_text(json.dumps({"type": "user"}) + "\n", encoding="utf-8")
    scan = tmp_path / "S.json"
    scan.write_text(_run("attempt_scan.py", "scan", "--path", str(transcript)), encoding="utf-8")
    assert json.loads(scan.read_text(encoding="utf-8"))["wall_s"] is None

    (row,) = _ladder(tmp_path, ("PASS", "--scan", str(scan)))
    span = _epoch(row["ended_at"]) - _epoch(row["started_at"])
    assert row["wall_s"] == round(span, 1)  # never 0.0 beside a stamped span
    assert row["timing_reason"] is None


def _epoch(stamp: str) -> float:
    return datetime.datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
