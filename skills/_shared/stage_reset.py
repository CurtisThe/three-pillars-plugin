#!/usr/bin/env python3
"""stage_reset.py — reset an interactive design run's context at a stage boundary.

design: run-throughput (Part F; detailed-design-stage-reset.md)

At a boundary the orchestrator saves a handoff, schedules a detached sender, and
ends its turn; the sender waits until the turn has really ended, then types
`/clear` and the resume command into the run's tmux pane.

- `should_reset(env, mode, weight, boundary)` — the gate: the interactive marker
  `TP_STAGE_RESET=pane`, a `$TMUX_PANE`, and a boundary inside the `--mode` window.
  DORMANT: no launcher exports the marker (Task 7.5 seat ruling), so a live run
  always gets `(False, "non-interactive")` until `stage-reset-supervisor` lands.
  `boundary` names the stage being entered (`plan` / `implement` / `review`, the
  `--resume-stage` vocabulary). Returns `(True, "reset")` or `(False, <why>)`, the
  `<why>` of `[orchestrator] stage-reset skipped (<why>)`.
- `idle(transcript, since)` — the turn has ended: `transcript_tail.end_of_turn()`
  over the records written at or after `since` (epoch seconds, by each record's
  `timestamp`), plus the file mtime stable for `STABLE_S` seconds.
- `schedule(pane, cwd, resume_cmd, ...)` — fork a detached `setsid` sender, return its
  pid; CLI: `stage_reset.py schedule ...` / `stage_reset.py idle --transcript T --since S`.

Stdlib only; never calls `claude`.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import transcript_tail

MARKER_VAR = "TP_STAGE_RESET"
MARKER = "pane"
STABLE_S = 3
STAGES = ("plan", "implement", "review")
WEIGHTS = ("full", "light")
# (mode, weight) -> the stages whose boundary resets. A light run has no design->plan
# boundary (Slots 3 and 5 do not exist; it collapses into the merged Slot 4+6 audit).
# design / plan modes end at their scoped PR; build crosses implement->review only.
WINDOWS = {
    ("full", "full"): ("plan", "implement", "review"),
    ("full", "light"): ("implement", "review"),
    ("design", "full"): (), ("design", "light"): (),
    ("plan", "full"): (), ("plan", "light"): (),
    ("build", "full"): ("review",), ("build", "light"): ("review",),
}


def should_reset(env, mode: str, weight: str, boundary: str) -> tuple[bool, str]:
    """The three-part reset gate; ValueError on an unknown mode, weight or boundary."""
    if (mode, weight) not in WINDOWS:
        raise ValueError(f"unknown mode/weight: {mode!r}/{weight!r}")
    if boundary not in STAGES:
        raise ValueError(f"unknown boundary: {boundary!r} (expected one of {', '.join(STAGES)})")
    if env.get(MARKER_VAR) != MARKER:
        return False, "non-interactive"
    if not env.get("TMUX_PANE"):
        return False, "no tmux pane"
    if boundary not in WINDOWS[(mode, weight)]:
        return False, "outside mode window"
    return True, "reset"


def _epoch(ts) -> float | None:
    if not isinstance(ts, str) or not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def records_since(records: list[dict], since: float) -> list[dict]:
    """The records from the first one timestamped at or after `since` to the end."""
    for index, rec in enumerate(records):
        stamp = _epoch(rec.get("timestamp"))
        if stamp is not None and stamp >= since:
            return records[index:]
    return []


def idle(transcript, since: float, *, now: float | None = None, stable_s: float = STABLE_S) -> bool:
    """True when the turn written after `since` has ended and the file has settled."""
    path = Path(transcript)
    try:
        mtime = path.stat().st_mtime
        records = transcript_tail.read_records(path)
    except OSError:
        return False
    if (time.time() if now is None else now) - mtime < stable_s:
        return False
    return transcript_tail.end_of_turn(records_since(records, since)) is not None


def _slug(cwd: str) -> str:
    # Claude Code's project-dir rule; the fleet transcript_paths.project_slug rule.
    return re.sub(r"[^a-zA-Z0-9]", "-", os.path.normpath(cwd))


def _newest_transcript(config_dir, cwd: str) -> Path | None:
    base = Path(config_dir or os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    found = [p for p in (base / "projects" / _slug(cwd)).glob("*.jsonl") if p.is_file()]
    return max(found, key=lambda p: p.stat().st_mtime) if found else None


def _keys(pane: str, *args: str) -> None:
    subprocess.run(["tmux", "send-keys", "-t", pane, *args], check=False)


def _send(pane, resume_cmd, gap_s, do_clear) -> None:
    if do_clear:
        _keys(pane, "-l", "/clear")
        _keys(pane, "Enter")
        time.sleep(gap_s)
    _keys(pane, "-l", resume_cmd)
    _keys(pane, "Enter")


def schedule(pane, cwd, resume_cmd, *, design_dir, config_dir=None, gap_s=4, timeout_s=900,
             since=None, stable_s=STABLE_S, poll_s=1.0) -> int:
    """Fork one setsid child that waits for idle, then types /clear + resume; return its pid."""
    since = time.time() if since is None else since
    transcript = _newest_transcript(config_dir, cwd)
    pid = os.fork()
    if pid:
        return pid
    code = 1
    try:
        os.setsid()
        null = os.open(os.devnull, os.O_RDWR)
        for fd in (0, 1, 2):
            os.dup2(null, fd)
        deadline = time.monotonic() + timeout_s
        ended = False
        while True:
            if transcript is not None and idle(transcript, since, stable_s=stable_s):
                ended = True
                break
            if time.monotonic() >= deadline:
                break
            time.sleep(poll_s)
        if not ended:
            log_dir = Path(design_dir) / ".handoffs"
            log_dir.mkdir(parents=True, exist_ok=True)
            with open(log_dir / "stage-reset.log", "a", encoding="utf-8") as fh:
                fh.write("stage-reset: idle-timeout\n")
        _send(pane, resume_cmd, gap_s, ended)
        code = 0
    finally:
        os._exit(code)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sc = sub.add_parser("schedule")
    sc.add_argument("--pane", required=True)
    sc.add_argument("--cwd", required=True)
    sc.add_argument("--resume-cmd", required=True)
    sc.add_argument("--design-dir", required=True)
    sc.add_argument("--config-dir")
    sc.add_argument("--gap-s", type=float, default=4)
    sc.add_argument("--timeout-s", type=float, default=900)
    idl = sub.add_parser("idle")
    idl.add_argument("--transcript", required=True)
    idl.add_argument("--since", type=float, required=True)
    a = ap.parse_args(argv)
    if a.cmd == "schedule":
        pid = schedule(a.pane, a.cwd, a.resume_cmd, design_dir=a.design_dir,
                       config_dir=a.config_dir, gap_s=a.gap_s, timeout_s=a.timeout_s)
        print(json.dumps({"pid": pid}))
        return 0
    ok = idle(a.transcript, a.since)
    print(json.dumps({"idle": ok}))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
