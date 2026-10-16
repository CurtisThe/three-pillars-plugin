"""budget_clock — the active-time wall clock of the /tp-pr-iterate budget.

design: fable-first-stops (Task 1.1)

The `wall-clock` signal measures the time spent **inside review rounds**, summed,
not the age of the loop. `round_scratch.prepare` stamps `budget_round_started_at`
into the iterate-state file when a round starts (`stamp_round_start`); the budget
tick then folds `now - budget_round_started_at` into `budget_active_elapsed_sec` and
clears the stamp (`active_elapsed`). Waiting, pauses and the fix passes between
rounds never count, so a loop resumed after a pause needs no
`pdw.guards.wall_clock_sec` override. A legacy state (only `started_at`) starts its
active total at 0. `started_at` stays the loop-start record: it still bootstraps and
still gates `budget-error` when unparseable.

Both fields are in `round_budget.BUDGET_FIELDS`, so a PR-key reset clears them and
`converge._seed_state` keeps them (its `budget_` prefix rule).

Stdlib only.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import iterate_state

ACTIVE_FIELD = "budget_active_elapsed_sec"
ROUND_START_FIELD = "budget_round_started_at"


def _aware(raw):
    """Aware datetime from an ISO string (a `Z` suffix is accepted), else None."""
    if not isinstance(raw, str):
        return None
    try:
        dt = datetime.fromisoformat(raw[:-1] + "+00:00" if raw.endswith("Z") else raw)
    except ValueError:
        return None
    return dt if dt.tzinfo is not None else None


def _stored_total(state: dict):
    """The stored active total; anything but a number >= 0 (incl. None) reads as 0."""
    raw = state.get(ACTIVE_FIELD)
    if isinstance(raw, (int, float)) and not isinstance(raw, bool) and raw >= 0:
        return raw
    return 0


def active_elapsed(state: dict, now) -> tuple[float, dict]:
    """`(total, updates)`: the active seconds so far and the fields to persist.

    `total` is the stored `budget_active_elapsed_sec` (None or garbage reads as 0)
    plus `now - budget_round_started_at` when that start parses as aware (a span
    that would be negative is clamped to 0). An unparseable or naive start adds
    nothing. `updates` always carries the new total and clears the round start, so
    a re-tick without a fresh stamp adds 0.
    """
    total = _stored_total(state)
    start = _aware(state.get(ROUND_START_FIELD))
    if start is not None:
        total = total + max(0.0, (now - start).total_seconds())
    return total, {ACTIVE_FIELD: total, ROUND_START_FIELD: None}


def stamp_round_start(state_path, started_at: str) -> bool:
    """Write `started_at` as `budget_round_started_at` into the existing state file.

    Every other field is left as read; the write goes through
    `iterate_state.write_state_atomic`. A missing file stays absent (no bootstrap:
    `run_round` owns that) and a file that is not a readable JSON object is left
    byte-identical for `run_round` to refuse. Returns True when the stamp was written.
    """
    path = Path(state_path)
    if not path.is_file():  # missing, dangling, or non-regular (a FIFO would block a read)
        return False
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(state, dict):
        return False
    state[ROUND_START_FIELD] = started_at
    iterate_state.write_state_atomic(path, state)
    return True
