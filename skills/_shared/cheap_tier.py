#!/usr/bin/env python3
"""cheap_tier.py — the cheap-tier eligibility table and its two keys.

design: cheap-tier-offload (Phase 1)

SLOTS names every step that may run on a cheap rung (a local model, its Sonnet
mirror, or plain code — D8), with the oracle that checks it and what a failed
check does. Every slot but handoff ships its local-first rung (operator 2026-10-07: the cheap
tier is the default; handoffs stay on Opus). A failed "drop" draft is dropped and today's path
runs; an "escalate" slot keeps its own runtime gate (classifier_judge's verdict file,
pr_fix_reproducer's in-loop spawn site), so default-on only means configured.

A slot runs cheap only when **both** keys are on (slot_rung):

1. the slot is configured: its SLOTS default, or models.<slot>: <rung> (load_slots, key 1);
   models.<slot>: "off" removes it for the repo;
2. the run's cheap_flag is on (key 2). The CLI always passes it on (an absent
   --cheap-tier is on, --cheap-tier=ab runs as on; one-cheap-engine 2.4), so
   models.<slot>: "off" is the one switch left.

EXCLUDED lists the roles that may never be cheap (every gate, audit, review,
design, merge and certification step); the loader refuses them by name. A key in
model_policy.ROLES is model_policy own and is skipped before any check.
Stdlib-only; no model is ever called here.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import NamedTuple

_SHARED = str(Path(__file__).resolve().parent)
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

import ladder_rungs  # noqa: E402 — in-repo, stdlib-only sibling
import model_policy  # noqa: E402 — in-repo, stdlib-only sibling


class Slot(NamedTuple):
    """One eligibility row. kind: "model" (a spawned cheap rung) or "code" (a
    script, no model — D8). effect: "pure" (a draft, proposal, attempt or scratch
    worktree) or "effectful" (pushes, posts or deletes; always "code" — D10)."""
    phase: int
    kind: str
    effect: str
    oracle: str
    rungs: tuple
    on_fail: str
    default: str | None


_MEDIUM = ("local-medium", "sonnet-medium")
_XHIGH = ("local-xhigh", "sonnet-xhigh")

SLOTS: dict[str, Slot] = {
    "task": Slot(1, "model", "pure", "task_verify", ("sonnet-xhigh",), "escalate",
                 "sonnet-xhigh"),
    "runbook": Slot(2, "code", "effectful", "exit_code", ("code",), "escalate", "code"),
    "base_sync_splice": Slot(2, "model", "pure", "zero_drop", _XHIGH, "drop", "local-xhigh"),
    "pr_fix_reproducer": Slot(2, "model", "pure", "reproducer_fixed", _XHIGH, "escalate",
                              "local-xhigh"),
    "classifier_judge": Slot(2, "model", "pure", "classifier_schema", _MEDIUM, "escalate",
                             "local-medium"),
    "history_line": Slot(3, "model", "pure", "prose_shape", _MEDIUM, "drop", "local-medium"),
    "handoff": Slot(3, "model", "pure", "prose_shape", _MEDIUM, "drop", None),
    "docs_draft": Slot(3, "model", "pure", "prose_shape", _MEDIUM, "drop", "local-medium"),
    # design: cheap-tier-review-prep — the review-prep slots (phase 4); each is a draft
    # the oracle checks, and a failed draft is dropped (the round reads the diff itself).
    "review_slice": Slot(4, "model", "pure", "hunk_bytes", _MEDIUM, "drop", "local-medium"),
    "review_refs": Slot(4, "model", "pure", "path_line", _MEDIUM, "drop", "local-medium"),
    "ci_log_triage": Slot(4, "model", "pure", "log_substring", _MEDIUM, "drop", "local-medium"),
    "repro_scaffold": Slot(4, "model", "pure", "observed_red", _XHIGH, "drop", "local-xhigh"),
}

# The review-prep slots, in order (design: cheap-tier-review-prep).
REVIEW_PREP_SLOTS = ("review_slice", "review_refs", "ci_log_triage", "repro_scaffold")

# Never cheap: every GATE_ROLES role and every non-rung AGENTS role but task, plus
# the design/plan/merge/ci-local steps, the #188 finalizer and digest_post
# (plan.md Deviations 1: the proof digest feeds a merge-gate predicate). Council
# members (audit-member) are cheap (one-cheap-engine 1.1); the council synth stays.
EXCLUDED: frozenset[str] = frozenset({
    "review", "impl-audit", "certify", "phase-check", "generator", "phase-worker", "reader",
    "council", "design", "plan", "orchestrator", "merge_gate", "land",
    "ci_local", "ci_local_stamp", "finalizer", "severity", "confirm", "digest_post",
})

MIRROR = {"local-medium": "sonnet-medium", "local-xhigh": "sonnet-xhigh"}
FLAG_VALUES = (None, "on", "ab")
OFF = "off"  # models.<slot>: "off" — the repo opts the slot out
WAIT, HALT = "wait", "halt"  # resolve's second element under a busy lease and busy_policy "wait"
_WAITABLE = ("busy", "busy-measure")  # lease states a `wait` run holds for (not unchecked)


def load_slots(config) -> dict[str, str]:
    """Key 1: {slot: rung} from config["models"] over each SLOTS default.

    A model_policy.ROLES key is skipped first. Then, per key, ValueError in this
    order: excluded, unknown slot, rung outside the slot rungs ("off" is always
    legal and removes the slot). A None or non-dict config (or models block) gives
    just the SLOTS defaults.
    """
    models = config.get("models") if isinstance(config, dict) else None
    if not isinstance(models, dict):
        models = {}
    out = {s: row.default for s, row in SLOTS.items() if row.default is not None}
    for key, value in models.items():
        if key in model_policy.ROLES:
            continue
        if key in EXCLUDED:
            raise ValueError(f"models.{key}: excluded from the cheap tier")
        if key not in SLOTS:
            names = ", ".join(SLOTS)
            raise ValueError(f"models.{key}: unknown role (cheap-tier slots: {names})")
        if value == OFF:
            out.pop(key, None)
            continue
        if value not in SLOTS[key].rungs:
            rungs = ", ".join(SLOTS[key].rungs)
            raise ValueError(f"models.{key}: rung {value!r} not allowed (rungs: {rungs}, "
                             f"or {OFF!r})")
        out[key] = value
    return out


def slot_rung(slot: str, config, *, cheap_flag) -> str | None:
    """The rung for slot when both keys are on, else None (today path unchanged).

    Both keys: cheap_flag in ("on", "ab") and the slot present in load_slots.
    An unknown slot raises ValueError. With the flag off the config is never read,
    so a bad config cannot change a run that has the flag off.
    """
    if slot not in SLOTS:
        raise ValueError(f"unknown cheap-tier slot {slot!r}")
    if cheap_flag not in ("on", "ab"):
        return None
    return load_slots(config).get(slot)


def _busy_action(waited_since, now) -> str:
    """`wait` until `strata_spawn.CEILING_S` has passed since `waited_since`, then `halt`
    (through `cheap_engine.busy_action`). Imported here: cheap_engine pulls in tier_ladder."""
    import cheap_engine
    import strata_spawn
    now = time.time() if now is None else now
    since = now if waited_since is None else waited_since
    return cheap_engine.busy_action("wait", since, now, strata_spawn.CEILING_S)


def resolve(rung: str, *, route_label: str, lease_state: str, busy_policy: str = "fallback",
            waited_since: float | None = None, now: float | None = None) -> tuple[str, str]:
    """(rung, why) after the route and lease check (Behavior 2). Pure.

    A local rung is kept only when route_label == "routed/ok" and lease_state ==
    "free"; otherwise it becomes MIRROR[rung], and why names the route label (when
    unrouted) or the lease state. A sonnet-* rung and the code rung pass through.

    busy_policy "wait" (one-cheap-engine 2.4) changes one case: a routed rung whose lease is
    busy keeps the local rung and answers `WAIT`, or `HALT` once the wait has run
    `strata_spawn.CEILING_S` from `waited_since` (default: `now`, a first poll). A route that
    is not routed/ok still mirrors (M51). "fallback" is the behaviour above.
    """
    if not rung.startswith("local-"):
        return rung, f"{rung}: not a local rung"
    if rung not in MIRROR:
        raise ValueError(f"local rung {rung!r} has no Sonnet mirror")
    mirror = MIRROR[rung]
    if route_label != "routed/ok":
        return mirror, f"{rung}->{mirror}: route {route_label}"
    if lease_state != "free":
        if busy_policy == "wait" and lease_state in _WAITABLE:
            return rung, _busy_action(waited_since, now)
        return mirror, f"{rung}->{mirror}: lease {lease_state}"
    return rung, f"{rung}: routed/ok, lease free"


def task_table(rows: list[dict]) -> list[dict]:
    """The task lever without --local: each task_eligibility local row becomes sonnet.

    A local row gets tier "sonnet", floored_from "local", the reason "cheap-tier: no
    --local", and start_rung recomputed through ladder_rungs.task_start (sonnet-xhigh,
    or sonnet-medium for a clerical row). Every other row is unchanged. The input
    rows are copied, never mutated.
    """
    out = []
    for row in rows:
        row = dict(row)
        if row.get("tier") == "local":
            row["tier"] = "sonnet"
            row["floored_from"] = "local"
            row["reasons"] = list(row.get("reasons") or []) + ["cheap-tier: no --local"]
            row["start_rung"] = ladder_rungs.task_start(row)[0]
        out.append(row)
    return out
