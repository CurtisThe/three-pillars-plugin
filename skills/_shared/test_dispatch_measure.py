"""test_dispatch_measure.py — Decision 12 measurement fields and totals (operator ruling Q3).

design: run-throughput (Q3, PR #178 fix pass)

Behavior: a fixture ndjson row written by `dispatch_log.py record` round-trips with
`started_at`/`ended_at`/`wall_s`/`tokens`/`served_by`; `dispatch_report.totals` sums wall
and tokens per rung and per phase over ndjson rows plus ladder telemetry; a missing
token total stays null with a reason and is counted missing, never summed as 0.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import dispatch_log
import dispatch_report

CLI = Path(__file__).resolve().parent / "dispatch_log.py"


def _record(tmp_path, *args) -> dict:
    proc = subprocess.run([sys.executable, str(CLI), "record", "--design-dir", str(tmp_path),
                           "--root", str(tmp_path), *args], capture_output=True, text=True,
                          timeout=30)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_ndjson_row_round_trips_the_measurement_fields(tmp_path):
    printed = _record(tmp_path, "--role", "task", "--agent", "tp-task-worker-local-medium",
                      "--reason", "task_start", "--outcome", "PASS", "--rung", "local-medium",
                      "--phase", "2", "--started-at", "2026-09-28T10:00:00-06:00",
                      "--ended-at", "2026-09-28T16:01:30Z", "--tokens", "81234",
                      "--local-requests", "0")
    row = json.loads((tmp_path / dispatch_log.NDJSON_NAME).read_text(encoding="utf-8"))
    assert row == printed
    assert (row["started_at"], row["ended_at"], row["wall_s"]) == (
        "2026-09-28T16:00:00Z", "2026-09-28T16:01:30Z", 90.0)
    assert (row["tokens"], row["tokens_reason"]) == (81234, None)
    assert (row["served_by"], row["rung"], row["phase"]) == ("fallback", "local-medium", "2")


def test_missing_or_zero_tokens_stay_null_with_a_reason(tmp_path):
    none = _record(tmp_path, "--role", "generator", "--agent", "tp-generator", "--reason", "x",
                   "--outcome", "ok", "--wall-s", "12.5")
    zero = _record(tmp_path, "--role", "generator", "--inline", "--reason", "x", "--outcome",
                   "ok", "--tokens", "0", "--wall-s", "3")
    assert none["tokens"] is None and none["tokens_reason"] == "the spawn reported no usage total"
    assert zero["tokens"] is None and "never recorded as 0" in zero["tokens_reason"]
    assert (none["served_by"], zero["served_by"], zero["wall_s"]) == ("opus", "opus", 3.0)


def test_unknown_agent_is_logged_not_a_crash(tmp_path):
    rec = _record(tmp_path, "--role", "fix", "--agent", "general-purpose", "--reason", "x",
                  "--outcome", "ok")
    assert (rec["model"], rec["effort"]) == ("-", "-")


def test_report_sums_per_rung_and_phase_missing_tokens_counted(tmp_path):
    nd = tmp_path / dispatch_log.NDJSON_NAME
    rows = [{"role": "task", "agent": "tp-task-worker-opus-medium", "rung": "opus-medium",
             "phase": "1", "wall_s": 30.0, "tokens": 1000},
            {"role": "task", "agent": "tp-task-worker-opus-medium", "rung": "opus-medium",
             "phase": "2", "wall_s": 12.5, "tokens": None, "tokens_reason": "not reported"}]
    nd.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    telemetry = {"task_tiers": [{"task_id": "2.4", "verdicts": [
        {"rung": "local-medium", "outcome": "PASS", "wall_s": 40.0,
         "tokens": {"input": 300, "output": 200}}]}]}
    tot = dispatch_report.totals(nd, telemetry)
    assert tot["rung"]["opus-medium"] == {"count": 2, "wall_s": 42.5, "tokens": 1000,
                                          "tokens_missing": 1}
    assert tot["rung"]["local-medium"] == {"count": 1, "wall_s": 40.0, "tokens": 500,
                                           "tokens_missing": 0}
    assert tot["phase"]["2"] == {"count": 2, "wall_s": 52.5, "tokens": 500, "tokens_missing": 1}
    assert "| rung | opus-medium | 2 | 42.5 | 1000 | 1 |" in dispatch_report.render_totals(tot)
