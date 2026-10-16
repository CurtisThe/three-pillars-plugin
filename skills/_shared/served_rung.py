"""served_rung.py — the one served-rung derivation and fallback-reason vocabulary.

design: cheap-tier-local-routing (detailed-design.md §Interfaces `served_rung.py`, §Notes 4, 5)

Pure, no I/O. `served()` turns the evidence a dispatch row carries into the arm that actually
served it, so a mirror fallback is never scored as a local (or deliberate Sonnet) arm. Evidence
comes first: only `served_by == "local"` can yield the `local` arm, and the requested rung never
decides it.

`served_by` is `router_stats.served_by`: `local`, `fallback` (a local-family attempt with no
LOCAL-STATS request), `sonnet`, `opus`, or None (nothing ran).
"""
from __future__ import annotations

# The arm that served a row. `sonnet-mirror` is a Sonnet run standing in for a local request;
# `sonnet` is a slot deliberately configured on a Sonnet rung.
SERVED = ("local", "sonnet-mirror", "sonnet", "opus")

# Why a local request was not (fully) served locally. `unrouted-slot` is the label `cheap_route`
# emits for a slot that is not routed at all (§Notes 4); the rest are the detailed-design list.
FALLBACKS = (
    "local-busy", "local-busy-measure", "orphan-holds-gpu", "refuse", "unreachable",
    "unrouted", "unrouted-slot", "router-fallback", "partial-fallback", "runaway",
    "background-spawn-failed", "watchdog-error", "unrecorded",
)

# Causes of a failed local run that survive on the row even though the slot answered (§Notes 5).
_RUN_CAUSES = ("runaway", "watchdog-error")


def normalize(reason) -> str:
    """`reason` when it is a listed fallback, else `unrecorded` (None and non-strings included)."""
    return reason if isinstance(reason, str) and reason in FALLBACKS else "unrecorded"


def _is_local(rung) -> bool:
    return isinstance(rung, str) and rung.startswith("local-")


def served(requested, rung, served_by, fallback, fallback_requests=0):
    """-> (served_rung, fallback). `served_rung` is one of SERVED or None (never spawned).

    - `local` with `fallback_requests > 0`: the slot was lost mid-attempt and later turns went
      upstream, so `("sonnet-mirror", "partial-fallback")`, never the local arm.
    - `local` otherwise: `("local", None)`; a passed `runaway` / `watchdog-error` stays the
      returned cause (the slot served, the run still failed; §Notes 5, and also when partial).
    - `fallback` (the router served a local rung upstream): `("sonnet-mirror", fallback or
      "router-fallback")`.
    - `sonnet` while a `local-*` rung was requested (B2): `("sonnet-mirror", fallback or
      "unrecorded")`; otherwise a deliberate `("sonnet", None)`.
    - `opus`: `("opus", None)`.
    - anything else (None: never spawned): `(None, fallback or "unrecorded")`.
    """
    run_cause = fallback if fallback in _RUN_CAUSES else None
    if served_by == "local":
        if isinstance(fallback_requests, int) and fallback_requests > 0:
            return "sonnet-mirror", run_cause or "partial-fallback"
        return "local", run_cause
    if served_by == "fallback":
        return "sonnet-mirror", fallback or "router-fallback"
    if served_by == "sonnet":
        if _is_local(requested) or _is_local(rung):
            return "sonnet-mirror", fallback or "unrecorded"
        return "sonnet", None
    if served_by == "opus":
        return "opus", None
    return None, fallback or "unrecorded"


def from_router(text) -> str | None:
    """The fallback reason a router refusal text names, else None."""
    if not isinstance(text, str):
        return None
    if "slot held by" in text:
        return "local-busy"
    if "would breach the floor" in text:
        return "refuse"
    return None
