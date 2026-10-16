#!/usr/bin/env python3
"""router_checks.py — the resume report: classifier calls per Strata request.

design: strata-classifier-cost-followups (A5, the resume criterion as a report)

Reads the LIVE router log only (`router_stats.log_path` — archives are never read) and
reports, per session and per time window: Strata requests (`-> local`), classifier
calls (`model=claude-sonnet-5 sess=… -> upstream` with no `agent=` and no `effort=`;
model overridable), their bytes, and classifier calls per Strata request. The target
is 0.035 (5% of the 0.70 baseline): over it the one summary line starts `ALARM` and
the exit is 1 — logged by the run, never a gate. The summary line ends `alarm=none`, `alarm=ratio`,
`alarm=main_thread_strata:<id8,...>` or both joined by `+`; exit 1 means either alarm kind. A missing log prints `no router log`
and exits 0; a window with no Strata request reports `ratio=n/a` and exits 0.

The window counts classifier calls only in sessions with ≥1 Strata request in the
window (design ruling, `decisions.md` "router_checks ratio and run-end placement");
classifier calls in other sessions are reported as `other=<n>` and do not move the
ratio. Nothing here raises: an unreadable line or file is skipped.

Alongside the ratio, `main` reports the S3 leak (`router_main_thread.leak_sessions`): a
session whose MAIN thread took Strata — an unagented `-> local` request beside an
unagented `-> upstream` request that is not a classifier call. Each such session prints
one `ALARM main_thread_strata <sess>` after the summary and `--by-session` lines and
makes the exit 1, beside the ratio alarm. Sanctioned all-Strata sessions and
agent-tagged child Strata stay clean.
"""
from __future__ import annotations

import argparse
import datetime
import os
import re
import sys
from pathlib import Path

import router_stats

DEFAULT_CLASSIFIER_MODEL = "claude-sonnet-5"
DEFAULT_TARGET = 0.035

# One request regex over the router's request line:
#   [<ts>] POST /v1/messages  model=strata  sess=7814fd93  agent=ab3ad173  effort=high
#        -> local strata wait owner=7814fd93  (167953B)
# `mid` is whatever sits between `sess=` and `->` (the `agent=`/`effort=` fields, or
# nothing at all) — that is what separates a child-spawn call from a classifier call.
REQUEST_RE = re.compile(
    r"^\[(?P<ts>[^\]]+)\] POST \S+\s+model=(?P<model>\S+)\s+sess=(?P<sess>\S+)"
    r"(?P<mid>.*?)\s->\s(?P<route>\w+).*\((?P<bytes>\d+)B\)\s*$")


def parse_line(line, classifier_model: str = DEFAULT_CLASSIFIER_MODEL) -> dict | None:
    """A `strata` or `classifier` event dict, or None for any other line.

    A Strata request is a local-routed request (`-> local …`). A classifier call is
    `classifier_model` routed `-> upstream` with no `agent=` and no `effort=` — the
    host's own call, which carries no child-agent or effort field. Anything else (an
    `agent=`/`effort=` Sonnet call, an `-> upstream` Opus call, a LOCAL-STATS line) is
    neither."""
    if not isinstance(line, str):
        return None
    m = REQUEST_RE.match(line)
    if not m:
        return None
    ev = {"ts": m["ts"], "model": m["model"], "sess": m["sess"],
          "route": m["route"], "bytes": int(m["bytes"])}
    if m["route"].startswith("local"):
        return {"kind": "strata", **ev}
    if (m["model"] == classifier_model and m["route"] == "upstream"
            and "agent=" not in m["mid"] and "effort=" not in m["mid"]):
        return {"kind": "classifier", **ev}
    return None


def bound(value):
    """A `--since`/`--until` bound as epoch seconds: an epoch number, or a local
    `<ts>`-shaped date-time; None when absent or unreadable."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        pass
    try:
        return datetime.datetime.fromisoformat(str(value)).timestamp()
    except (TypeError, ValueError):
        return None


def parse(path, since=None, until=None, classifier_model: str = DEFAULT_CLASSIFIER_MODEL):
    """The strata/classifier events in `path` whose `<ts>` is within [since, until].

    `since`/`until` are epoch seconds (or None for unbounded); a missing or unreadable
    file, and any line that is not a request of either kind, give nothing."""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    events = []
    for line in text.splitlines():
        ev = parse_line(line, classifier_model)
        if ev is None:
            continue
        epoch = router_stats.ts_epoch(ev["ts"])
        if epoch is None:
            continue
        if since is not None and epoch < since:
            continue
        if until is not None and epoch > until:
            continue
        events.append(ev)
    return events


def summarize(events) -> dict:
    """{strata, classifier, other, bytes, ratio, sessions} over parsed events.

    `classifier` counts only calls in sessions with ≥1 Strata request in the window;
    the rest are `other` and never move `ratio`. `sessions` maps each session seen in
    first-appearance order to its own {strata, classifier, bytes}. `ratio` is None when
    the window has no Strata request."""
    sessions: dict[str, dict] = {}
    strata = classifier = other = total_bytes = 0

    def row(sess):
        return sessions.setdefault(sess, {"strata": 0, "classifier": 0, "bytes": 0})

    for ev in events:
        cell = row(ev["sess"])
        cell["bytes"] += ev["bytes"]
        total_bytes += ev["bytes"]
        if ev["kind"] == "strata":
            cell["strata"] += 1
            strata += 1
        elif ev["kind"] == "classifier":
            cell["classifier"] += 1
            classifier += 1
    for sess, cell in sessions.items():
        if cell["strata"] == 0:
            other += cell["classifier"]
            classifier -= cell["classifier"]
    return {"strata": strata, "classifier": classifier, "other": other,
            "bytes": total_bytes, "ratio": (classifier / strata) if strata else None,
            "sessions": sessions}


def _ratio(summary) -> str:
    return "n/a" if summary["ratio"] is None else f"{summary['ratio']:.3f}"


def format_line(summary, target: float, leaks=()) -> str:
    """The one summary line: `strata=… classifier=… other=… bytes=… ratio=… target=… alarm=…`.

    `alarm=` names every alarm (`none`, `ratio`, `main_thread_strata:<id8,...>`, or both joined
    by `+`), so logging this line alone records a leak. It starts `ALARM` when the ratio is over
    target and ends `OK` only when there is no alarm at all."""
    ratio_alarm = summary["ratio"] is not None and summary["ratio"] > target
    alarms = (["ratio"] if ratio_alarm else []) + (
        [f"main_thread_strata:{','.join(leaks)}"] if leaks else [])
    body = (f"strata={summary['strata']} classifier={summary['classifier']}"
            f" other={summary['other']} bytes={summary['bytes']}"
            f" ratio={_ratio(summary)} target={target:.3f}"
            f" alarm={'+'.join(alarms) or 'none'}")
    if ratio_alarm:
        return f"ALARM {body}"
    return body if alarms else f"{body} OK"


def session_line(sess: str, cell: dict) -> str:
    """`sess=<8> strata=<n> classifier=<n> bytes=<n> ratio=<r>` for one session."""
    ratio = "n/a" if not cell["strata"] else f"{cell['classifier'] / cell['strata']:.3f}"
    return (f"sess={sess} strata={cell['strata']} classifier={cell['classifier']}"
            f" bytes={cell['bytes']} ratio={ratio}")


def default_log_path() -> Path:
    """The live router log — `router_stats.log_path(os.environ)`, never an archive."""
    return router_stats.log_path(os.environ)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Classifier calls per Strata request.")
    ap.add_argument("--since", help="Window start: epoch seconds or 'YYYY-MM-DD HH:MM:SS'")
    ap.add_argument("--until", help="Window end: epoch seconds or 'YYYY-MM-DD HH:MM:SS'")
    ap.add_argument("--by-session", action="store_true", help="One line per session")
    ap.add_argument("--classifier-model", default=DEFAULT_CLASSIFIER_MODEL)
    ap.add_argument("--target", type=float, default=DEFAULT_TARGET)
    ap.add_argument("--log", help="Router log path (default: the live log)")
    args = ap.parse_args(argv)

    path = Path(args.log) if args.log else default_log_path()
    if not path.is_file():
        print("no router log")
        return 0
    since, until = bound(args.since), bound(args.until)
    events = parse(path, since, until, args.classifier_model)
    summary = summarize(events)
    import router_main_thread  # here, not at top: it imports this module's REQUEST_RE

    leaks = router_main_thread.leak_sessions(path, since, until, args.classifier_model)
    print(format_line(summary, args.target, leaks))
    if args.by_session:
        for sess, cell in summary["sessions"].items():
            print(session_line(sess, cell))
    for sess in leaks:
        print(f"ALARM main_thread_strata {sess}")
    ratio_alarm = summary["ratio"] is not None and summary["ratio"] > args.target
    return 1 if ratio_alarm or leaks else 0


if __name__ == "__main__":
    sys.exit(main())
