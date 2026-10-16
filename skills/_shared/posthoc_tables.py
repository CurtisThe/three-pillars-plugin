#!/usr/bin/env python3
"""posthoc_tables.py — the post-hoc report's pure aggregates and its text table.

design: cheap-tier-local-routing (detailed-design-posthoc.md, posthoc_report)

Every aggregate reads the report's enriched rows: a `posthoc_rows.load` row plus `joined` (its
`posthoc_join.join`), `spawned` (it ran: not `unavailable`, and a server or a start time),
`cause` (a FAIL's `posthoc_rows.fail_reason`, else None) and `pre_198` (started before PR
#198's merge). A row's group is (`slot`, else `role`; `requested_rung`, else `rung`).

- `groups(rows)`: per group, n; served-rung counts (`never-spawned` when nothing ran); pass rate
  (a cheap-slot row on `oracle == "pass"`, any other row on `outcome` PASS; see `_passed`)
  over spawned rows only, overall, `clean` / `contended` (the join label) and `adjusted`
  (without the pre-#198 `reset` runaway FAILs; every other runaway stays in); runaways by
  cause; `wall_s` (`elapsed_s` when the row has it) median and nearest-rank p90 over spawned
  rows; tokens sum and median; router output tokens; fallbacks by reason.
- `attempts_to_pass(rows)`: per `(design, task_id)` of `role: task`, spawned attempts in
  `started_at` order up to the first PASS, keyed by the first spawned attempt's rung; a task
  with no PASS is `unpassed`, never averaged.
- `reach(rows)`: GPU reach = served `local` / rows requesting a `local-*` rung, overall and by
  `measure`; `local-busy-measure` rows leave the organic (`off`) reach and are counted beside it.
- `render(report)`: the text table of a whole report.
"""
from __future__ import annotations

import datetime as dt
import math
import statistics
from collections import Counter

RUNAWAYS = ("reset", "generation", "wall-clock", "runaway-other")
MEASURES = ("owner", "other", "off")
NEVER = "never-spawned"
BUSY_MEASURE = "local-busy-measure"
_EPOCH = dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)


def when(value) -> dt.datetime | None:
    """An ISO stamp (`Z` ok, naive = UTC) as aware UTC; None if absent or unreadable."""
    if value is None:
        return None
    try:
        stamp = dt.datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=dt.timezone.utc)


def requested(row):
    return row.get("requested_rung") or row.get("rung")


def role(row):
    return row.get("slot") or row.get("role")


def _num(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _passed(row) -> bool:
    """A cheap-slot row (`slot` set) passes on `oracle == "pass"`, the field `cheap_ab_served`
    rates it on (its `outcome` is the action: accept / drop / escalate); a null or missing
    `oracle` is never a pass. Any other row passes on `outcome` PASS."""
    if row.get("slot"):
        return row.get("oracle") == "pass"
    return str(row.get("outcome") or "").lower() == "pass"


def rate(rows) -> dict:
    """`{pass, n, rate}`; `rate` is None over no rows."""
    n, k = len(rows), sum(map(_passed, rows))
    return {"pass": k, "n": n, "rate": round(k / n, 4) if n else None}


def percentile(values, q):
    """The nearest-rank `q` percentile (a value that occurred); None for no values."""
    ordered = sorted(values)
    return ordered[max(1, math.ceil(q * len(ordered))) - 1] if ordered else None


def _median(values):
    return statistics.median(values) if values else None


def _wall(row):
    elapsed = _num(row.get("elapsed_s"))
    return elapsed if elapsed is not None else _num(row.get("wall_s"))


def _group(key, rows) -> dict:
    spawned = [r for r in rows if r["spawned"]]
    adjusted = [r for r in spawned if not (r["cause"] == "reset" and r["pre_198"])]
    walls = [w for w in map(_wall, spawned) if w is not None]
    tokens = [t for t in (_num(r.get("tokens")) for r in rows) if t is not None]
    causes = Counter(r["cause"] for r in rows if r["cause"] in RUNAWAYS)

    def labelled(name):
        return rate([r for r in spawned if r["joined"]["label"] == name])

    return {"role": key[0], "rung": key[1], "n": len(rows), "spawned": len(spawned),
            "served": dict(Counter(r["joined"]["served_rung"] or NEVER for r in rows)),
            "pass_rate": {"overall": rate(spawned), "adjusted": rate(adjusted),
                          "clean": labelled("clean"), "contended": labelled("contended")},
            "pre_198_resets": len(spawned) - len(adjusted),
            "runaways": {c: causes[c] for c in RUNAWAYS},
            "wall_s": {"median": _median(walls), "p90": percentile(walls, 0.9)},
            "tokens": {"sum": sum(tokens), "median": _median(tokens)},
            "router_output_tokens": sum(r["joined"]["router_output_tokens"] or 0 for r in rows),
            "fallbacks": dict(Counter(r["joined"]["fallback"] for r in rows if r["joined"]["fallback"]))}


def groups(rows) -> list[dict]:
    """One aggregate per (role, requested rung), sorted by role then rung."""
    by: dict[tuple, list] = {}
    for row in rows:
        by.setdefault((role(row), requested(row)), []).append(row)
    return [_group(k, by[k]) for k in sorted(by, key=lambda k: (str(k[0] or ""), str(k[1] or "")))]


def _start_key(row):
    stamp = when(row.get("started_at") or row.get("time"))
    return stamp is None, stamp or _EPOCH


def _attempt_stats(counts) -> dict:
    done = [n for n in counts if n is not None]
    return {"tasks": len(counts), "passed": len(done), "unpassed": len(counts) - len(done),
            "mean": round(statistics.fmean(done), 4) if done else None,
            "median": _median(done), "max": max(done, default=None)}


def attempts_to_pass(rows) -> dict:
    """`{start rung: {tasks, passed, unpassed, mean, median, max}}` over task attempts."""
    tasks: dict[tuple, list] = {}
    for row in rows:
        if row.get("role") == "task" and row.get("task_id") is not None and row["spawned"]:
            tasks.setdefault((row["design"], str(row["task_id"])), []).append(row)
    per_rung: dict = {}
    for attempts in tasks.values():
        attempts = sorted(attempts, key=_start_key)  # stable: file order breaks a tie
        first = next((i for i, r in enumerate(attempts) if _passed(r)), None)
        per_rung.setdefault(requested(attempts[0]), []).append(None if first is None else first + 1)
    return {rung: _attempt_stats(per_rung[rung]) for rung in sorted(per_rung, key=lambda k: str(k or ""))}


def _reach(rows) -> dict:
    n = sum(r["joined"]["served_rung"] == "local" for r in rows)
    return {"local": n, "rows": len(rows), "reach": round(n / len(rows), 4) if rows else None}


def reach(rows) -> dict:
    """GPU reach over `local-*` requests: `all`, then each `measure` (`off` minus BUSY_MEASURE)."""
    local = [r for r in rows if str(requested(r) or "").startswith("local-")]
    out = {"all": _reach(local)}
    for measure in MEASURES:
        bucket = [r for r in local if r.get("measure") == measure]
        if measure != "off":
            out[measure] = _reach(bucket)
            continue
        busy = [r for r in bucket if r["joined"]["fallback"] == BUSY_MEASURE]
        out[measure] = dict(_reach([r for r in bucket if r not in busy]), local_busy_measure=len(busy))
    return out


# --- the text table -------------------------------------------------------------------------

def _pairs(counts) -> str:
    return " ".join(f"{k}={v}" for k, v in sorted(counts.items(), key=lambda kv: str(kv[0]))) or "-"


def _frac(r) -> str:
    return f"{r['pass']}/{r['n']} ({'-' if r['rate'] is None else format(r['rate'], '.2f')})"


def _share(r) -> str:
    return f"{r['local']}/{r['rows']} ({'-' if r['reach'] is None else format(r['reach'], '.2f')})"


def _value(v) -> str:
    return "-" if v is None else format(v, "g") if isinstance(v, float) else str(v)


def _group_lines(g) -> list[str]:
    p, w, t = g["pass_rate"], g["wall_s"], g["tokens"]
    return [f"{g['role'] or '-'}  {g['rung'] or '-'}  n={g['n']}  spawned={g['spawned']}",
            f"  served: {_pairs(g['served'])}",
            f"  pass: {_frac(p['overall'])}  adjusted {_frac(p['adjusted'])}  clean {_frac(p['clean'])}"
            f"  contended {_frac(p['contended'])}",
            f"  runaways: {_pairs(g['runaways'])}",
            f"  wall_s: median {_value(w['median'])}  p90 {_value(w['p90'])}  tokens: sum {t['sum']}"
            f"  median {_value(t['median'])}  router output tokens: {g['router_output_tokens']}",
            f"  fallbacks: {_pairs(g['fallbacks'])}"]


def render(report) -> str:
    """The whole report as a text table."""
    rng = report["range"]
    lines = [f"post-hoc report  since={rng['since'] or '-'}  until={rng['until'] or '-'}  rows={report['rows']}"]
    for group in report["groups"]:
        lines += ["", *_group_lines(group)]
    lines += ["", "attempts to pass (by start rung):"]
    lines += [f"  {rung or '-'}  " + _pairs({k: _value(v) for k, v in s.items()})
              for rung, s in report["attempts_to_pass"].items()] or ["  -"]
    reach_ = report["gpu_reach"]
    lines += ["", "GPU reach (served local / local-* rows): " + "  ".join(
        f"{k} {_share(reach_[k])}" for k in ("all", *MEASURES))
        + f"  [{BUSY_MEASURE} out of off: {reach_['off']['local_busy_measure']}]"]
    for run in report["measured_runs"]:
        lines += ["", f"measured run {run['design']}  {run['start']} to {run['end']}",
                  f"  owner rows: {_pairs(run['rows'])}",
                  f"  other_session_local_requests={run['other_session_local_requests']}"
                  f"  foreign_local_requests={run['foreign_local_requests']}"]
    f = report["footer"]
    lines += ["", "coverage: " + ("  ".join(f"{s}..{e}" for s, e in f["coverage"]) or "none"),
              f"uncovered rows: {f['uncovered']}  join: {_pairs(f['join'])}  ambiguous joins: {f['ambiguous_joins']}",
              f"malformed lines: {f['malformed']}  ambiguous stamps: {f['ambiguous_ts']}",
              "archive: " + ("skipped" if f["archive"] is None else _pairs(f["archive"]))]
    return "\n".join(lines) + "\n"
