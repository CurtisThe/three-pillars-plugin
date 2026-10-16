#!/usr/bin/env python3
"""stop_records.py — the durable per-stop records `router_daily.py` measures from.

design: m44-orphan-reaper (Part B — measurement; audit M3). A ladder W file is per
task: the preflight sweep deletes it once done and the next rung's `arm` overwrites
it, so `orphans` / `orphan_hold_s` cannot rest on W alone. Every stop is also one
line (`stopped_agents._entry` plus `orphaned_at` / `result`) in the ladder dir's
`stops.ndjson` (never swept) and, with a router, the stopped-agents file. `files`
lists those sources; `merged` folds them, plus any W still on disk, into one
`{attempt_id, agent_id, orphaned_at, stopped_at}` per (attempt, agent). Stdlib only.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stopped_agents  # noqa: E402

FIELDS = ("attempt_id", "agent_id", "orphaned_at", "stopped_at")


def files(stopped, ladder_dirs, *, default: bool, env) -> list[str]:
    """`stopped` files, each ladder dir's `stops.ndjson`, and (when `default`) the
    stopped-agents file at `stopped_agents.path(env)`."""
    out = list(stopped) + [str(Path(d) / stopped_agents.LADDER_STOPS) for d in ladder_dirs]
    if default:
        out.append(str(stopped_agents.path(env)))
    return out


def _num(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _w_states(ladder_dirs) -> list[dict]:
    found = []
    for d in ladder_dirs:
        for path in sorted(Path(d).glob("*.watch.json")):
            try:
                state = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(state, dict):
                found.append({k: state.get(k) for k in FIELDS})
    return found


def merged(ladder_dirs, stop_files) -> list[dict]:
    """One `{attempt_id, agent_id, orphaned_at, stopped_at}` per (attempt, agent):
    the earliest `orphaned_at` and the latest `stopped_at` across the durable
    records and the W files still on disk (retries write several lines). An
    entry with neither stamp is dropped; unreadable files are skipped."""
    found = [{"attempt_id": r.get("attempt"), "agent_id": r.get("agent"),
              "orphaned_at": r.get("orphaned_at"), "stopped_at": r.get("stopped_at")}
             for f in stop_files for r in stopped_agents.records(f)]
    out: dict = {}
    for s in found + _w_states(ladder_dirs):
        cur = out.setdefault((s["attempt_id"], s["agent_id"]),
                             {**s, "orphaned_at": None, "stopped_at": None})
        for key, pick in (("orphaned_at", min), ("stopped_at", max)):
            vals = [v for v in (_num(cur[key]), _num(s[key])) if v is not None]
            cur[key] = pick(vals) if vals else None
    return [s for s in out.values()
            if s["orphaned_at"] is not None or s["stopped_at"] is not None]
