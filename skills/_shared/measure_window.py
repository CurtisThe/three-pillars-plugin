#!/usr/bin/env python3
"""measure_window.py — the machine-wide exclusive-lease measurement window.

design: cheap-tier-local-routing (B4)

While an operator measures one design's local routing, every other caller reads as a
non-owner of the GPU slot (`local_lease` answers them `busy-measure`). The window is one
JSON file under `<state dir>/tp-local/` (the dir `router_stats.log_path` uses):
`{"schema": "tp-measure-window/v1", design, started_at, until, set_by}`. `load` returns it
only while live (never raises); `role` says whether a design owns it. `start` and `stop`
also append a line to the never-rewritten `measure-windows.ndjson`, so `history` and
`role_at` can tell owner from other after the live file expires.

    measure_window.py start --design D (--hours H | --until ISO) [--set-by WHO]
    measure_window.py stop
    measure_window.py status

`start` refuses a live window held by another design (exit 2). Only the operator, or the
seat under delegation, runs `start`/`stop`. Clocks are injectable; stdlib only.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

import router_stats

SCHEMA = "tp-measure-window/v1"
LIVE_NAME = "measure-window.json"
HISTORY_NAME = "measure-windows.ndjson"


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _parse(value) -> dt.datetime | None:
    """An aware datetime from an ISO string (a naive one is local time) or datetime, else None."""
    try:
        when = value if isinstance(value, dt.datetime) else dt.datetime.fromisoformat(
            value.strip().replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None
    return when.astimezone() if when.tzinfo is None else when


def _iso(when: dt.datetime) -> str:
    return when.astimezone(dt.timezone.utc).isoformat(timespec="seconds")


def state_dir(env):
    return router_stats.log_path(env).parent


def _read_live(env) -> dict | None:
    """The live file's window if it parses and has the v1 shape (expired or not), else None."""
    try:
        raw = json.loads((state_dir(env) / LIVE_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    ok = (isinstance(raw, dict) and raw.get("schema") == SCHEMA
          and isinstance(raw.get("design"), str) and raw["design"]
          and _parse(raw.get("started_at")) and _parse(raw.get("until")))
    return raw if ok else None


def load(env, *, clock=None) -> dict | None:
    """The live window, or None (absent, unreadable, malformed or expired). Never raises."""
    window = _read_live(env)
    if window is None or role(window, None, (clock or _utcnow)()) == "off":
        return None
    return window


def role(window, design: str | None, now=None) -> str:
    """`off` with no live window; `owner` iff `design` is the window's; else `other`."""
    until = _parse(window.get("until")) if isinstance(window, dict) else None
    if until is None or until <= (_parse(now) or _utcnow()):
        return "off"
    return "owner" if design is not None and design == window.get("design") else "other"


def history(env) -> list[dict]:
    """`[{design, start, end}]` in log order; `end` is `until` or an earlier `stop`/restart."""
    try:
        raw = (state_dir(env) / HISTORY_NAME).read_bytes()
    except OSError:
        return []
    windows: list[dict] = []
    for line in raw.decode("utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        design = row.get("design") if isinstance(row, dict) else None
        if not isinstance(design, str) or not design:
            continue
        if row.get("event") == "start":
            start, end = _parse(row.get("started_at")), _parse(row.get("until"))
            if start and end:
                _cut(windows, design, start)
                windows.append({"design": design, "start": _iso(start), "end": _iso(end)})
        elif row.get("event") == "stop" and (at := _parse(row.get("at"))):
            _cut(windows, design, at)
    return windows


def _cut(windows: list[dict], design: str, at: dt.datetime) -> None:
    """End `design`'s windows that are still open at `at` (a stop, or a restart)."""
    for w in windows:
        if w["design"] == design and _parse(w["start"]) <= at < _parse(w["end"]):
            w["end"] = _iso(at)


def role_at(windows, design: str | None, at) -> str:
    """`owner` / `other` inside a recorded window at `at` (`start` inclusive, `end` exclusive)."""
    when = _parse(at)
    live = [w["design"] for w in windows if _parse(w["start"]) <= when < _parse(w["end"])]
    return "off" if not live else "owner" if design is not None and design in live else "other"


def _write_live(path, window: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(window), encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _append(env, record: dict) -> None:
    """One `O_APPEND` write of one line; the log is never rewritten."""
    with open(state_dir(env) / HISTORY_NAME, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


def _start(args, env, now: dt.datetime) -> int:
    held = load(env, clock=lambda: now)
    if held and held["design"] != args.design:
        print(f"measure-window: held by {held['design']} until {held['until']}", file=sys.stderr)
        return 2
    try:
        until = _parse(args.until) if args.until is not None else now + dt.timedelta(hours=args.hours)
    except (OverflowError, ValueError):
        until = None
    if until is None or until <= now:
        print("measure-window: --hours must be > 0 and --until in the future", file=sys.stderr)
        return 2
    window = {"schema": SCHEMA, "design": args.design, "started_at": _iso(now),
              "until": _iso(until), "set_by": args.set_by or env.get("USER") or "operator"}
    _write_live(state_dir(env) / LIVE_NAME, window)
    _append(env, {"event": "start", **{k: window[k] for k in
                  ("design", "started_at", "until", "set_by")}})
    print(f"measure-window: {args.design} until {window['until']}")
    return 0


def _stop(env, now: dt.datetime) -> int:
    window = _read_live(env)
    if window:
        (state_dir(env) / LIVE_NAME).unlink(missing_ok=True)
        _append(env, {"event": "stop", "design": window["design"], "at": _iso(now)})
    print(f"measure-window: stopped {window['design']}" if window else "off")
    return 0


def main(argv=None, env=None, clock=None) -> int:
    """`env` (default `os.environ`) and `clock` (default UTC now) are injectable."""
    parser = argparse.ArgumentParser(description="The machine-wide measurement window.")
    sub = parser.add_subparsers(dest="action", required=True)
    start = sub.add_parser("start", help="open a window for one design")
    start.add_argument("--design", required=True)
    end = start.add_mutually_exclusive_group(required=True)
    end.add_argument("--hours", type=float)
    end.add_argument("--until", help="ISO timestamp (naive means local time)")
    start.add_argument("--set-by", default=None)
    sub.add_parser("stop", help="close the live window")
    sub.add_parser("status", help="print the live window, or off")
    args = parser.parse_args(argv)
    env = os.environ if env is None else env
    now = (clock or _utcnow)()
    try:
        if args.action == "start":
            return _start(args, env, now)
        if args.action == "stop":
            return _stop(env, now)
        window = load(env, clock=lambda: now)
        print(json.dumps(window) if window else "off")
        return 0
    except OSError as exc:
        print(f"measure-window: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
