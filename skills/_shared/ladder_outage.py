"""ladder_outage.py — a zero-request clock-out is a backend outage, not a runaway.

design: ladder-diagnose-and-size-pins (Task 1.6, Behaviors B4, B6)

A local attempt that ends at its wall clock with router evidence of zero requests (no local
and no fallback request logged for its agent) never ran: the backend is down, and a second
local rung would pay another full clock for the same nothing. ``reclass`` turns that
``runaway`` into ``backend-outage``; any request, or no ``served`` evidence, leaves it a
``runaway``. ``step`` applies the run's busy policy at once: ``wait`` keeps the rung (halting
at the busy ceiling, as ``ladder_busy``), ``fallback`` returns None and the caller takes the
same-effort ``sonnet`` rung. ``waits`` also covers an ``unavailable`` ``upstream-down``
(``local_route_check`` reports it; the dispatcher's pre-spawn probe passes it). ``entry_line``
is the one ``outage:`` line the ``[tier]`` entry and the telemetry record carry (the probe
result rides the verdict as ``probe`` = ``<state>/<reason>``). Stdlib only; pure.
"""
from __future__ import annotations

import ladder_busy

OUTAGE = "backend-outage"
UPSTREAM_DOWN = "upstream-down"  # local_route_check's reason for a router up, backend down
_CLOCK = "runaway: wall-clock"


def _none(n) -> bool:
    return isinstance(n, int) and not isinstance(n, bool) and n == 0


def reclass(klass: str, reason: str, evidence: dict | None) -> str:
    """``OUTAGE`` for a wall-clock ``runaway`` whose ``served`` evidence shows zero local and
    zero fallback requests; else ``klass`` unchanged. The caller guards the ``local`` family."""
    served = (evidence or {}).get("served")
    if (klass == "runaway" and str(reason).startswith(_CLOCK) and isinstance(served, dict)
            and _none(served.get("local_requests")) and _none(served.get("fallback_requests"))):
        return OUTAGE
    return klass


def waits(policy: str, rung: str, reason: str) -> bool:
    """True when an ``unavailable`` verdict is an ``upstream-down`` on a local rung under the
    wait policy (it waits like a busy rung)."""
    return (policy == "wait" and rung.rsplit("-", 1)[0] == "local"
            and str(reason).startswith(UPSTREAM_DOWN))


def step(rec: dict, rung: str, busy_policy: str, waited_since: float | None, now: float | None):
    """→ ``("wait", rung, rec)`` or ``("halt", None, rec)`` under ``wait`` (the busy ceiling);
    None under ``fallback``: the caller escalates to the same-effort ``sonnet`` rung."""
    if busy_policy != "wait":
        return None
    return ladder_busy.step(rec, rung, waited_since, now)


def entry_line(verdicts) -> str | None:
    """The ``outage: backend-outage probe=<state>/<reason>`` line for the latest outage
    verdict of ``verdicts`` (``probe=none`` when no probe was passed); None when there is none."""
    hit = next((v for v in reversed(verdicts or []) if v.get("class") == OUTAGE), None)
    return None if hit is None else f"outage: {OUTAGE} probe={hit.get('probe') or 'none'}"
