#!/usr/bin/env python3
"""dispatch_tasks.py — task-attempt rows for dispatch-telemetry.ndjson, from ladder verdicts.

design: run-throughput (seat ruling G1, PR #178 live check #2 item 7; operator ruling Q3)

Every `tp-task-worker` attempt gets one `dispatch-telemetry.ndjson` row with `served_by`,
`wall_s`, `tokens` (null + `tokens_reason`, never 0) and `started_at` / `ended_at` (ISO UTC:
the transcript span `attempt_scan` read, else `tier_ladder`'s step bracket; null +
`timing_reason` for a pre-H2 record), built from the ladder verdict that already carries them. One writer per path, never both:

* **interactive** (`/tp-phase-implement --local`): the dispatcher runs this CLI on each
  finished ladder record (`local-dispatch.md` §2 step 7);
* **full-design** (Slot 7): `run_tier_3_5.py` writes the rows from the envelope's
  `telemetry.task_tiers[]` (`write_task_tiers`). `tp-worker` never writes them.

Rows carry an `attempt_key` (task, attempt index, rung, outcome, fingerprint, wall, tokens), and
a write skips a key the file already holds, so a re-fed record or envelope never doubles a row.
No `decisions.md` line: the `[tier]` entry already carries each attempt's `[dispatch]` line.
Stdlib only.

CLI: ``dispatch_tasks.py --design-dir D --record R|- [--phase N]`` (``-``: stdin, a
``tier_ladder.py telemetry`` item) → prints ``{"written": n, "skipped": m}``, exit 0.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

_SHARED = str(Path(__file__).resolve().parent)
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

import dispatch_log  # noqa: E402 — the ndjson file and its one-write append
import ladder_rungs  # noqa: E402 — rung → agent / effort / family
import served_rung  # noqa: E402 — FALLBACKS: the cause vocabulary
import transcript_usage  # noqa: E402 — token_total: the one row-total rule

_KEY_FIELDS = ("rung", "outcome", "fingerprint", "wall_s", "tokens")


def attempt_key(task_id, index: int, verdict: dict) -> str:
    """A stable id for one attempt, the same from a ladder record or its telemetry item.
    ``started_at``, when the verdict has it, makes it per dispatch (a re-dispatched task's
    evidence-free attempt is a new row); a verdict without it keeps its pre-H2 key."""
    basis = [str(task_id), index] + [verdict.get(k) for k in _KEY_FIELDS]
    if verdict.get("started_at"):
        basis.append(verdict["started_at"])
    return hashlib.sha256(json.dumps(basis, sort_keys=True, default=str).encode()).hexdigest()[:16]


NO_STAMPS = "the ladder record carries no attempt timestamps (recorded before H2)"
NO_START = ("the attempt's start is unknown: its ladder record was started before H2, "
            "so only the closing step is stamped")


NEVER_SPAWNED = "the attempt never spawned (unavailable, or an env-error with no spawn)"


def timing_reason(measured: dict, verdict: dict) -> str | None:
    """Why a row lacks a full span: None when both stamps are set, ``NEVER_SPAWNED`` for an
    attempt that did not run, ``NO_START`` when only the end is stamped (a pre-H2 record
    stepped after H2), else ``NO_STAMPS``."""
    if measured["started_at"] and measured["ended_at"]:
        return None
    if verdict.get("served_by") is None and verdict.get("outcome") in ("unavailable", "env-error"):
        return NEVER_SPAWNED
    return NO_START if measured["ended_at"] else NO_STAMPS


_tokens = transcript_usage.token_total  # 0 (or a dict summing to 0) is None, never 0

_USAGE_KEYS = (("input_tokens", "input"), ("cache_creation_input_tokens", "cache_write"),
               ("cache_read_input_tokens", "cache_read"), ("output_tokens", "output"),
               ("thinking_tokens", "thinking"))
_NO_USAGE = {"usage": None, "usage_source": None, "tokens_legacy": None}


def _usage_fields(value) -> dict:
    """``usage`` / ``usage_source`` / ``tokens_legacy`` from a new-shape ``tokens`` dict (the
    one carrying a ``source``); an old-shape value gives all three as None."""
    if not (isinstance(value, dict) and value.get("source")):
        return dict(_NO_USAGE)
    return {"usage": {out: value.get(key) for out, key in _USAGE_KEYS},
            "usage_source": value["source"], "tokens_legacy": _tokens(value.get("legacy"))}


def _fallback(v: dict):
    """The row's ``fallback`` cause from the verdict's ``reason`` (never ``why``): None unless the
    outcome is ``unavailable`` / ``env-error`` or the reason is a listed cause (``runaway:`` ...
    is ``runaway``); an unlisted reason on those outcomes is ``unrecorded``."""
    reason = v.get("reason")
    if isinstance(reason, str) and reason.startswith("runaway:"):
        return "runaway"
    if v.get("outcome") in ("unavailable", "env-error") or reason in served_rung.FALLBACKS:
        return served_rung.normalize(reason)
    return None


def rows(record: dict, phase=None) -> list[dict]:
    """One ndjson row per well-formed verdict of a ladder record or telemetry item."""
    task_id = record.get("task_id")
    phase = str(phase) if phase is not None else str(task_id or "-").split(".", 1)[0]
    out = []
    for i, v in enumerate(record.get("verdicts") or []):
        rung = v.get("rung") if isinstance(v, dict) else None
        if not isinstance(rung, str) or rung not in ladder_rungs.RUNGS:
            continue
        tokens = _tokens(v.get("tokens"))
        measured = dispatch_log.measure(
            wall_s=v.get("wall_s") if isinstance(v.get("wall_s"), (int, float)) else None,
            started_at=v.get("started_at"), ended_at=v.get("ended_at"),
            tokens=tokens, family=ladder_rungs.family(rung),
            tokens_reason=None if tokens else "the attempt scan reported no usage total")
        row = {"role": "task", "agent": ladder_rungs.agent(rung), "task_id": task_id,
               "model": v.get("model") or "-", "effort": ladder_rungs.effort(rung),
               "route": record.get("route") or "-", "reason": v.get("why") or "-",
               "outcome": v.get("outcome"), "rung": rung, "phase": phase,
               **measured, **_usage_fields(v.get("tokens")),
               "served_by": v.get("served_by"),  # the ladder's one derivation
               "timing_reason": timing_reason(measured, v), "attempt_key": attempt_key(task_id, i, v)}
        if isinstance(v.get("served"), dict):
            row["served"] = v["served"]
        if fallback := _fallback(v):
            row["fallback"] = fallback
        if v.get("lease_wait_s") is not None:  # the ladder's wait; absent on an old verdict
            row["lease_wait_s"] = v["lease_wait_s"]
        out.append(row)
    return out


def existing_keys(ndjson) -> set:
    """The ``attempt_key``s already in an ndjson file (missing/unreadable → empty)."""
    path = Path(ndjson)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return set()
    keys = set()
    for line in lines:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict) and rec.get("attempt_key"):
            keys.add(rec["attempt_key"])
    return keys


def write(design_dir, records: list[dict], phase=None) -> dict:
    """Append each record's attempt rows not already in the ndjson → ``{written, skipped}``."""
    seen, written, skipped = existing_keys(Path(design_dir) / dispatch_log.NDJSON_NAME), 0, 0
    for record in records:
        if not isinstance(record, dict):
            continue
        for row in rows(record, phase):
            if row["attempt_key"] in seen:
                skipped += 1
                continue
            dispatch_log.write_ndjson(design_dir, row)
            seen.add(row["attempt_key"])
            written += 1
    return {"written": written, "skipped": skipped}


def write_task_tiers(design_dir, telemetry) -> dict:
    """The full-design writer: every ``telemetry.task_tiers[]`` item (malformed → skipped)."""
    tiers = telemetry.get("task_tiers") if isinstance(telemetry, dict) else None
    return write(design_dir, tiers if isinstance(tiers, list) else [])


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="task-attempt dispatch telemetry rows")
    parser.add_argument("--design-dir", required=True, type=Path)
    parser.add_argument("--record", required=True, help="a ladder record JSON file, or - (stdin)")
    parser.add_argument("--phase")
    args = parser.parse_args(argv)
    try:
        text = sys.stdin.read() if args.record == "-" else Path(args.record).read_text(encoding="utf-8")
        out = write(dispatch_log.resolve_dir(args.design_dir), [json.loads(text)], args.phase)
    except (OSError, ValueError) as exc:  # telemetry never blocks a dispatch
        out = {"written": 0, "skipped": 0, "error": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(out, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
