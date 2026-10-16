"""Wall-time budget for cheap-tier review prep loops — cheap-tier-review-prep (Task 3.4).

Tracks intervals of active prep work in `W/budget.json`, measuring the UNION of all
intervals so overlapping parallel units count once and sequential ones add. `start`
refuses once the union reaches the budget. `stop_batch` closes a batch of intervals at
one instant and stores a `late` flag per id so a later oracle run on one unit never
pushes time into another unit's recorded interval (D4).
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import review_prep

BUDGET_FILE = "budget.json"


def _path(work) -> Path:
    return Path(work) / BUDGET_FILE


def _now(now) -> float:
    return time.time() if now is None else now


def _write(work, data) -> None:
    path = _path(work)
    tmp = path.parent / (path.name + ".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(str(tmp), str(path))


def _read(work):
    """Return the parsed budget dict, or None when missing/corrupt."""
    path = _path(work)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict) or "intervals" not in data or "sec" not in data:
        return None
    return data


def begin(work, now=None) -> None:
    """Initialize `W/budget.json` with no intervals and the default budget."""
    _write(work, {"intervals": [], "sec": review_prep.PREP_BUDGET_SEC})


def _union_measure(intervals, now) -> float:
    """Lebesgue measure of the union of `intervals` (open ones end at `now`)."""
    spans = []
    for iv in intervals:
        start = iv["start"]
        end = iv["end"] if iv.get("end") is not None else now
        if end < start:
            end = start
        spans.append((start, end))
    if not spans:
        return 0.0
    spans.sort(key=lambda s: s[0])
    total = 0.0
    cur_start, cur_end = spans[0]
    for s, e in spans[1:]:
        if s > cur_end:
            total += cur_end - cur_start
            cur_start, cur_end = s, e
        else:
            if e > cur_end:
                cur_end = e
    total += cur_end - cur_start
    return total


def spent(work, now=None) -> float:
    """The measure of the union of all intervals; open intervals end at `now`.

    A missing or corrupt budget file fails safe: treated as fully spent.
    """
    data = _read(work)
    if data is None:
        return review_prep.PREP_BUDGET_SEC
    now = _now(now)
    return _union_measure(data.get("intervals", []), now)


def start(work, loop_id, now=None) -> bool:
    """Open a new interval for `loop_id` unless the budget is already spent."""
    data = _read(work)
    if data is None:
        return False
    now = _now(now)
    used = _union_measure(data.get("intervals", []), now)
    sec = data.get("sec", review_prep.PREP_BUDGET_SEC)
    if used >= sec:
        return False
    data.setdefault("intervals", []).append({"id": loop_id, "start": now, "end": None})
    _write(work, data)
    return True


def stop_batch(work, loop_ids, now=None) -> dict:
    """Close every open interval whose id is in `loop_ids` at one instant `now`.

    Computes `over = spent(now) > sec` once and stores it as each id's `late` flag
    (persisted in `W/budget.json`); returns `{id: late}` for the ids in `loop_ids`.
    """
    data = _read(work)
    if data is None:
        data = {"intervals": [], "sec": review_prep.PREP_BUDGET_SEC}
    now = _now(now)
    loop_ids = list(loop_ids)
    ids_set = set(loop_ids)
    intervals = data.get("intervals", [])
    for iv in intervals:
        if iv.get("end") is None and iv.get("id") in ids_set:
            iv["end"] = now
    data["intervals"] = intervals

    sec = data.get("sec", review_prep.PREP_BUDGET_SEC)
    used = _union_measure(intervals, now)
    over = used > sec

    late_map = data.get("late", {})
    if not isinstance(late_map, dict):
        late_map = {}
    for loop_id in loop_ids:
        late_map[loop_id] = over
    data["late"] = late_map

    _write(work, data)
    return {loop_id: late_map[loop_id] for loop_id in loop_ids}


def late(work, loop_id) -> bool:
    """The stored `late` flag for `loop_id`; an id never stopped is late."""
    data = _read(work)
    if data is None:
        return True
    late_map = data.get("late", {})
    if not isinstance(late_map, dict):
        return True
    if loop_id not in late_map:
        return True
    return bool(late_map[loop_id])
