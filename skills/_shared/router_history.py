#!/usr/bin/env python3
"""router_history.py — the router's live log and archives as one UTC-ordered history.

design: cheap-tier-local-routing (detailed-design-posthoc.md, router_history)

`load(paths)` reads each file's lines and keeps every distinct line text at its largest
per-file count, so overlapping snapshots do not double a line while identical same-second
lines (a doubled `client-reset idle`) survive. A router `<ts>` is the router's local wall
time; it becomes UTC through `utc_offset` (a `timedelta`), else `tz` (a `tzinfo`), else the
host zone. A line whose wall time happens twice (a DST repeated hour, only knowable with a
zone) is flagged `ambiguous_ts`, counted, and any window touching it is not `covered`.

Each event is `{kind, at, sess, agent, model, target, why, output_tokens, wall_s, owner,
ambiguous_ts}`: `kind` is post|stats|reset|refuse|unreachable; `at` is `YYYY-MM-DDTHH:MM:SSZ`;
`-` (no sess or agent) is None. For a `post`, `target` is local|upstream|fallback, `why` the
parenthesised reason (`model resident`, `slot held by X`, `... would breach the floor`) and
`owner` the `owner=` of a local route. A `stats` event's `why` is its stop_reason; a `reset`'s
is idle|mid-response (`target` = its route); an `unreachable`'s is the error text.
Indented lines, HEAD and STOPPED-AGENT lines are skipped; any other line that matches no
kind is counted in `malformed`. Nothing here raises on a bad line or an unreadable file.
`History.coverage` is the per-file `[first, last]` spans merged, minus every `gap` in an
`archive-gaps.ndjson` beside a file or in its `router-archive/` subdir.
"""
from __future__ import annotations

import bisect
import datetime
import json
import os
import re
from collections import Counter
from pathlib import Path

import router_stats as rs

UTC = datetime.timezone.utc
ARCHIVE_DIR = "router-archive"
GAPS_NAME = "archive-gaps.ndjson"
_FMT = "%Y-%m-%dT%H:%M:%SZ"

_TS_RE = re.compile(r"^\[(?P<ts>[^\]]+)\]")
_SKIP_RE = re.compile(r"^\[[^\]]*\](?:\s{2,}\S| (?:HEAD|STOPPED-AGENT) )")
_MODEL_RE = re.compile(r"^\[[^\]]+\] POST \S+\s+model=(?P<model>\S+)")
_TARGET_RE = re.compile(r"\s->\s(?P<target>.*?)(?:\s+\(\d+B\))?\s*$")
_ROUTE_RE = re.compile(r"^(?P<head>FALLBACK upstream|upstream|local)"
                       r"(?:\s*\((?P<why>.*)\))?(?:\s+owner=(?P<owner>\S+))?\s*$")
_REFUSE_RE = re.compile(
    r"^\[(?P<ts>[^\]]+)\] REFUSE model=(?P<model>\S+) free_mib=(?P<free>\d+) need_mib=(?P<need>\d+)"
    r" floor_mib=(?P<floor>\d+) sess=(?P<sess>\S+)(?: agent=(?P<agent>\S+))?\s*$")
_ERR_RE = re.compile(r"\((?P<err>.*)\)\s*$")
_SKIP = object()


def _dash(value):
    return None if value in (None, "", "-") else value


def _stamp(value):
    """A router `<ts>`, or an ISO stamp (`Z` ok), as a datetime; None if unreadable."""
    try:
        text = value.strip()
        return datetime.datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    except (AttributeError, TypeError, ValueError):
        return None


def _utc(value):
    """A datetime or ISO string as aware UTC (naive means UTC); None if unreadable."""
    dt = value if isinstance(value, datetime.datetime) else _stamp(value)
    if dt is None:
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


class _Clock:
    """Router wall time to UTC; `convert` returns (utc, other reading or None if unambiguous)."""

    def __init__(self, utc_offset, tz):
        self.utc_offset, self.tz, self._cache = utc_offset, tz, {}

    def _offset(self, naive, fold):
        if self.tz is not None:
            return naive.replace(tzinfo=self.tz, fold=fold).utcoffset()
        return naive.replace(fold=fold).astimezone().utcoffset()

    def _wall(self, utc):
        return (utc.astimezone(self.tz) if self.tz is not None else utc.astimezone()).replace(tzinfo=None)

    def _convert(self, dt):
        if dt.tzinfo is not None:
            return dt.astimezone(UTC), None
        if self.utc_offset is not None:
            return (dt - self.utc_offset).replace(tzinfo=UTC), None
        first = (dt - self._offset(dt, 0)).replace(tzinfo=UTC)
        second = (dt - self._offset(dt, 1)).replace(tzinfo=UTC)
        # Ambiguous only when both readings land back on this wall time (not a skipped one).
        if first != second and self._wall(first) == dt and self._wall(second) == dt:
            return first, second
        return first, None

    def convert(self, ts: str):
        if ts not in self._cache:
            dt = _stamp(ts)
            self._cache[ts] = None if dt is None else self._convert(dt)
        return self._cache[ts]


def _post(text, m):
    model, target = _MODEL_RE.match(text), _TARGET_RE.search(text)
    route = _ROUTE_RE.match(target.group("target")) if target else None
    if not (model and route):
        return None
    head = route.group("head")
    return {"kind": "post", "sess": _dash(m["sess"]), "agent": _dash(m["agent"]),
            "model": model["model"], "why": route.group("why"), "owner": route.group("owner"),
            "target": "fallback" if head.startswith("FALLBACK") else head}


def _fields(text, m):
    """The event fields for a line a regex matched; None if the POST target is unreadable."""
    if m.re is _REFUSE_RE:
        return {"kind": "refuse", "sess": _dash(m["sess"]), "agent": _dash(m["agent"]),
                "model": m["model"], "why": f"free_mib={m['free']} need_mib={m['need']} floor_mib={m['floor']}"}
    if m.re is rs.STATS_RE:
        return {"kind": "stats", "sess": _dash(m["sess"]), "agent": _dash(m["agent"]), "model": m["model"],
                "why": m["stop_reason"], "output_tokens": int(m["output_tokens"]), "wall_s": float(m["wall_s"])}
    if m.re is rs.RESET_RE:
        return {"kind": "reset", "sess": _dash(m["sess"]), "agent": _dash(m["agent"]),
                "why": m["mode"], "target": _dash(m["route"])}
    if m.re is rs.UNREACHABLE_RE:
        err = _ERR_RE.search(m.string[m.end():])
        return {"kind": "unreachable", "sess": _dash(m["sess"]), "agent": _dash(m["agent"]),
                "target": _dash(m["route"]), "why": err["err"] if err else None}
    return _post(m.string, m)


_MATCHERS = (rs.STATS_RE, rs.RESET_RE, rs.REQUEST_RE, rs.UNREACHABLE_RE, _REFUSE_RE)


def _parse(text, clock):
    """(event, utc, other reading) for a router line; `_SKIP` if ignored; None if unparseable."""
    if not _TS_RE.match(text):
        return None
    if _SKIP_RE.match(text):
        return _SKIP
    for rx in _MATCHERS:
        m = rx.match(text)
        if m is None:
            continue
        when = clock.convert(m["ts"])
        fields = _fields(text, m) if when else None
        if fields is None:
            return None
        utc, other = when
        ev = {"kind": None, "at": utc.strftime(_FMT), "sess": None, "agent": None, "model": None,
              "target": None, "why": None, "output_tokens": None, "wall_s": None, "owner": None,
              "ambiguous_ts": other is not None}
        ev.update(fields)
        return ev, utc, other
    return None


def _read(path):
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace").replace("\r", "").split("\n")
    except OSError:
        return None


def _span(texts, clock):
    stamps = [clock.convert(m["ts"]) for m in map(_TS_RE.match, texts) if m]
    utcs = [s[0] for s in stamps if s]
    return (min(utcs), max(utcs)) if utcs else None


def _merge(spans):
    out: list[list] = []
    for start, end in sorted(spans):
        if out and start <= out[-1][1]:
            out[-1][1] = max(out[-1][1], end)
        else:
            out.append([start, end])
    return [(s, e) for s, e in out]


def _subtract(intervals, gaps):
    for g0, g1 in gaps:
        kept = []
        for s, e in intervals:
            if g1 < s or g0 > e:
                kept.append((s, e))
                continue
            if s < g0:
                kept.append((s, g0))
            if g1 < e:
                kept.append((g1, e))
        intervals = kept
    return intervals


def _read_gaps(paths, clock):
    """Every `gap` interval in archive-gaps.ndjson beside a path or in its router-archive/."""
    seen, gaps = set(), []
    for p in paths:
        for d in (Path(p).parent, Path(p).parent / ARCHIVE_DIR):
            f = d / GAPS_NAME
            if f in seen:
                continue
            seen.add(f)
            for line in _read(f) or []:
                try:
                    pair = [_stamp_utc(v, clock) for v in json.loads(line)["gap"]]
                except (ValueError, KeyError, TypeError):
                    continue
                if len(pair) == 2 and None not in pair and pair[0] <= pair[1]:
                    gaps.append((pair[0], pair[1]))
    return gaps


def _stamp_utc(value, clock):
    when = clock.convert(value) if isinstance(value, str) else None
    return when[0] if when else None


def default_paths(env=None) -> list[Path]:
    """The live log plus every `router-*.log` (dated or snapshot) in its `router-archive/`."""
    env = os.environ if env is None else env
    live = rs.log_path(env)
    try:
        archived = sorted((live.parent / ARCHIVE_DIR).glob("router-*.log"))
    except OSError:
        archived = []
    return [live, *archived]


class History:
    """Merged router events (UTC-sorted), coverage, and window queries."""

    def __init__(self, rows, spans, gaps, malformed):
        rows.sort(key=lambda r: (r[0], r[1]))
        self.events = [r[2] for r in rows]
        self._times = [r[0] for r in rows]
        self._ambiguous_at = sorted(t for r in rows if r[3] for t in (r[0], r[3]))
        self._intervals = _subtract(_merge(spans), gaps)
        self.coverage = [(s.strftime(_FMT), e.strftime(_FMT)) for s, e in self._intervals]
        self.malformed = malformed
        self.ambiguous = sum(1 for r in rows if r[3])

    def window(self, start, end) -> list[dict]:
        """Events with start <= at <= end (inclusive), UTC-sorted; [] for an unreadable bound."""
        lo, hi = _utc(start), _utc(end)
        if lo is None or hi is None:
            return []
        return self.events[bisect.bisect_left(self._times, lo):bisect.bisect_right(self._times, hi)]

    def covered(self, start, end) -> bool:
        """True iff [start, end] lies inside one coverage interval and touches no ambiguous line."""
        lo, hi = _utc(start), _utc(end)
        if lo is None or hi is None or hi < lo:
            return False
        if not any(s <= lo and hi <= e for s, e in self._intervals):
            return False
        i = bisect.bisect_left(self._ambiguous_at, lo)
        return not (i < len(self._ambiguous_at) and self._ambiguous_at[i] <= hi)


def load(paths=None, *, utc_offset=None, tz=None, env=None) -> History:
    """Merge `paths` (default: `default_paths(env)`) into one History.

    `utc_offset` (a timedelta) wins over `tz` (a tzinfo); with neither, the host zone."""
    clock = _Clock(utc_offset, tz if utc_offset is None else None)
    plist = default_paths(env) if paths is None else [Path(p) for p in paths]
    counts: Counter = Counter()
    first_seen: dict[str, int] = {}
    spans = []
    for path in plist:
        lines = _read(path)
        if lines is None:
            continue
        per_file = Counter(line for line in lines if line.strip())
        for text, n in per_file.items():
            counts[text] = max(counts[text], n)
            first_seen.setdefault(text, len(first_seen))
        span = _span(per_file, clock)
        if span:
            spans.append(span)
    rows, malformed = [], 0
    for text, n in counts.items():
        parsed = _parse(text, clock)
        if parsed is _SKIP:
            continue
        if parsed is None:
            malformed += n
            continue
        ev, utc, other = parsed
        rows.extend((utc, first_seen[text], dict(ev), other) for _ in range(n))
    return History(rows, spans, _read_gaps(plist, clock), malformed)
