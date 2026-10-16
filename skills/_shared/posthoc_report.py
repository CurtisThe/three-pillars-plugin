#!/usr/bin/env python3
"""posthoc_report.py — dispatch telemetry joined to the router history, as one report.

design: cheap-tier-local-routing (detailed-design-posthoc.md, posthoc_report)

    posthoc_report.py report [--root R] [--router-log P ...] [--since D] [--until D]
                             [--utc-offset ±HH:MM] [--json] [--no-archive]

`router_archive.archive` runs first unless `--no-archive`; it is fail-open, so its failure is a
footer note, never a failed report. Rows are `posthoc_rows.load` over every worktree of R
(`cheap_ab_state.worktree_roots`), each joined by `posthoc_join.join` to the router history
(`router_history.load`: the `--router-log` files, else the live log and its archive). A legacy
`unavailable` row takes its cause from its design's decisions.md `[tier]` block first (the
longest decisions.md of that design across the worktrees). Aggregates and the text table are
`posthoc_tables`: groups, attempts to pass, GPU reach by `measure`. For every recorded
measurement window (`measure_window.history`, expired ones included) that overlaps the range,
a measured-run block gives the span, the owner design's rows by label,
`other_session_local_requests` (`-> local` POSTs of non-owner sessions in the span) and its
subset `foreign_local_requests` (sessions no row of the run maps to). The footer gives router
coverage, uncovered rows, join quality, malformed and ambiguous router lines, the archive
result. A separated negative `--utc-offset -06:00` is accepted. Exit 0; 2 on a bad flag.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

import cheap_ab_state
import measure_window
import posthoc_join
import posthoc_rows
import posthoc_tables
import router_archive
import router_history

PRE_198 = dt.datetime(2026, 10, 1, 18, 45, 12, tzinfo=dt.timezone.utc)  # PR #198's merge (104dd993)
_OFFSET = re.compile(r"^([+-])(\d{2}):(\d{2})$")
_SUBS = ("tp-designs", "completed-tp-designs")
_when = posthoc_tables.when


def _offset(text) -> dt.timedelta:
    m = _OFFSET.match(str(text).strip())
    if not m or int(m[3]) >= 60:
        raise argparse.ArgumentTypeError(f"--utc-offset wants ±HH:MM, got {text!r}")
    delta = dt.timedelta(hours=int(m[2]), minutes=int(m[3]))
    return -delta if m[1] == "-" else delta


def _instant(text) -> str:
    if _when(text) is None:
        raise argparse.ArgumentTypeError(f"not an ISO time: {text!r}")
    return text


def _argv(argv) -> list[str]:
    """Join `--utc-offset V` into `--utc-offset=V`, so a negative offset is not read as a flag."""
    out, args = [], iter(argv)
    for arg in args:
        nxt = next(args, None) if arg == "--utc-offset" else None
        out.append(f"{arg}={nxt}" if nxt is not None else arg)
    return out


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="posthoc_report.py", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    rep = sub.add_parser("report", help="the post-hoc report over a repo's telemetry and the router log")
    rep.add_argument("--root", default=".", help="the repo (every worktree of it is read)")
    rep.add_argument("--router-log", dest="router_log", action="extend", nargs="+", default=None,
                     help="router log files (default: the live log plus its router-archive/)")
    rep.add_argument("--since", type=_instant, default=None, help="ISO time, inclusive")
    rep.add_argument("--until", type=_instant, default=None, help="ISO time, inclusive")
    rep.add_argument("--utc-offset", dest="utc_offset", type=_offset, default=None,
                     help="the router's wall-clock offset, ±HH:MM (default: the host zone)")
    rep.add_argument("--json", action="store_true", help="print the report as JSON")
    rep.add_argument("--no-archive", dest="no_archive", action="store_true",
                     help="skip running router_archive.archive first")
    return parser


def _archive(env) -> dict:
    try:
        return router_archive.archive(env=env)
    except Exception as exc:  # noqa: BLE001 — fail-open: the report runs on what is there
        return {"archived": 0, "reason": f"error: {exc}"}


def _decisions(roots) -> dict[str, str]:
    """Design dir name -> its longest decisions.md text across the roots (telemetry designs only)."""
    texts: dict[str, str] = {}
    for root in roots:
        for sub in _SUBS:
            for tel in sorted((Path(root) / "three-pillars-docs" / sub).glob("*/dispatch-telemetry.ndjson")):
                try:
                    text = (tel.parent / "decisions.md").read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                if len(text) > len(texts.get(tel.parent.name, "")):
                    texts[tel.parent.name] = text
    return texts


def _spawned(row) -> bool:
    if row.get("outcome") in (None, "unavailable"):
        return False
    return row.get("served_by") is not None or row.get("started_at") is not None


def enrich(row, history, decisions_text, reasons) -> dict:
    """The row plus `joined`, `spawned`, `cause` and `pre_198` (see posthoc_tables)."""
    probe = dict(row)
    if row.get("outcome") == "unavailable":
        probe["fallback"] = posthoc_rows.unavailable_reason(row, reasons)
    start = _when(row.get("started_at") or row.get("time"))
    return dict(row, joined=posthoc_join.join(probe, history), spawned=_spawned(row),
                cause=posthoc_rows.fail_reason(row, decisions_text) if row.get("outcome") == "FAIL" else None,
                pre_198=start is not None and start < PRE_198)


def _overlaps(window, since, until) -> bool:
    lo, hi = _when(since), _when(until)
    start, end = _when(window.get("start")), _when(window.get("end"))
    if start is None or end is None:
        return False
    return (hi is None or start <= hi) and (lo is None or end >= lo)


def _measured(window, rows, history) -> dict:
    lo, hi = _when(window["start"]), _when(window["end"])
    own = [r for r in rows if r["design"] == window["design"]
           and (t := _when(r.get("time"))) is not None and lo <= t < hi]
    owners = {r["joined"]["sess"] for r in own if r["joined"]["sess"]}
    run = {r["joined"]["sess"] for r in rows if r["joined"]["sess"]}
    counts = posthoc_join.other_local(history.window(lo, hi), owners, run)
    return {"design": window["design"], "start": window["start"], "end": window["end"],
            "rows": dict(Counter(r["joined"]["label"] for r in own)),
            "other_session_local_requests": counts["other"], "foreign_local_requests": counts["foreign"]}


def _footer(rows, history, archived) -> dict:
    return {"coverage": [list(span) for span in history.coverage],
            "uncovered": sum(r["joined"]["label"] == "uncovered" for r in rows),
            "join": dict(Counter(r["joined"]["join"] for r in rows if r["joined"]["join"])),
            "ambiguous_joins": sum((r["joined"]["ambiguous"] or 0) > 1 for r in rows),
            "malformed": history.malformed, "ambiguous_ts": history.ambiguous, "archive": archived}


def build(root, *, router_logs=None, since=None, until=None, utc_offset=None, archive=True, env=None) -> dict:
    """The whole report as one JSON-able dict (archive first, then rows, then the router history)."""
    env = os.environ if env is None else env
    archived = _archive(env) if archive else None
    roots = cheap_ab_state.worktree_roots(root)
    rows = posthoc_rows.load(root, since=since, until=until, roots=roots, env=env)
    history = router_history.load(router_logs, utc_offset=utc_offset, env=env)
    texts = _decisions(roots)
    reasons = {design: posthoc_rows.tier_reasons(text) for design, text in texts.items()}
    rows = [enrich(r, history, texts.get(r["design"], ""), reasons.get(r["design"], {})) for r in rows]
    windows = [w for w in measure_window.history(env) if _overlaps(w, since, until)]
    return {"range": {"since": since, "until": until}, "rows": len(rows),
            "groups": posthoc_tables.groups(rows),
            "attempts_to_pass": posthoc_tables.attempts_to_pass(rows),
            "gpu_reach": posthoc_tables.reach(rows),
            "measured_runs": [_measured(w, rows, history) for w in windows],
            "footer": _footer(rows, history, archived)}


def main(argv=None, env=None) -> int:
    """`env` (default `os.environ`) is injectable; argparse errors return 2, never raise."""
    try:
        args = _parser().parse_args(_argv(sys.argv[1:] if argv is None else argv))
    except SystemExit as exc:
        return 0 if exc.code in (0, None) else 2
    report = build(args.root, router_logs=args.router_log, since=args.since, until=args.until,
                   utc_offset=args.utc_offset, archive=not args.no_archive, env=env)
    sys.stdout.write(json.dumps(report, indent=1, sort_keys=True) + "\n" if args.json
                     else posthoc_tables.render(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
