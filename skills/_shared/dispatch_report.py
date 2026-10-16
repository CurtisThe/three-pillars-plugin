#!/usr/bin/env python3
"""dispatch_report.py — the per-role/variant timing table (measurement only).

design: run-throughput (detailed-design.md §File table — dispatch_report.py)

Reads the two telemetry sources `dispatch_log` and the ladder write: the
`<design>/dispatch-telemetry.ndjson` records (`{role, agent, outcome, served?}`)
and, when given, one `ladder_entry.to_telemetry` dict (`task_tiers[].verdicts[]`
with `rung`, `outcome` and `wall_s`). Groups both into role × variant rows:
counts, outcomes, wall p50/max (nearest-rank) and `served` local/turn totals
with the ratio. `totals()` sums wall and tokens per rung and per phase (operator
ruling Q3, Decision 12): a missing token total stays missing (counted, never 0).
Nothing here gates on the tables — they are read by a human. Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

_SHARED = str(Path(__file__).resolve().parent)
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

import dispatch_tasks  # noqa: E402 — attempt_key: a telemetry verdict already in the ndjson
import ladder_rungs  # noqa: E402 — rung algebra (variant name for a task rung)
import strata_effort  # noqa: E402 — split/render_split (the Strata effort line)
import transcript_usage  # noqa: E402 — token_total: the one row-total rule

NDJSON_NAME = "dispatch-telemetry.ndjson"

# Columns of the markdown table, in order.
COLUMNS = ("role", "variant", "count", "outcomes", "wall_p50", "wall_max",
           "served_local_requests", "served_turns", "served_ratio")


def _rows_from_ndjson(ndjson: Path) -> list[tuple[str, str, str, dict | None, float | None]]:
    """`(role, variant, outcome, served, wall_s)` per decodable record line.

    `variant` is the record's `agent` name, or `inline` for the dispatcher's
    own slot attempt (`agent: None`). Malformed lines never raise: a report
    tool must not crash on a half-written record."""
    rows: list[tuple[str, str, str, dict | None, float | None]] = []
    try:
        text = ndjson.read_text(encoding="utf-8")
    except OSError:
        return rows
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not isinstance(rec, dict):
            continue
        role = str(rec.get("role") or "-")
        agent = rec.get("agent")
        variant = agent if agent is not None else "inline"
        outcome = str(rec.get("outcome") or "-")
        served = rec.get("served") if isinstance(rec.get("served"), dict) else None
        wall = rec.get("wall_s")
        wall = float(wall) if isinstance(wall, (int, float)) and not isinstance(wall, bool) else None
        rows.append((role, variant, outcome, served, wall))
    return rows


_ndjson_keys = dispatch_tasks.existing_keys  # the task rows' attempt_keys


def _fresh_verdicts(tier: dict, seen: set) -> list[dict]:
    """``tier``'s dict verdicts whose attempt the ndjson does not already hold."""
    vs = tier.get("verdicts") if isinstance(tier.get("verdicts"), list) else []
    return [v for i, v in enumerate(vs) if isinstance(v, dict)
            and dispatch_tasks.attempt_key(tier.get("task_id"), i, v) not in seen]


def _rows_from_telemetry(telemetry, seen: set = frozenset()) -> list[tuple[str, str, str, dict | None, float | None]]:
    """`(role, variant, outcome, served, wall_s)` per `task_tiers[].verdicts[]` item.

    `role` is the constant `"task"`; the variant is the spawn agent for the
    rung (`ladder_rungs.agent`), or `inline` for an opus rung the dispatcher
    ran itself. A `telemetry` that is not a mapping (or whose `task_tiers`
    is malformed) contributes no rows."""
    rows: list[tuple[str, str, str, dict | None, float | None]] = []
    if not isinstance(telemetry, dict):
        return rows
    task_tiers = telemetry.get("task_tiers")
    if not isinstance(task_tiers, list):
        return rows
    for tier in task_tiers:
        if not isinstance(tier, dict):
            continue
        for v in _fresh_verdicts(tier, seen):
            rung = str(v.get("rung") or "")
            if not rung:
                continue
            agent = ladder_rungs.agent(rung)
            variant = agent if agent is not None else "inline"
            served = v.get("served") if isinstance(v.get("served"), dict) else None
            wall = v.get("wall_s")
            wall = float(wall) if isinstance(wall, (int, float)) and not isinstance(wall, bool) else None
            rows.append(("task", variant, str(v.get("outcome") or "-"), served, wall))
    return rows


def report(ndjson, telemetry=None) -> list[dict]:
    """The timing table as `list[dict]`, one row per (role, variant), sorted by
    (role, variant). Counts and outcomes come from both sources; `wall_p50` /
    `wall_max` only when a `wall_s` was recorded (ndjson rows carry none);
    `served_local_requests` / `served_turns` are the summed totals and
    `served_ratio` is `local_requests / turns` (None when either total is
    missing or turns is 0). `ndjson` may be a path (missing file or no
    decodable line → no rows) and `telemetry` the `ladder_entry.to_telemetry`
    dict (its `task_tiers[]` verdicts)."""
    path = Path(ndjson)
    grouped: dict[tuple[str, str], dict] = {}
    for role, variant, outcome, served, wall in (
            _rows_from_ndjson(path) + _rows_from_telemetry(telemetry, _ndjson_keys(path))):
        g = grouped.setdefault((role, variant), {
            "role": role, "variant": variant, "count": 0,
            "outcomes": Counter(), "walls": [],
            "local_requests": 0, "turns": 0, "has_served": False,
        })
        g["count"] += 1
        g["outcomes"][outcome] += 1
        if wall is not None:
            g["walls"].append(wall)
        if served is not None:
            g["has_served"] = True
            lr = served.get("local_requests")
            turns = served.get("turns")
            if isinstance(lr, (int, float)) and not isinstance(lr, bool):
                g["local_requests"] += lr
            if isinstance(turns, (int, float)) and not isinstance(turns, bool):
                g["turns"] += turns
    table: list[dict] = []
    for (role, variant) in sorted(grouped):
        g = grouped[(role, variant)]
        ratio = (g["local_requests"] / g["turns"]) if (
            g["has_served"] and g["turns"]) else None
        table.append({
            "role": role, "variant": variant, "count": g["count"],
            "outcomes": dict(sorted(g["outcomes"].items())),
            "wall_p50": statistics.median(g["walls"]) if g["walls"] else None,
            "wall_max": max(g["walls"]) if g["walls"] else None,
            "served_local_requests": g["local_requests"] if g["has_served"] else None,
            "served_turns": g["turns"] if g["has_served"] else None,
            "served_ratio": ratio,
        })
    return table


def _num(value) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


_tokens = transcript_usage.token_total  # 0 (or a dict summing to 0) is None, never 0


def _source(usage_source, tokens) -> str:
    """The unit a token count is in: the record's ``usage_source``, else the verdict tokens'
    ``source``, else ``legacy`` (the older ``input + output`` figure)."""
    if isinstance(usage_source, str) and usage_source:
        return usage_source
    source = tokens.get("source") if isinstance(tokens, dict) else None
    return source if isinstance(source, str) and source else "legacy"


def _measured(ndjson: Path, telemetry) -> list[tuple[str, str, float | None, int | None, str]]:
    """``(rung, phase, wall_s, tokens, source)`` per ndjson record and ladder verdict."""
    out = []
    try:
        lines = ndjson.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    for line in lines:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict):
            out.append((str(rec.get("rung") or rec.get("agent") or "inline"),
                        str(rec.get("phase") or "-"), _num(rec.get("wall_s")),
                        _tokens(rec.get("tokens")),
                        _source(rec.get("usage_source"), rec.get("tokens"))))
    tiers = telemetry.get("task_tiers") if isinstance(telemetry, dict) else None
    seen = _ndjson_keys(ndjson)
    for tier in tiers if isinstance(tiers, list) else []:
        if not isinstance(tier, dict):
            continue
        phase = str(tier.get("task_id") or "-").split(".", 1)[0]
        for v in _fresh_verdicts(tier, seen):
            if v.get("rung"):
                out.append((str(v["rung"]), phase, _num(v.get("wall_s")), _tokens(v.get("tokens")),
                            _source(None, v.get("tokens"))))
    return out


def totals(ndjson, telemetry=None) -> dict:
    """``{"rung": {key: row}, "phase": {key: row}}``; a row is ``{count, wall_s, tokens,
    tokens_missing}`` — wall and tokens summed over what was recorded, a record with no
    token total counted in ``tokens_missing`` (its null never becomes 0). A row that took
    a count marked with a ``usage_source`` (the final-usage unit, ``input + cache_write +
    output``) also has ``tokens_by_source``, ``{source: tokens}`` summing to ``tokens``,
    the unmarked older counts under ``legacy``; a row of only ``legacy`` counts has none."""
    out: dict = {"rung": {}, "phase": {}}
    shares: dict = {}  # (axis, key) -> {source: tokens}
    for rung, phase, wall, tokens, source in _measured(Path(ndjson), telemetry):
        for axis, key in (("rung", rung), ("phase", phase)):
            row = out[axis].setdefault(key, {"count": 0, "wall_s": 0.0, "tokens": 0,
                                             "tokens_missing": 0})
            row["count"] += 1
            row["wall_s"] = round(row["wall_s"] + (wall or 0.0), 1)
            if tokens is None:
                row["tokens_missing"] += 1
            else:
                row["tokens"] += tokens
                share = shares.setdefault((axis, key), {})
                share[source] = share.get(source, 0) + tokens
    for (axis, key), share in shares.items():
        if set(share) - {"legacy"}:  # a legacy-only row keeps its shape
            out[axis][key]["tokens_by_source"] = share
    return out


def render_totals(tot: dict) -> str:
    """The totals table; the trailing ``tokens_by_source`` column names each unit's share,
    a row of only unmarked counts reading ``legacy: <tokens>``."""
    lines = ["| by | key | count | wall_s | tokens | tokens_missing | tokens_by_source |",
             "|---|---|---|---|---|---|---|"]
    for axis in ("rung", "phase"):
        for key, row in sorted(tot[axis].items()):
            share = row.get("tokens_by_source") or ({"legacy": row["tokens"]}
                                                    if row["tokens"] else None)
            lines.append(f"| {axis} | {key} | {row['count']} | {row['wall_s']:.1f} | "
                         f"{row['tokens']} | {row['tokens_missing']} | {_cell(share)} |")
    return "\n".join(lines) + "\n"


def _cell(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.1f}"
    if isinstance(value, dict):
        return ", ".join(f"{k}: {v}" for k, v in sorted(value.items()))
    return str(value)


def render_markdown(table: list[dict]) -> str:
    """The markdown table: header + separator + one line per row. A `table`
    of `[]` is exactly the header and separator — nothing after them."""
    lines = [
        "| " + " | ".join(COLUMNS) + " |",
        "|" + "|".join("---" for _ in COLUMNS) + "|",
    ]
    for row in table:
        lines.append("| " + " | ".join(_cell(row[c]) for c in COLUMNS) + " |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    """`report --ndjson PATH [--telemetry PATH]` — the markdown table on stdout.
    A missing or unreadable ndjson (or telemetry) file is an empty table, not
    an error; always exits 0."""
    parser = argparse.ArgumentParser(description="per-role/variant timing table")
    parser.add_argument("--ndjson", required=True, type=Path,
                        help=f"path to a dispatch ndjson (default name: {NDJSON_NAME})")
    parser.add_argument("--telemetry", type=Path, default=None,
                        help="optional candidate.v1 telemetry JSON: {\"task_tiers\": [one "
                             "tier_ladder.py telemetry item per task]}")
    args = parser.parse_args(argv)

    telemetry = None
    if args.telemetry is not None:
        try:
            telemetry = json.loads(args.telemetry.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            telemetry = None
    print(render_markdown(report(args.ndjson, telemetry)))
    tot = totals(args.ndjson, telemetry)
    if tot["rung"]:  # no records: the role table's header alone, as before
        print(render_totals(tot))
    counts = strata_effort.split(args.ndjson)
    if counts:  # no Strata rows: no split line at all
        print(strata_effort.render_split(counts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
