"""test_dispatch_tasks.py — the interactive path writes one ndjson row per task attempt (G1).

design: run-throughput (seat ruling G1; PR #178 live check #2 item 7: `local-dispatch.md`
never called `dispatch_log.py`, so the interactive run left no `dispatch-telemetry.ndjson`).
A real ladder record is driven through `tier_ladder.py` (start → FAIL → PASS with scan and
poll evidence), then `dispatch_tasks.py` — §2 step 7's writer — turns it into rows.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import dispatch_log  # noqa: E402
import dispatch_report  # noqa: E402
import dispatch_tasks  # noqa: E402


def _cli(script: str, *args: str, cwd: Path, stdin: str | None = None) -> dict:
    proc = subprocess.run([sys.executable, str(HERE / script), *args], cwd=str(cwd), input=stdin,
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _write(path: Path, data) -> str:
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def _ladder(tmp_path: Path) -> Path:
    """A sonnet-medium record: FAIL (tokens 8/1511) → retry → PASS with no usage total."""
    rec = tmp_path / "1.2.json"
    _cli("tier_ladder.py", "start", "--task", "1.2", "--tier", "sonnet-medium", "--record",
         str(rec), "--root", str(tmp_path), cwd=tmp_path)
    scan1 = _write(tmp_path / "s1.json", {"flags": [], "tokens": {"input": 8, "output": 1511},
                                          "wall_s": 17.2})
    _cli("tier_ladder.py", "next", "--record", str(rec), "--outcome", "FAIL", "--reason",
         "red test", "--root", str(tmp_path), "--scan", scan1, cwd=tmp_path)
    scan2 = _write(tmp_path / "s2.json", {"flags": [], "wall_s": 9.0})
    out = _cli("tier_ladder.py", "next", "--record", str(rec), "--outcome", "PASS", "--root",
               str(tmp_path), "--scan", scan2, cwd=tmp_path)
    assert out["action"] == "done"
    return rec


def _rows(design: Path) -> list[dict]:
    text = (design / dispatch_log.NDJSON_NAME).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines()]


def test_interactive_record_yields_one_row_per_attempt_with_measurements(tmp_path):
    rec = _ladder(tmp_path)
    design = tmp_path / "design"
    design.mkdir()
    out = _cli("dispatch_tasks.py", "--design-dir", str(design), "--record", str(rec),
               "--phase", "1", cwd=tmp_path)
    assert out == {"written": 2, "skipped": 0}
    first, second = _rows(design)
    assert (first["role"], first["agent"], first["rung"], first["phase"]) == (
        "task", "tp-task-worker-sonnet-medium", "sonnet-medium", "1")
    assert (first["outcome"], first["served_by"], first["wall_s"]) == ("FAIL", "sonnet", 17.2)
    assert (first["tokens"], first["tokens_reason"]) == (1519, None)
    assert (second["outcome"], second["wall_s"], second["tokens"]) == ("PASS", 9.0, None)
    assert second["tokens_reason"]  # null with a reason, never 0


def test_rewriting_the_same_record_never_doubles_a_row(tmp_path):
    rec = _ladder(tmp_path)
    design = tmp_path / "design"
    design.mkdir()
    for _ in range(2):
        _cli("dispatch_tasks.py", "--design-dir", str(design), "--record", str(rec), cwd=tmp_path)
    tele = _cli("tier_ladder.py", "telemetry", "--record", str(rec), cwd=tmp_path)
    again = _cli("dispatch_tasks.py", "--design-dir", str(design), "--record", "-", cwd=tmp_path,
                 stdin=json.dumps(tele))  # the telemetry item keys the same attempts
    assert again == {"written": 0, "skipped": 2}
    assert len(_rows(design)) == 2


def test_live_check_local_verdict_row(tmp_path):
    """Live check #2 task 1.1 (scrubbed): a local PASS served by the local model."""
    record = {"task_id": "1.1", "route": "routed/ok", "final": "done", "verdicts": [
        {"rung": "local-medium", "tier": "local-medium", "outcome": "PASS", "model": "haiku",
         "why": "task_start", "served_by": "local", "wall_s": 78.2, "fingerprint": "pass||",
         "tokens": {"input": 17923, "output": 2924},
         "served": {"local_requests": 12, "turns": 10}}]}
    (row,) = dispatch_tasks.rows(record)
    assert (row["served_by"], row["tokens"], row["wall_s"], row["phase"]) == (
        "local", 20847, 78.2, "1")
    assert row["served"] == {"local_requests": 12, "turns": 10} and row["route"] == "routed/ok"


def test_unavailable_attempt_is_served_by_nobody(tmp_path):
    record = {"task_id": "2.1", "verdicts": [
        {"rung": "local-medium", "outcome": "unavailable", "served_by": None},
        {"rung": "bogus"}, "not-a-dict"]}
    (row,) = dispatch_tasks.rows(record)
    assert row["served_by"] is None and row["tokens"] is None and row["tokens_reason"]


def test_report_counts_an_attempt_once_from_ndjson_and_telemetry(tmp_path):
    rec = _ladder(tmp_path)
    design = tmp_path / "design"
    design.mkdir()
    _cli("dispatch_tasks.py", "--design-dir", str(design), "--record", str(rec), cwd=tmp_path)
    tele = {"task_tiers": [_cli("tier_ladder.py", "telemetry", "--record", str(rec), cwd=tmp_path)]}
    nd = design / dispatch_log.NDJSON_NAME
    table = dispatch_report.report(nd, tele)
    assert [r["count"] for r in table if r["role"] == "task"] == [2]
    assert dispatch_report.totals(nd, tele)["rung"]["sonnet-medium"]["count"] == 2
