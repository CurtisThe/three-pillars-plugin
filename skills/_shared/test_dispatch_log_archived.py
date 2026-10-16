"""dispatch rows written after the Tier 5.6 archive land in the archived design dir.

design: run-throughput (PR #178 round-4 note: a Slot 10 / Slot 11 row logged after
`/tp-design-complete` moved `tp-designs/<slug>` to `completed-tp-designs/<slug>` fell
outside every H1 commit site, because the in-flight dir no longer existed).

Real CLI runs: `dispatch_log.py record` and `dispatch_tasks.py` are handed the in-flight
path the docs name; once it is archived the row and the `[dispatch]` line follow it.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _run(script: str, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(HERE / script), *args], input=stdin,
                          capture_output=True, text=True, timeout=60)


def _docs(tmp_path: Path, *, inflight: bool, archived: bool) -> tuple[Path, Path]:
    docs = tmp_path / "three-pillars-docs"
    live, done = docs / "tp-designs" / "d", docs / "completed-tp-designs" / "d"
    for want, path in ((inflight, live), (archived, done)):
        if want:
            path.mkdir(parents=True)
    docs.mkdir(exist_ok=True)
    (docs / "tp-designs").mkdir(exist_ok=True)
    return live, done


def _record(live: Path, root: Path) -> subprocess.CompletedProcess:
    return _run("dispatch_log.py", "record", "--design-dir", str(live), "--role", "pr",
                "--inline", "--reason", "slot 10", "--outcome", "ok", "--decisions",
                str(live / "decisions.md"), "--root", str(root))


def _rows(directory: Path) -> list[dict]:
    text = (directory / "dispatch-telemetry.ndjson").read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines()]


def test_record_after_the_archive_lands_in_the_archived_dir(tmp_path):
    live, done = _docs(tmp_path, inflight=False, archived=True)
    proc = _record(live, tmp_path)
    assert proc.returncode == 0 and proc.stderr == "", proc.stderr
    assert [r["role"] for r in _rows(done)] == ["pr"]
    assert "[dispatch] pr" in (done / "decisions.md").read_text(encoding="utf-8")
    assert not live.exists()  # never re-creates the archived-away in-flight dir


def test_record_before_the_archive_still_uses_the_in_flight_dir(tmp_path):
    live, done = _docs(tmp_path, inflight=True, archived=True)  # a stale archive copy exists
    assert _record(live, tmp_path).returncode == 0
    assert [r["role"] for r in _rows(live)] == ["pr"]
    assert not (done / "dispatch-telemetry.ndjson").exists()


def test_record_with_neither_dir_stays_fail_open(tmp_path):
    live, done = _docs(tmp_path, inflight=False, archived=False)
    proc = _record(live, tmp_path)
    assert proc.returncode == 0 and "ndjson row not written" in proc.stderr
    assert not done.exists()


def test_task_rows_after_the_archive_land_in_the_archived_dir(tmp_path):
    live, done = _docs(tmp_path, inflight=False, archived=True)
    verdict = {"rung": "sonnet-medium", "outcome": "PASS", "fingerprint": "f", "wall_s": 3.0,
               "tokens": 10, "served_by": "sonnet", "model": "sonnet", "why": "task_start"}
    rec = json.dumps({"task_id": "1.1", "route": "-", "verdicts": [verdict]})
    proc = _run("dispatch_tasks.py", "--design-dir", str(live), "--record", "-", stdin=rec)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == {"written": 1, "skipped": 0}
    assert [r["role"] for r in _rows(done)] == ["task"]
    assert not live.exists()
