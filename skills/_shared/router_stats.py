#!/usr/bin/env python3
"""router_stats.py — read the local router's LOCAL-STATS v1 and client-reset lines.

design: run-throughput (Part S, runaway ceiling)

The contract is local-llm-skills `README.md` §"Router log contract: LOCAL-STATS v1"
(`bin/local_stats.py`). After each completed local-routed response the router logs

    [<ts>] LOCAL-STATS v=1 sess=<8ch|-> agent=<8ch|-> model=<name> output_tokens=<int>
           stop_reason=<end_turn|max_tokens|tool_use|stop_sequence|error|unknown>
           wall_s=<float> clamped=<0|1> [additive fields...]

and an abandoned stream logs
`[<ts>] client-reset <idle|mid-response> sess=<8ch|-> agent=<8ch|-> route=<...>`.
Two more lines are read only to judge a reset (M48): each request,
`[<ts>] POST <path>  model=<name>  sess=<8ch>  [agent=<8ch>  ...] -> <route> ...`, and a
backend that never answered, `[<ts>] UPSTREAM-UNREACHABLE route=<...> sess=<8ch|->
agent=<8ch|-> (<error>)`. `<ts>` is the router's local wall time.
`agent` is the first 8 characters of `x-claude-code-agent-id`. A `v=` other than 1
is not matched. Nothing here raises: an unreadable line or file is skipped.
"""
from __future__ import annotations

import datetime
import re
from pathlib import Path

STATS_RE = re.compile(
    r"^\[(?P<ts>[^\]]+)\] LOCAL-STATS v=1 sess=(?P<sess>\S+) agent=(?P<agent>\S+)"
    r" model=(?P<model>\S+) output_tokens=(?P<output_tokens>\d+)"
    r" stop_reason=(?P<stop_reason>\w+) wall_s=(?P<wall_s>\d+(?:\.\d+)?)"
    r" clamped=(?P<clamped>[01])(?: \S+)*\s*$")
RESET_RE = re.compile(
    r"^\[(?P<ts>[^\]]+)\] client-reset (?P<mode>idle|mid-response) sess=(?P<sess>\S+)"
    r" agent=(?P<agent>\S+) route=(?P<route>\S+)(?: \S+)*\s*$")
REQUEST_RE = re.compile(
    r"^\[(?P<ts>[^\]]+)\] POST \S+\s+model=\S+\s+sess=(?P<sess>\S+)(?:\s+agent=(?P<agent>\S+))?"
    r".*?\s->\s(?P<route>\w+)")
UNREACHABLE_RE = re.compile(
    r"^\[(?P<ts>[^\]]+)\] UPSTREAM-UNREACHABLE route=(?P<route>\S+) sess=(?P<sess>\S+)"
    r" agent=(?P<agent>\S+)")
STOPPED_RE = re.compile(
    r"^\[(?P<ts>[^\]]+)\] STOPPED-AGENT (?P<action>refuse|drop) sess=(?P<sess>\S+)"
    r" agent=(?P<agent>\S+) route=(?P<route>\S+)(?: \S+)*\s*$")
LOG_REL = Path("tp-local") / "router.log"

# M48: how long a `client-reset mid-response` may go unanswered before it counts as a
# runaway. Claude Code drops a slow stream and carries on, so a reset alone is no breach;
# it is answered by any later request or LOCAL-STATS from the same agent. In the
# 2026-09-30 fragile-test-prevention run, healthy attempts answered a reset within 181 s
# (their next healthy LOCAL-STATS took a 222 s median, against 10.5 s for all healthy
# requests). 300 s clears both, and ends well before the 1200 s wall-clock budget
# (`attempt_watchdog.DEFAULT_WALL_S`), which stays the guard against mere slowness.
RESET_GRACE_S = 300


def log_path(env) -> Path:
    """`$TP_LOCAL_LOG`, else `($XDG_STATE_HOME or $HOME/.local/state)/tp-local/router.log`."""
    if env.get("TP_LOCAL_LOG"):
        return Path(env["TP_LOCAL_LOG"])
    if env.get("XDG_STATE_HOME"):
        return Path(env["XDG_STATE_HOME"]) / LOG_REL
    home = Path(env["HOME"]) if env.get("HOME") else Path.home()
    return home / ".local" / "state" / LOG_REL


def parse_line(line) -> dict | None:
    """A stats or reset event dict, or None for any other (or unreadable) line."""
    if not isinstance(line, str):
        return None
    m = STATS_RE.match(line)
    if m:
        ev = m.groupdict()
        ev.update(kind="stats", output_tokens=int(ev["output_tokens"]),
                  wall_s=float(ev["wall_s"]), clamped=int(ev["clamped"]))
        return ev
    for kind, rx in (("reset", RESET_RE), ("request", REQUEST_RE),
                     ("unreachable", UNREACHABLE_RE), ("stopped", STOPPED_RE)):
        m = rx.match(line)
        if m:
            return {"kind": kind, **m.groupdict(default="-")}
    return None


def ts_epoch(ts) -> float | None:
    """A router `<ts>` (local wall time) as epoch seconds; None if unreadable."""
    try:
        return datetime.datetime.fromisoformat(ts).timestamp()
    except (TypeError, ValueError):
        return None


def day_of(ts) -> str | None:
    """The `YYYY-MM-DD` of a router `<ts>` (local wall time); None if unreadable."""
    try:
        return datetime.datetime.fromisoformat(ts).date().isoformat()
    except (TypeError, ValueError):
        return None


def daily_counts(events) -> dict:
    """Per-day counts of local mid-response resets and router stops.

    {day: {"reset_local_mid": n, "stopped_refuse": n, "stopped_drop": n}} over the
    event dicts `parse_line` returns: `kind` "reset" with `mode=mid-response` and
    `route=local` count as `reset_local_mid`; `kind` "stopped" count by `action`
    (refuse|drop). Every day present carries all three keys (zero-filled); any other
    event, or an event whose ts has no readable day, is skipped."""
    out: dict[str, dict[str, int]] = {}
    for ev in events:
        day = day_of(ev.get("ts"))
        if day is None:
            continue
        if ev.get("kind") == "reset" and ev.get("mode") == "mid-response" and ev.get("route") == "local":
            key = "reset_local_mid"
        elif ev.get("kind") == "stopped" and ev.get("action") in ("refuse", "drop"):
            key = "stopped_" + ev["action"]
        else:
            continue
        counts = out.setdefault(day, {"reset_local_mid": 0, "stopped_refuse": 0, "stopped_drop": 0})
        counts[key] += 1
    return out


def read_since(path, offset: int) -> tuple[list[dict], int]:
    """Events in whole lines after byte `offset`, and the offset to read from next.

    A partial last line is held back; a file smaller than `offset` (truncated or
    rotated) restarts at 0; a missing or unreadable file returns `([], offset)`.
    """
    try:
        with open(Path(path), "rb") as fh:
            size = fh.seek(0, 2)
            start = 0 if size < offset else offset
            fh.seek(start)
            data = fh.read()
    except OSError:
        return [], offset
    end = data.rfind(b"\n") + 1
    text = data[:end].decode("utf-8", errors="replace")
    events = [ev for ev in (parse_line(line) for line in text.splitlines()) if ev]
    return events, start + end


def offset_since(path, since_epoch, tail_bytes: int) -> int:
    """The byte offset of the first whole line whose `<ts>` is ≥ `since_epoch`, scanning
    only the last `tail_bytes` — `arm`'s lookback, so a request sent between the agent's
    spawn and `arm` is still read. A line that does not parse, or whose `<ts>` does not,
    never qualifies; a tail starting mid-line skips that line, so the answer is always a
    line boundary. An absent, unreadable or unconfigured (`None`) log, or no qualifying
    line in the tail, gives the offset just past the last whole line read (0 for no log).
    """
    try:
        with open(Path(path), "rb") as fh:
            size = fh.seek(0, 2)
            start = max(0, size - max(0, int(tail_bytes)))
            probe = max(0, start - 1)  # the byte before the tail decides if it starts mid-line
            fh.seek(probe)
            data = fh.read()
    except (OSError, TypeError):
        return 0
    if start > 0:  # the tail may begin mid-line: only a whole line can be judged
        if data[:1] == b"\n":  # it starts on a boundary — keep that first whole line
            data = data[1:]
        else:
            nl = data.find(b"\n")
            if nl < 0:
                return probe + len(data)
            start, data = start + nl, data[nl + 1:]
    end = data.rfind(b"\n") + 1  # whole lines only, as `read_since` reads them
    pos = start
    for raw in data[:end].split(b"\n")[:-1]:
        ev = parse_line(raw.decode("utf-8", errors="replace"))
        epoch = ts_epoch(ev["ts"]) if ev else None
        if epoch is not None and epoch >= since_epoch:
            return pos
        pos += len(raw) + 1
    return pos


def for_agent(events, agent_id: str) -> list[dict]:
    """The events whose `agent` is `agent_id[:8]`; `-` (no agent) never matches."""
    prefix = (agent_id or "")[:8]
    if not prefix or prefix == "-":
        return []
    return [ev for ev in events if ev.get("agent") == prefix]


def _reset_outcome(reset: dict, later: list[dict], now) -> str | None:
    """Why a local mid-response reset is a runaway, or None while it is not (M48).
    `error` / `unreachable`: one follows it before any healthy LOCAL-STATS. `silent`: no
    request or LOCAL-STATS within RESET_GRACE_S, once `now` is past the window."""
    for ev in later:
        if ev.get("kind") == "unreachable":
            return "unreachable"
        if ev.get("kind") == "stats":
            return "error" if ev.get("stop_reason") == "error" else None
    start = ts_epoch(reset.get("ts"))
    if now is None or start is None or now < start + RESET_GRACE_S:
        return None
    answered = any(ev.get("kind") == "request" and (ts_epoch(ev.get("ts")) or 0) <= start
                   + RESET_GRACE_S for ev in later)
    return None if answered else "silent"


def runaway_event(events, *, max_gen_tokens=None, now=None) -> dict | None:
    """The first runaway generation: `stop_reason=max_tokens`, or a `mid-response` reset on
    `route=local` that `_reset_outcome` judges a runaway (the reset, with `after` = why).
    `now` (epoch) enables the silence window; None (the agent has ended) disables it.
    `max_gen_tokens` (tests / live check) also counts `output_tokens >= N`."""
    for i, ev in enumerate(events):
        if ev.get("kind") == "stats":
            if ev.get("stop_reason") == "max_tokens":
                return ev
            if max_gen_tokens is not None and ev.get("output_tokens", 0) >= max_gen_tokens:
                return ev
        elif ev.get("kind") == "reset":
            if ev.get("mode") == "mid-response" and ev.get("route") == "local":
                after = _reset_outcome(ev, events[i + 1:], now)
                if after:
                    return {**ev, "after": after}
    return None


FALLBACK_SERVED = "local-fallback-served"


def served_by(family, local_requests) -> str | None:
    """Who served an attempt — the ONE derivation (operator rulings Q1/Q3), from the
    router stats, never from the requested rung: a ``local``-family attempt with no
    LOCAL-STATS request (``local_requests`` 0 or unknown) went to the router's fallback
    (``fallback``; reason ``FALLBACK_SERVED``), else ``local``; a ``sonnet`` / ``opus``
    attempt never touches the local slot. Any other family is None."""
    if family == "local":
        return "local" if isinstance(local_requests, int) and local_requests > 0 else "fallback"
    return family if family in ("sonnet", "opus") else None


def gen_stats(events) -> dict:
    """{local_requests, max, p50, at_cap} over stats lines only (`max`/`p50` None when none)."""
    tokens = sorted(ev["output_tokens"] for ev in events if ev.get("kind") == "stats")
    at_cap = sum(1 for ev in events
                 if ev.get("kind") == "stats" and ev.get("stop_reason") == "max_tokens")
    if not tokens:
        return {"local_requests": 0, "max": None, "p50": None, "at_cap": 0}
    return {"local_requests": len(tokens), "max": tokens[-1],
            "p50": tokens[(len(tokens) - 1) // 2], "at_cap": at_cap}
