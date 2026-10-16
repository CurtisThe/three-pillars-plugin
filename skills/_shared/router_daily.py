#!/usr/bin/env python3
"""router_daily.py — per-day report of router resets, stops, orphans, GPU-hold.

design: m44-orphan-reaper (Part B — measurement)

`router_daily.py [--log P]... [--archive-dir D] [--ladder-dir L]... [--stopped F]...
[--day YYYY-MM-DD]`
prints ONE JSON object to stdout and exits 0:
`{"days": {day: {"reset_local_mid", "stopped_refuse", "stopped_drop",
"orphans", "orphan_hold_s"}}}` — days sorted, every day carries all five keys
(zero-filled), `orphan_hold_s` a number. Log sources: every `router-*.log` in
`--archive-dir` (sorted) plus every `--log` file; with neither flag, the defaults
are `<its parent dir>/router-archive/router-*.log` when present plus
`router_stats.log_path(env)`. Files are read oldest first (archives, then the
live log) and each raw line counts at its max multiplicity across the files (the
archives are overlapping cumulative snapshots), so the merged events keep log
order for open/close pairing. Stops come from the
durable per-stop records (W files are swept): each `--ladder-dir`'s `stops.ndjson`,
every `--stopped` file, and with no source flag the stopped-agents file
(`stopped_agents.path(env)`); plus each ladder dir's `*.watch.json` still carrying
`orphaned_at`/`stopped_at`. They merge per (attempt, agent) (retries write several
lines; `stop_records.merged`): one `orphans` on the local day of the hold's start (`orphaned_at`, else
`stopped_at`), and `attempt_orphans.hold_seconds` (agent events with `ts >= start`)
added to that day's `orphan_hold_s`. Missing / unreadable files are skipped
silently; no inputs -> `{"days": {}}`, exit 0. Stdlib only.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import attempt_orphans  # noqa: E402
import router_stats  # noqa: E402
import stop_records  # noqa: E402

KEYS = ("reset_local_mid", "stopped_refuse", "stopped_drop", "orphans", "orphan_hold_s")


def _sources(args, env) -> list[str]:
    """The log files to read, oldest first: the archives (sorted), then the live
    `--log` files in the order given (`_events` de-duplicates in that order)."""
    if args.log or args.archive_dir:
        archives = sorted(Path(args.archive_dir).glob("router-*.log")) if args.archive_dir else []
        return [str(p) for p in archives] + list(args.log)
    default = router_stats.log_path(env)
    archive = default.parent / "router-archive"
    return [str(p) for p in sorted(archive.glob("router-*.log"))] + [str(default)]


def _lines(path) -> Counter:
    """The file's whole lines (a partial last line held back), counted; `{}` if unreadable."""
    try:
        data = Path(path).read_bytes()
    except OSError:
        return Counter()
    text = data[: data.rfind(b"\n") + 1].decode("utf-8", errors="replace")
    return Counter(line for line in text.splitlines() if line)


def _events(paths) -> list[dict]:
    """Every readable file's events, each raw line at its max multiplicity across files.

    The archives are cumulative snapshots and the live log overlaps the newest, so a
    line seen in several files counts once, while a line repeated within one file
    still counts per occurrence (`Counter` union). Missing/unreadable files skip.
    `paths` come oldest first, so the union is in log order: a line sits where the
    oldest file holding it put it, and a newer file's new lines follow in its own
    order. The stable sort by timestamp only backstops a mis-ordered file list; it
    never reorders lines within one file or same-second lines across files, which
    open/close pairing relies on (a close before its request is a pre-window close).
    """
    merged: Counter = Counter()
    for path in paths:
        merged |= _lines(path)
    events = [ev for line, n in merged.items()
              if (ev := router_stats.parse_line(line)) for _ in range(n)]
    return sorted(events, key=_log_order)


def _log_order(ev: dict) -> tuple:
    """Stable sort key: timestamp only (unreadable last); equal stamps keep their order."""
    t = router_stats.ts_epoch(ev.get("ts"))
    return (t is None, t or 0.0)


def _orphan_days(states: list[dict], events: list[dict], now: float, days: dict) -> None:
    """Add each stop's count and hold to the day of its start (`orphaned_at`, else `stopped_at`)."""
    for state in states:
        start = state["orphaned_at"] if state["orphaned_at"] is not None else state["stopped_at"]
        try:
            day = datetime.datetime.fromtimestamp(float(start)).date().isoformat()
        except (TypeError, ValueError, OSError):
            continue
        day_entry = days.setdefault(day, {k: 0 for k in KEYS})
        day_entry["orphans"] += 1
        after = [ev for ev in router_stats.for_agent(events, str(state.get("agent_id") or ""))
                 if (t := router_stats.ts_epoch(ev.get("ts"))) is not None and t >= start]
        hold = attempt_orphans.hold_seconds(state, after, now)
        if hold is not None:
            day_entry["orphan_hold_s"] += hold


def main(argv=None, env=None, now=None) -> int:
    """Print the per-day JSON report to stdout and return 0 (never raises on input)."""
    env = os.environ if env is None else env
    now = time.time() if now is None else now
    parser = argparse.ArgumentParser(prog="router_daily.py")
    parser.add_argument("--log", action="append", default=[])
    parser.add_argument("--archive-dir", default=None)
    parser.add_argument("--ladder-dir", action="append", default=[])
    parser.add_argument("--stopped", action="append", default=[])
    parser.add_argument("--day", default=None)
    args = parser.parse_args(argv)

    events = _events(_sources(args, env))
    days: dict[str, dict] = {}
    for day, counts in router_stats.daily_counts(events).items():
        days[day] = {**{k: 0 for k in KEYS}, **counts}
    stops = stop_records.files(args.stopped, args.ladder_dir, env=env,
                               default=not (args.log or args.archive_dir or args.stopped))
    _orphan_days(stop_records.merged(args.ladder_dir, stops), events, now, days)
    if args.day:
        days = {d: c for d, c in days.items() if d == args.day}
    print(json.dumps({"days": {d: days[d] for d in sorted(days)}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
