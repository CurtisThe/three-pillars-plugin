"""cheap_ab_served.py — the served-arm dimension of the cheap-tier A/B harness.

design: cheap-tier-local-routing (detailed-design.md §Interfaces `cheap_ab_served.py`)

`cheap_ab.arm` stays the `cheap|opus` pairing key. This module is the second dimension: which
arm actually served a row, so a mirror fallback is never scored as a local (or deliberate
Sonnet) arm. It holds all the new scoring and rendering (`cheap_ab.summarize` / `report` only
call it) and imports nothing from `cheap_ab`.

- `served_arm(row)`: `opus` (an opus rung), `code` (rung `code`, a runbook row rated as today),
  else the arm `served_rung.served` derives from the row's own evidence (legacy rows with no
  `requested_rung` use `rung`); a row that never spawned is `fallback`.
- `fallbacks(rows)`: `{slot: {reason: n}}` over every row whose local request was not (fully)
  served locally, plus a passed `runaway` / `watchdog-error` cause.
- `reach(rows, *, measure=None)`: `{slot: {eligible, local, share}}`. Eligible = the
  `requested_rung` or the `rung` is `local-*`. `measure=None` is the organic reach: rows that
  met a measurement window leave it (a `local-busy-measure` row, tagged `measure` or not, is a
  non-owner row) and are reported per window state, `"owner"` / `"other"`.
- `served_summary(pairs)`: each complete pair's cheap cell rated under its `served_arm`; a pair
  whose cheap cell is `fallback` drops from rating (it is still counted in `fallbacks`). On a
  local slot the `opus` cell counts only the pairs the local arm served.
- `render_tables(summary, rows)`: the served-arm, fallback and reach markdown tables.

Pure and stdlib-only; no I/O.
"""
from __future__ import annotations

import sys
from collections.abc import Mapping
from pathlib import Path

_SHARED = str(Path(__file__).resolve().parent)
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

import served_rung  # noqa: E402 — in-repo, stdlib-only sibling (the one served derivation)

WINDOW_STATES = ("owner", "other")  # the `measure` values a row can carry
RATED = ("pass", "fail")  # the `oracle` values a row may be rated under
_SUMMARY_ARMS = ("local", "opus")  # the cells `flip_verdict` reads: always present


def _family(rung) -> str:
    return str(rung or "").split("-", 1)[0]


def _is_local(rung) -> bool:
    return isinstance(rung, str) and rung.startswith("local-")


def _eligible(row: dict) -> bool:
    """A row that asked for a local rung (`requested_rung`, or `rung` on a legacy row)."""
    return _is_local(row.get("requested_rung")) or _is_local(row.get("rung"))


def _evidence(row: dict) -> tuple[str | None, str | None]:
    """(served arm or None, fallback reason or None) from the row's own fields."""
    rung = row.get("rung")
    if _family(rung) == "opus":
        return "opus", None
    if rung == "code":
        return "code", None
    return served_rung.served(row.get("requested_rung"), rung, row.get("served_by"),
                              row.get("fallback"), row.get("fallback_requests") or 0)


def served_arm(row: dict) -> str:
    """The arm that served `row`: opus | code | local | sonnet-mirror | sonnet | fallback."""
    return _evidence(row)[0] or "fallback"


def fallbacks(rows: list[dict]) -> dict[str, dict[str, int]]:
    """`{slot: {reason: n}}`: a mirror row `local-busy` gives `local-busy: 1`. An unlisted
    reason is counted as `unrecorded`; opus, code and cleanly served rows carry none."""
    out: dict[str, dict[str, int]] = {}
    for row in rows:
        slot, reason = row.get("slot"), _evidence(row)[1]
        if slot and reason:
            counts = out.setdefault(slot, {})
            key = served_rung.normalize(reason)
            counts[key] = counts.get(key, 0) + 1
    return out


def _window(row: dict, reason: str | None) -> str | None:
    """`owner` / `other` for a row that met a measurement window, else None (organic). A
    `local-busy-measure` row is a non-owner row even when a task row left it untagged."""
    if reason == "local-busy-measure":
        return "other"
    return row.get("measure") if row.get("measure") in WINDOW_STATES else None


def reach(rows: list[dict], *, measure: str | None = None) -> dict[str, dict]:
    """`{slot: {eligible, local, share}}` over the local-eligible rows in window state
    `measure` (None: organic). A busy mirror is eligible with local 0; a slot with no
    eligible row is absent."""
    counts: dict[str, list[int]] = {}
    for row in rows:
        arm, reason = _evidence(row)
        if not row.get("slot") or not _eligible(row) or _window(row, reason) != measure:
            continue
        cell = counts.setdefault(row["slot"], [0, 0])
        cell[0] += 1
        cell[1] += arm == "local"
    return {slot: {"eligible": e, "local": n, "share": n / e} for slot, (e, n) in counts.items()}


def _cell() -> dict:
    return {"n": 0, "pass": 0, "rate": None}


def _is_complete(members: list[dict]) -> bool:
    """Exactly one opus-rung row and one cheap row, each carrying a rated oracle."""
    return (len(members) == 2 and all(r.get("oracle") in RATED for r in members)
            and sorted(_family(r.get("rung")) == "opus" for r in members) == [False, True])


def _slotted(pairs):
    """`(slot, members)` per pair: the slot of a `(source, slot, pair id)` key when `pairs` is
    the mapping `cheap_ab.summarize` builds, else the slot of the pair's own rows."""
    items = pairs.items() if isinstance(pairs, Mapping) else ((None, m) for m in pairs)
    for key, members in items:
        members = list(members)
        keyed = isinstance(key, tuple) and len(key) == 3
        yield key[1] if keyed else (members[0].get("slot") if members else None), members


def served_summary(pairs) -> dict[str, dict]:
    """`{slot: {arm: {n, pass, rate}, "local_slot": bool}}` over the complete pairs.

    `pairs` is what `cheap_ab.summarize` builds, `{(source, slot, pair id): [rows]}`, or any
    iterable of member lists (the slot then comes from the rows). Each complete pair's cheap
    row is rated under `served_arm` and its opus row under `opus`; a pair whose cheap cell is
    `fallback` drops from rating whole. `local_slot` is true when any member of any complete
    pair asked for a local rung, dropped pairs included. On a local slot the `opus` cell counts
    only the pairs whose cheap cell is `local` (a Sonnet-mirror pair still rates its cheap
    cell), so `flip_verdict` compares `local` and `opus` on the same inputs. The `local` and
    `opus` cells are always present, as `flip_verdict` reads them."""
    out: dict[str, dict] = {}
    rated: dict[str, list[list[tuple[str, dict]]]] = {}
    for slot, members in _slotted(pairs):
        if not slot or not _is_complete(members):
            continue
        entry = out.setdefault(slot, {**{a: _cell() for a in _SUMMARY_ARMS}, "local_slot": False})
        entry["local_slot"] = entry["local_slot"] or any(_eligible(r) for r in members)
        arms = [(served_arm(r), r) for r in members]
        if not any(arm == "fallback" for arm, _ in arms):
            rated.setdefault(slot, []).append(arms)
    for slot, rated_pairs in rated.items():
        entry = out[slot]
        for arms in rated_pairs:
            unpaired = entry["local_slot"] and not any(arm == "local" for arm, _ in arms)
            for arm, row in arms:
                if arm == "opus" and unpaired:
                    continue  # the opus half of a pair the local arm never served
                cell = entry.setdefault(arm, _cell())
                cell["n"] += 1
                cell["pass"] += row.get("oracle") == "pass"
    for entry in out.values():
        for arm, cell in entry.items():
            if arm != "local_slot" and cell["n"]:
                cell["rate"] = cell["pass"] / cell["n"]
    return out


def _table(headers: list[str], body: list[list[str]]) -> str:
    if not body:
        return "none"
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    return "\n".join(lines + ["| " + " | ".join(cells) + " |" for cells in body])


def _share(value: float) -> str:
    return f"{value:.2f}"


def render_tables(summary: dict, rows: list[dict]) -> str:
    """The served-arm table (from `summary`), the fallback table and the GPU-reach table (from
    `rows`), as markdown; an empty section reads `none`."""
    arms = [[slot, arm, str(c["n"]), str(c["pass"]), _share(c["rate"])]
            for slot, entry in sorted(summary.items())
            for arm, c in sorted(entry.items()) if arm != "local_slot" and c["n"]]
    falls = [[slot, reason, str(n)] for slot, counts in sorted(fallbacks(rows).items())
             for reason, n in sorted(counts.items())]
    states = (("organic", None), ("owner", "owner"), ("other", "other"))
    reached = sorted((slot, order, label, v) for order, (label, state) in enumerate(states)
                     for slot, v in reach(rows, measure=state).items())
    reaches = [[slot, label, str(v["eligible"]), str(v["local"]), _share(v["share"])]
               for slot, _order, label, v in reached]
    return "\n".join([
        "**Served arms** (each pair's cheap cell, by the arm that served it)",
        _table(["slot", "served arm", "n", "pass", "rate"], arms), "",
        "**Fallbacks** (local requests not served locally, by reason)",
        _table(["slot", "reason", "n"], falls), "",
        "**GPU reach** (local-eligible dispatches that reached the GPU, by measurement window)",
        _table(["slot", "window", "eligible", "local", "share"], reaches)])
