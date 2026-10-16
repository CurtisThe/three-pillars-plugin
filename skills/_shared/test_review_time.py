"""review_time.py — implementation vs review wall time (review-convergence 9.3, §D8).

Fixture telemetry + round manifests: sums from `dispatch-telemetry.ndjson` rows with a
non-null phase, and per-round review walls from `angles.json` `started_at` to the latest
mtime in `tail/`. mtimes are set with os.utime from the same epoch the manifest's
`started_at` was written from, so the expected seconds are exact.
"""
from __future__ import annotations

import datetime
import json
import os
import sys
from datetime import timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import review_time  # noqa: E402

# Two round brackets with exact expected walls: r1 = 100 s, r2 = 50 s.
T0 = 1_760_000_000.0


def _iso(epoch: float) -> str:
    return datetime.datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


def _telemetry(design_dir: Path, rows: list[dict]) -> None:
    design_dir.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(r) for r in rows]
    lines.append("")  # a blank line is skipped
    (design_dir / "dispatch-telemetry.ndjson").write_text("\n".join(lines), encoding="utf-8")


def _round(proof_root: Path, pr: int, ordinal: str, started: float, tail_last: float) -> None:
    rdir = proof_root / "rounds" / str(pr) / ordinal
    rdir.mkdir(parents=True, exist_ok=True)
    (rdir / "angles.json").write_text(
        json.dumps({"started_at": _iso(started), "head_sha": "abc123"}), encoding="utf-8")
    tail = rdir / "tail"
    tail.mkdir(exist_ok=True)
    (tail / "findings.json").write_text("[]", encoding="utf-8")
    (tail / "log.jsonl").write_text("{}\n", encoding="utf-8")
    os.utime(tail / "findings.json", (started, started))
    os.utime(tail / "log.jsonl", (tail_last, tail_last))


def _impl_rows() -> list[dict]:
    return [
        {"agent": "tp-task-worker-local-medium", "phase": "7", "task_id": "7.2",
         "wall_s": 120.5},
        {"agent": "tp-task-worker-local-medium", "phase": "9", "task_id": "9.1",
         "wall_s": 79.5},
        # the per-phase tp-worker row: phase null AND wall_s null → not counted
        {"agent": "tp-worker", "phase": None, "task_id": "7", "wall_s": None},
        {"agent": "design-slot", "phase": None, "task_id": "d1", "wall_s": 999.0},
        {"agent": "audit-slot", "phase": "4", "task_id": "4.1"},  # wall_s missing
    ]


def test_summary_sums_two_rounds_and_ignores_null_rows(tmp_path):
    design_dir = tmp_path / "design"
    proof_root = tmp_path / "proof"
    _telemetry(design_dir, _impl_rows())
    _round(proof_root, 57, "r1", T0, T0 + 100)
    _round(proof_root, 57, "r2", T0 + 1000, T0 + 1050)
    got = review_time.summary(design_dir, proof_root, 57)
    assert got == {"implementation_s": 200.0, "review_s": 150.0, "ratio": 0.75}


def test_ratio_none_when_no_telemetry(tmp_path):
    design_dir = tmp_path / "design"
    proof_root = tmp_path / "proof"
    design_dir.mkdir(parents=True)
    _round(proof_root, "57", "r1", T0, T0 + 60)
    got = review_time.summary(design_dir, proof_root, "57")
    assert got == {"implementation_s": 0.0, "review_s": 60.0, "ratio": None}


def test_missing_rounds_dir_is_zero(tmp_path):
    design_dir = tmp_path / "design"
    _telemetry(design_dir, [{"phase": "4", "task_id": "4.1", "wall_s": 30.0}])
    got = review_time.summary(design_dir, tmp_path / "nope", 57)
    assert got == {"implementation_s": 30.0, "review_s": 0.0, "ratio": 0.0}


def test_round_without_tail_or_manifest_is_skipped(tmp_path):
    design_dir = tmp_path / "design"
    proof_root = tmp_path / "proof"
    _telemetry(design_dir, [{"phase": "4", "task_id": "4.1", "wall_s": 40.0}])
    _round(proof_root, 57, "r1", T0, T0 + 10)
    # r2: manifest but no tail/ → skipped
    r2 = proof_root / "rounds" / "57" / "r2"
    r2.mkdir(parents=True)
    (r2 / "angles.json").write_text(json.dumps({"started_at": _iso(T0)}), encoding="utf-8")
    # r3: tail but unparseable manifest → skipped
    _round(proof_root, 57, "r3", T0, T0 + 999)
    r3 = proof_root / "rounds" / "57" / "r3"
    (r3 / "angles.json").write_text("{not json", encoding="utf-8")
    got = review_time.summary(design_dir, proof_root, 57)
    assert got == {"implementation_s": 40.0, "review_s": 10.0, "ratio": 0.25}


def test_cli_phase_impl_prints_one_line(tmp_path, capsys):
    design_dir = tmp_path / "design"
    _telemetry(design_dir, [{"phase": "7", "task_id": "7.2", "wall_s": 3725.0}])
    rc = review_time.main(["--design-dir", str(design_dir), "--phase", "impl"])
    out = capsys.readouterr().out
    assert rc == 0
    assert out == "Implementation time: 1h 02m (3725.0 s)\n"


def test_cli_default_prints_one_line(tmp_path, capsys):
    design_dir = tmp_path / "design"
    proof_root = tmp_path / "proof"
    _telemetry(design_dir, [{"phase": "7", "task_id": "7.2", "wall_s": 200.0}])
    _round(proof_root, 57, "r1", T0, T0 + 100)
    _round(proof_root, 57, "r2", T0 + 1000, T0 + 1050)
    rc = review_time.main(["--design-dir", str(design_dir),
                           "--proof-root", str(proof_root), "--pr", "57"])
    out = capsys.readouterr().out
    assert rc == 0
    assert out == "Implementation 0h 03m, review 0h 02m, ratio 0.75\n"


def test_cli_review_phase_ratio_na(tmp_path, capsys):
    design_dir = tmp_path / "design"
    proof_root = tmp_path / "proof"
    design_dir.mkdir(parents=True)
    _round(proof_root, 57, "r1", T0, T0 + 60)
    rc = review_time.main(["--design-dir", str(design_dir),
                           "--proof-root", str(proof_root), "--pr", "57",
                           "--phase", "review"])
    out = capsys.readouterr().out
    assert rc == 0
    assert out == "Review time: 0h 01m (60.0 s), n/a implementation\n"
