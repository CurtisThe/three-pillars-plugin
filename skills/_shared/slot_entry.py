#!/usr/bin/env python3
"""Slot headings carry wall-clock minutes (design: light-run-ceremony-diet, B6).

`heading` renders `### [orchestrator/<slot>] <title> (N min)`; the `append` CLI
writes such an entry to decisions.md only through `local_route_log.append_entry`.
"""
import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import local_route_log  # noqa: E402


def _parse(ts: str) -> datetime:
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def minutes(started: str, ended: str) -> int:
    """Whole minutes from start to end, rounded half up, never negative."""
    secs = (_parse(ended) - _parse(started)).total_seconds()
    if secs <= 0:
        return 0
    return int((secs + 30) // 60)


def heading(slot: str, title: str, started: str, ended: str) -> str:
    return f"### [orchestrator/{slot}] {title} ({minutes(started, ended)} min)"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="slot_entry.py")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("append")
    a.add_argument("--decisions", required=True)
    a.add_argument("--slot", required=True)
    a.add_argument("--title", required=True)
    a.add_argument("--started", required=True)
    a.add_argument("--ended", default=None)
    a.add_argument("--body", default="")
    args = p.parse_args(argv)
    ended = args.ended or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        text = heading(args.slot, args.title, args.started, ended)
    except ValueError as exc:
        print(f"slot_entry: bad ISO time: {exc}", file=sys.stderr)
        return 2
    entry = text + ("\n" + args.body if args.body else "")
    local_route_log.append_entry(Path(args.decisions), entry)
    return 0


if __name__ == "__main__":
    sys.exit(main())
