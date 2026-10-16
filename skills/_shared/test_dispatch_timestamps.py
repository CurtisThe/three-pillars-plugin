"""started_at / ended_at on the task-attempt ndjson rows (run-throughput, operator ruling H2).

Real CLI flows: `attempt_scan.py scan` on a transcript → `tier_ladder.py start` / `next` →
`dispatch_tasks.py` (interactive) and `tier_ladder.py telemetry` → `write_task_tiers`
(nested, the `run_tier_3_5.py` writer). A scanned attempt spans its transcript; an attempt
with no scan spans the ladder's own step bracket; a pre-H2 record is null + `timing_reason`.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import dispatch_tasks  # noqa: E402

T0, T1 = "2026-09-28T15:00:00.000Z", "2026-09-28T15:01:41.700Z"  # a 101.7 s attempt


def _run(script: str, *args, stdin: str | None = None) -> str:
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_BASE_URL"}
    proc = subprocess.run([sys.executable, str(HERE / script), *args], input=stdin,
                          capture_output=True, text=True, timeout=60, env=env, check=True)
    return proc.stdout


def _epoch(stamp: str) -> float:
    assert stamp.endswith("Z"), stamp  # ISO UTC
    return datetime.datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()


def _rows(design_dir: Path) -> list[dict]:
    text = (design_dir / "dispatch-telemetry.ndjson").read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines()]


def _ladder_run(tmp_path: Path) -> Path:
    """start → FAIL (scanned transcript) → PASS (no scan): a two-attempt record."""
    transcript = tmp_path / "agent.jsonl"
    transcript.write_text("".join(json.dumps({"type": t, "timestamp": ts}) + "\n"
                                  for t, ts in (("user", T0), ("assistant", T1))),
                          encoding="utf-8")
    scan = tmp_path / "S.json"
    scan.write_text(_run("attempt_scan.py", "scan", "--path", str(transcript)), encoding="utf-8")
    rec, bare = tmp_path / "R.json", tmp_path / "bare"
    bare.mkdir()
    _run("tier_ladder.py", "start", "--task", "1.1", "--tier", "sonnet-medium", "--record",
         str(rec), "--root", str(bare))
    _run("tier_ladder.py", "next", "--record", str(rec), "--outcome", "FAIL", "--reason",
         "red test", "--scan", str(scan), "--root", str(bare))
    _run("tier_ladder.py", "next", "--record", str(rec), "--outcome", "PASS", "--root", str(bare))
    return rec


def _assert_timed(rows: list[dict]) -> None:
    scanned, bracketed = rows
    assert (_epoch(scanned["started_at"]), _epoch(scanned["ended_at"])) == (_epoch(T0), _epoch(T1))
    assert scanned["wall_s"] == 101.7  # the scan's own wall_s, spanning the same stamps
    for row in rows:
        assert row["timing_reason"] is None
        assert _epoch(row["started_at"]) <= _epoch(row["ended_at"])
        assert row["wall_s"] == round(_epoch(row["ended_at"]) - _epoch(row["started_at"]), 1)
    # the unscanned retry spans the ladder's bracket: the FAIL step → the PASS step
    assert _epoch(bracketed["started_at"]) > _epoch(T1)


def test_interactive_rows_carry_the_attempt_span(tmp_path):
    rec = _ladder_run(tmp_path)
    design = tmp_path / "design"
    design.mkdir()
    out = _run("dispatch_tasks.py", "--design-dir", str(design), "--record", str(rec),
               "--phase", "1")
    assert json.loads(out) == {"written": 2, "skipped": 0}
    _assert_timed(_rows(design))


def test_nested_rows_from_task_tiers_match_and_replay_adds_none(tmp_path):
    rec = _ladder_run(tmp_path)
    item = json.loads(_run("tier_ladder.py", "telemetry", "--record", str(rec)))
    nested, interactive = tmp_path / "nested", tmp_path / "interactive"
    nested.mkdir(), interactive.mkdir()

    assert dispatch_tasks.write_task_tiers(nested, {"task_tiers": [item]})["written"] == 2
    _assert_timed(_rows(nested))
    dispatch_tasks.write(interactive, [json.loads(rec.read_text(encoding="utf-8"))])
    assert _rows(nested) == _rows(interactive)  # one attempt, one key, either writer
    assert dispatch_tasks.write_task_tiers(nested, {"task_tiers": [item]}) == {
        "written": 0, "skipped": 2}


def test_pre_h2_record_is_null_with_a_reason_and_keeps_its_key(tmp_path):
    verdict = {"rung": "sonnet-medium", "outcome": "PASS", "fingerprint": "f", "wall_s": None,
               "tokens": None, "served_by": "sonnet", "model": "sonnet", "why": "task_start"}
    legacy = {"task_id": "2.1", "route": "routed/ok", "verdicts": [verdict]}
    (row,) = dispatch_tasks.rows(legacy)

    assert (row["started_at"], row["ended_at"], row["wall_s"]) == (None, None, None)
    assert row["timing_reason"] == dispatch_tasks.NO_STAMPS
    basis = ["2.1", 0, "sonnet-medium", "PASS", "f", None, None]  # the pre-H2 key basis
    want = hashlib.sha256(json.dumps(basis, sort_keys=True, default=str).encode()).hexdigest()
    assert row["attempt_key"] == want[:16]  # a replayed legacy record still dedups


def test_pre_h2_record_stepped_by_the_new_cli_has_no_start_and_says_so(tmp_path):
    rec, bare = tmp_path / "R.json", tmp_path / "bare"
    bare.mkdir()
    _run("tier_ladder.py", "start", "--task", "3.1", "--tier", "sonnet-medium", "--record",
         str(rec), "--root", str(bare))
    data = json.loads(rec.read_text(encoding="utf-8"))
    del data["stepped_at"]  # a record `start`ed before H2
    rec.write_text(json.dumps(data), encoding="utf-8")
    _run("tier_ladder.py", "next", "--record", str(rec), "--outcome", "PASS", "--root", str(bare))

    (row,) = dispatch_tasks.rows(json.loads(rec.read_text(encoding="utf-8")))
    assert row["started_at"] is None and row["ended_at"].endswith("Z")
    assert row["wall_s"] is None
    # the end is stamped, so the reason must not claim "no timestamps": it names the missing start
    assert row["timing_reason"] == dispatch_tasks.NO_START != dispatch_tasks.NO_STAMPS


def test_a_redispatched_evidence_free_attempt_is_its_own_row(tmp_path):
    def record(started: str) -> dict:
        v = {"rung": "local-medium", "outcome": "FAIL", "fingerprint": "f", "wall_s": None,
             "tokens": None, "started_at": started, "ended_at": started}
        return {"task_id": "4.1", "route": "routed/ok", "verdicts": [v]}

    first, again = record("2026-09-28T15:00:00Z"), record("2026-09-28T16:00:00Z")
    assert dispatch_tasks.write(tmp_path, [first]) == {"written": 1, "skipped": 0}
    assert dispatch_tasks.write(tmp_path, [again]) == {"written": 1, "skipped": 0}
    assert dispatch_tasks.write(tmp_path, [first, again]) == {"written": 0, "skipped": 2}
