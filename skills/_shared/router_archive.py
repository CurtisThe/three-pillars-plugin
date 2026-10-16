#!/usr/bin/env python3
"""router_archive.py — incremental, trim-aware archiver for the local router's log.

design: cheap-tier-local-routing (detailed-design.md, Interfaces `router_archive.py`)

`archive` appends every complete new line of the router log (a partial last line waits for
its newline) to `D/router-YYYYMMDD.log`, dated by the line's own `[YYYY-MM-DD HH:MM:SS]`
stamp. `D` defaults to the log's sibling `router-archive/`. The state file
`D/.archive-state.json` keeps `{inode, size, offset, tail, last_ts, last_run_at}` (plus the
`last_trim_seen_at` / `ran_before_last_trim` that `status` reports) and is replaced
(tmp + `os.replace`) only after the append, so a crash between the two re-appends one batch
rather than losing it.

Each run first verifies that the bytes ending at `offset` are the stored `tail` (the last
three archived lines) in the same inode. Anything else is a trim: the run anchors after the
**last** occurrence of the tail in the file; with no occurrence it appends only lines stamped
after `last_ts` (never the whole file, which would double router_history's max-count union)
and adds `{"at", "reason": "anchor-lost", "gap": [last_ts, first kept ts]}` (router-local
stamps, as router_history reads them) to `D/archive-gaps.ndjson`.

`ran_before_last_trim` is evidence, not proof, of an `ExecStartPre` run before the trimmer:
it is true when the last trim the archiver saw kept the archived tail (nothing was lost).
Interim seat snapshots `router-<YYYYMMDDTHHMM>.log` in `D` are never written or deleted.
`archive` takes `fcntl.flock(LOCK_EX | LOCK_NB)` on `D/.archive.lock`; a held lock is a no-op.
The CLI prints one JSON line and exits 0.
"""
from __future__ import annotations

import argparse
import datetime
import fcntl
import json
import os
import re
import sys
from pathlib import Path

import router_history as rh
import router_stats as rs

STATE_NAME = ".archive-state.json"
LOCK_NAME = ".archive.lock"
TAIL_LINES = 3
_FMT = "%Y-%m-%dT%H:%M:%SZ"
_TS_RE = re.compile(rb"^\[(\d{4})-(\d{2})-(\d{2})[ T](\d{2}:\d{2}:\d{2})")


def _paths(log, dir, env):
    env = os.environ if env is None else env
    log = Path(log) if log else rs.log_path(env)
    return log, (Path(dir) if dir else log.parent / rh.ARCHIVE_DIR)


def _iso(now):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    return now.astimezone(datetime.timezone.utc).strftime(_FMT)


def _stamp(line: bytes):
    """(router-local `YYYY-MM-DD HH:MM:SS`, `YYYYMMDD`) for a stamped line, else None."""
    m = _TS_RE.match(line)
    if not m:
        return None
    y, mo, d, hms = (g.decode("ascii") for g in m.groups())
    return f"{y}-{mo}-{d} {hms}", f"{y}{mo}{d}"


def _encode(lines):
    return b"".join(line + b"\n" for line in lines)


def _text(line: bytes) -> str:
    return line.decode("utf-8", "surrogateescape")


def _tail(content: bytes, offset: int) -> list[bytes]:
    """The last TAIL_LINES complete lines ending at `offset`."""
    parts = content[:offset].rsplit(b"\n", TAIL_LINES + 1)
    return parts[1:-1] if len(parts) == TAIL_LINES + 2 else parts[:-1]


def _verified(state, content, inode) -> bool:
    offset, tail = state["offset"], _encode(state["tail"])
    start = offset - len(tail)
    return (state.get("inode") == inode and len(content) >= offset and start >= 0
            and content[start:offset] == tail and (start == 0 or content[start - 1:start] == b"\n"))


def _anchor(content: bytes, tail: bytes):
    """The end of the **last** line-aligned occurrence of `tail` in `content`, or None."""
    if not tail:
        return 0
    end = len(content)
    while True:
        i = content.rfind(tail, 0, end)
        if i < 0:
            return None
        if i == 0 or content[i - 1:i] == b"\n":
            return i + len(tail)
        end = i + len(tail) - 1


def _after(lines, last_ts):
    """Lines stamped after `last_ts` (an unstamped line follows its last stamp), first kept ts."""
    kept, first, keep = [], None, last_ts is None
    for line in lines:
        st = _stamp(line)
        if st:
            keep = last_ts is None or st[0] > last_ts
            if keep and first is None:
                first = st[0]
        if keep:
            kept.append(line)
    return kept, first


def _load_state(path):
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        state["offset"], state["tail"] = int(state["offset"]), [
            t.encode("utf-8", "surrogateescape") for t in state["tail"]]
        return state
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def _write_state(d: Path, state: dict) -> None:
    tmp = d / f"{STATE_NAME}.{os.getpid()}.tmp"
    tmp.write_text(json.dumps(state, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, d / STATE_NAME)


def _append(d: Path, lines, last_ts, today):
    """Append `lines` to their dated files; (files written, stamp of the last stamped line)."""
    batches: dict[str, list[bytes]] = {}
    day = last_ts.replace("-", "")[:8] if last_ts else today
    for line in lines:
        st = _stamp(line)
        if st:
            last_ts, day = st
        batches.setdefault(day, []).append(line)
    for day, batch in batches.items():
        with open(d / f"router-{day}.log", "ab") as fh:
            fh.write(_encode(batch))
    return sorted(f"router-{day}.log" for day in batches), last_ts


def _gap(d: Path, at: str, last_ts: str, first: str | None) -> None:
    row = {"at": at, "reason": "anchor-lost", "gap": [last_ts, first or last_ts]}
    fd = os.open(d / rh.GAPS_NAME, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(fd, (json.dumps(row) + "\n").encode("utf-8"))
    finally:
        os.close(fd)


def _run(log: Path, d: Path, at: str, today: str) -> dict:
    with open(log, "rb") as fh:
        inode, content = os.fstat(fh.fileno()).st_ino, fh.read()
    complete = content.rfind(b"\n") + 1
    prev = _load_state(d / STATE_NAME)
    last_ts = prev.get("last_ts") if prev else None
    trim, anchor, gap_first = False, "first", None
    if prev is None:
        start = 0
    elif _verified(prev, content, inode):
        start, anchor = prev["offset"], "verified"
    else:
        trim = True
        start = _anchor(content, _encode(prev["tail"]))
        anchor = "found" if start is not None else "lost"
    if anchor == "lost":
        lines, gap_first = _after(content[:complete].split(b"\n")[:-1], last_ts)
    else:
        lines = content[start:complete].split(b"\n")[:-1]
    files, new_ts = _append(d, lines, last_ts, today) if lines else ([], last_ts)
    if anchor == "lost" and last_ts is not None:
        _gap(d, at, last_ts, gap_first)
    state = {"inode": inode, "size": len(content), "offset": complete,
             "tail": [_text(t) for t in _tail(content, complete)], "last_ts": new_ts,
             "last_run_at": at,
             "last_trim_seen_at": at if trim else (prev or {}).get("last_trim_seen_at"),
             "ran_before_last_trim": (anchor == "found") if trim
             else bool((prev or {}).get("ran_before_last_trim"))}
    _write_state(d, state)
    return {"archived": len(lines), "anchor": anchor, "trim": trim, "files": files}


def archive(log=None, dir=None, *, env=None, now=None) -> dict:
    """Archive the router log's new complete lines into `dir`; one JSON-able dict, never raises."""
    try:
        log, d = _paths(log, dir, env)
        if not log.is_file():
            return {"archived": 0, "reason": "no router log"}
        d.mkdir(parents=True, exist_ok=True)
        lock = os.open(d / LOCK_NAME, os.O_RDWR | os.O_CREAT, 0o644)
    except OSError as exc:
        return {"archived": 0, "reason": f"error: {exc}"}
    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return {"archived": 0, "reason": "locked"}
        at = _iso(now)
        return _run(log, d, at, at[:10].replace("-", ""))
    except OSError as exc:
        return {"archived": 0, "reason": f"error: {exc}"}
    finally:
        os.close(lock)


def _count_gaps(path: Path) -> int:
    n = 0
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return 0
    for line in lines:
        try:
            n += isinstance(json.loads(line), dict)
        except ValueError:
            continue
    return n


def status(log=None, dir=None, *, env=None) -> dict:
    """`{last_run_at, last_trim_seen_at, ran_before_last_trim, gaps}` from `dir`'s state."""
    try:
        _, d = _paths(log, dir, env)
    except OSError:
        d = None
    state = (_load_state(d / STATE_NAME) if d else None) or {}
    return {"last_run_at": state.get("last_run_at"),
            "last_trim_seen_at": state.get("last_trim_seen_at"),
            "ran_before_last_trim": bool(state.get("ran_before_last_trim")),
            "gaps": _count_gaps(d / rh.GAPS_NAME) if d else 0}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="router_archive.py", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("archive", "status"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--log", default=None, help="router log (default: router_stats.log_path)")
        cmd.add_argument("--dir", default=None, help="archive dir (default: <log dir>/router-archive)")
    args = parser.parse_args(argv)
    try:
        out = archive(args.log, args.dir) if args.cmd == "archive" else status(args.log, args.dir)
    except Exception as exc:  # noqa: BLE001 — fail-open: one JSON line, exit 0
        out = {"archived": 0, "reason": f"error: {exc}"}
    sys.stdout.write(json.dumps(out, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
