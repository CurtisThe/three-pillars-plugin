#!/usr/bin/env python3
"""posthoc_rows.py — every worktree's dispatch-telemetry rows, merged, timed and tagged.

design: cheap-tier-local-routing (detailed-design-posthoc.md, posthoc_rows)

`load` reads `three-pillars-docs/{tp-designs,completed-tp-designs}/*/dispatch-telemetry.ndjson`
under each root (default `cheap_ab_state.worktree_roots`). Lines merge per (design dir name, line
text) at their largest per-file count, so nested checkouts and a `tp-designs/X` +
`completed-tp-designs/X` pair never double a row. A row is the JSON row plus `design`; `ordinal`
(n-th of its task, rung and outcome in file order); `measure` (its own field, else
`measure_window.role_at`, `off` with no time); `time`/`time_src`: `started_at` (`own`), or for a
null-time row that of the next timed row of its `task_id` at or before `until` (`task`), else the
nearest preceding timed row (`before`), else the next (`after`), else None, which a bounded run
drops. `since`/`until` (ISO or datetime, naive = UTC) bound `time`, inclusive.

`tier_reasons` maps `(task_id, rung, n)` to the cause of the n-th `unavailable` verdict in a
decisions.md `### [tier]` block; `unavailable_reason` is a row's `fallback`, else that cause, else
`unrecorded`. `fail_reason` classes a FAIL (`reset`, `generation`, `wall-clock`, `runaway-other`,
`fail`), pairing the row to its verdict by `gen-stats local_requests=A/B`, else `ordinal`.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import json
import os
import re
from collections import Counter
from pathlib import Path

import cheap_ab_state
import measure_window

_TIER = re.compile(r"^### \[tier\] (?P<task>\S+)")
_ITEM_SPLIT = re.compile(r";\s+(?=(?:local|sonnet|opus)(?:-\w+)?\s+[A-Za-z][\w-]*(?:\s\(|;|\s*$))")
_ITEM = re.compile(r"^(?P<rung>\S+)\s+(?P<outcome>[\w-]+)\s*(?:\((?P<reason>.*)\))?")
_DISPATCH = re.compile(r"^\[dispatch\] task \S+ \S+ tp-task-worker-(?P<rung>\S+) .*: (?P<outcome>\S+)\s*$")
_STATS = re.compile(r"gen-stats local_requests=(\d+)/(\d+)")
_CLASSES = (("generation client-reset", "reset"), ("generation stop_reason=", "generation"),
            ("wall-clock", "wall-clock"))


def _when(value) -> dt.datetime | None:
    try:
        when = value if isinstance(value, dt.datetime) else dt.datetime.fromisoformat(
            value.strip().replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None
    return when if when.tzinfo else when.replace(tzinfo=dt.timezone.utc)


def _texts(roots) -> dict[str, list[list[str]]]:
    """Design dir name -> each telemetry file's stripped non-empty lines, in discovery order."""
    found: dict[str, list[list[str]]] = {}
    for root in roots:
        for sub in ("tp-designs", "completed-tp-designs"):
            for path in sorted((Path(root) / "three-pillars-docs" / sub).glob("*/dispatch-telemetry.ndjson")):
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                found.setdefault(path.parent.name, []).append([x.strip() for x in text.splitlines() if x.strip()])
    return found


def _merge(files: list[list[str]]) -> list[str]:
    """Each line text at its largest per-file count; a line only a later file has lands after its neighbour."""
    merged: list[str] = []
    for lines in files:
        have, seen, at = Counter(merged), Counter(), -1
        for text in lines:
            seen[text] += 1
            if seen[text] <= have[text]:
                at = [i for i, t in enumerate(merged) if t == text][seen[text] - 1]
            else:
                merged.insert(at := at + 1, text)
    return merged


def _donor(i, rows, own, until) -> tuple[int | None, str | None]:
    """Which row's `started_at` row `i` is placed at, and how (the null-time rule)."""
    if own[i] is not None:
        return i, "own"
    task, timed = rows[i].get("task_id"), [j for j, w in enumerate(own) if w is not None]
    rules = (("task", [j for j in timed if j > i and task is not None and rows[j].get("task_id") == task
                       and (until is None or own[j] <= until)]),
             ("before", [j for j in reversed(timed) if j < i]), ("after", [j for j in timed if j > i]))
    return next(((c[0], src) for src, c in rules if c), (None, None))


def _design_rows(design, lines, until, windows) -> list[tuple[dict, dt.datetime | None]]:
    rows = []
    for line in lines:
        with contextlib.suppress(ValueError):  # a bad line is skipped
            if isinstance(row := json.loads(line), dict):
                rows.append(row)
    own, ordinals, out = [_when(r.get("started_at")) for r in rows], Counter(), []
    for i, row in enumerate(rows):
        j, src = _donor(i, rows, own, until)
        when = None if j is None else own[j]
        key = (row.get("task_id"), row.get("rung"), row.get("outcome"))
        ordinals[key] += 1
        measure = row.get("measure")
        if measure not in ("owner", "other", "off"):
            measure = "off" if when is None else measure_window.role_at(windows, design, when)
        out.append((dict(row, design=design, measure=measure, time_src=src, ordinal=ordinals[key],
                         time=None if j is None else rows[j]["started_at"]), when))
    return out


def load(root, *, since=None, until=None, roots=None, env=None) -> list[dict]:
    """The merged, timed, tagged rows of the repo at `root`, filtered to `[since, until]` when given."""
    lo, hi = _when(since), _when(until)
    if (since is not None and lo is None) or (until is not None and hi is None):
        raise ValueError(f"unreadable since/until: {since!r} {until!r}")
    roots = cheap_ab_state.worktree_roots(root) if roots is None else roots
    windows = measure_window.history(os.environ if env is None else env)
    rows, bounded = [], lo is not None or hi is not None
    for design, files in sorted(_texts(roots).items()):
        rows += [row for row, when in _design_rows(design, _merge(files), hi, windows) if not bounded or (
            when is not None and (lo is None or when >= lo) and (hi is None or when <= hi))]
    return rows


def _blocks(text) -> list[tuple[str, list[str]]]:
    """`(task_id, lines)` for each `### [tier] <task_id>` block of a decisions.md."""
    blocks, current = [], None
    for line in str(text).splitlines():
        if m := _TIER.match(line):
            current = (m["task"], [])
            blocks.append(current)
        elif line.startswith("#"):
            current = None
        elif current is not None:
            current[1].append(line)
    return blocks


def _verdicts(lines) -> list[tuple[str, str, str | None]]:
    """`(rung, outcome, reason)` per item of the block's `**Verdicts**` line."""
    line = next((x for x in lines if x.startswith("**Verdicts**:")), "")
    items = _ITEM_SPLIT.split(line.partition(":")[2].strip())
    return [(m["rung"], m["outcome"], m["reason"]) for m in map(_ITEM.match, items) if m]


def tier_reasons(decisions_text) -> dict[tuple[str, str, int], str]:
    """`(task_id, rung, n)` -> the cause of the n-th `unavailable` verdict for that task and rung."""
    seen, out = Counter(), {}
    for task, lines in _blocks(decisions_text):
        for rung, outcome, reason in _verdicts(lines):
            if outcome == "unavailable":
                seen[task, rung] += 1
                if reason and reason.strip():
                    out[task, rung, seen[task, rung]] = reason.strip()
    return out


def unavailable_reason(row, reasons) -> str:
    """An `unavailable` row's cause: its own `fallback`, else the `[tier]` verdict's, else `unrecorded`."""
    return str(row["fallback"]) if row.get("fallback") else reasons.get(
        (row.get("task_id"), row.get("rung"), row.get("ordinal")), "unrecorded")


def _fail_stats(lines, rung) -> list[tuple[int, int] | None]:
    """For each FAIL dispatch line of `rung`: its `gen-stats local_requests=A/B` as `(A, B)`, else None."""
    out, open_line = [], False
    for line in lines:
        if m := _DISPATCH.match(line):
            open_line = m["rung"] == rung and m["outcome"] == "FAIL"
            out += [None] if open_line else []
        elif open_line and (s := _STATS.search(line)):
            out[-1] = (int(s[1]), int(s[2]))
    return out


def _classify(cause: str) -> str:
    text = cause.strip()
    if not text.startswith("runaway:"):
        return "fail"
    rest = text[len("runaway:"):].strip()
    return next((name for prefix, name in _CLASSES if rest.startswith(prefix)), "runaway-other")


def fail_reason(row, decisions_text) -> str:
    """A FAIL row's class: `reset`, `generation`, `wall-clock`, `runaway-other` or `fail`."""
    task, rung = row.get("task_id"), row.get("rung")
    fails, stats = [], []
    for block_task, lines in _blocks(decisions_text):
        if block_task == task:
            fails += [reason or "" for r, outcome, reason in _verdicts(lines) if (r, outcome) == (rung, "FAIL")]
            stats += _fail_stats(lines, rung)
    served = row.get("served") if isinstance(row.get("served"), dict) else {}
    key, ordinal = (served.get("local_requests"), served.get("turns")), row.get("ordinal")
    if fails and len(stats) == len(fails) and key in stats:
        cause = fails[stats.index(key)]
    elif isinstance(ordinal, int) and 1 <= ordinal <= len(fails):
        cause = fails[ordinal - 1]
    else:
        cause = fails[0] if ordinal is None and len(fails) == 1 else ""
    return _classify(cause)
