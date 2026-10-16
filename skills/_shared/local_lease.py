"""local_lease.py — the lease hook around every local-model task spawn: the slot check.

design: local-implement-and-review; run-throughput (Q1); cheap-tier-local-routing (B4)

``local-dispatch.md`` §3 runs ``acquire`` right before a local rung spawns. The router
(local-llm-skills) grants its one local GPU slot to one conversation at a time and sends
everyone else upstream as its fallback model (Sonnet): a local rung spawned while another
session owns the slot would run as a disguised Sonnet call. ``acquire`` asks the ROUTER'S
OWN slot owner — ``bin/slot_owner.py`` beside the ``tp-local`` binary on ``PATH`` — through
its public side-traffic probe ``SlotOwner.acquire(endpoint, key, subagent=False)``, which
never takes, renews or counts as in flight. The ownership rule stays that module's; this
file only compares the owner it names with this session (``$CLAUDE_CODE_SESSION_ID``, the
key a nested spawn shares). One line on stdout:

- exit 0 ``lease: free (<why>)`` — unowned, idle past its window, or held by this session;
- exit 3 ``lease: busy (slot held by <id8>)`` — another conversation owns it: no spawn, the
  rung's outcome is ``unavailable`` with reason ``local-busy`` (the ladder goes straight to
  the sonnet family; no attempt is spent);
- exit 3 ``lease: busy (slot held by agent <id8>)`` — this session owns the slot but one of its
  subagents still holds it (a request in flight, or ``owner_agent`` unreleased with ``agent_seen``
  inside ``IDLE_S``): the honest answer, since the spawn would come back ``agent-busy`` upstream
  (slot-release-on-attempt-end Behavior 6; a released, idle-expired or ``main`` hold with nothing
  in flight stays ``free``);
- exit 0 ``lease: unchecked (<why>)`` — no router install, no slot state, or the probe
  failed: the spawn goes ahead and the attempt's router stats decide who served it
  (``router_stats.served_by``: zero local requests is ``local-fallback-served``);
- exit 3 ``lease: busy-measure (measurement window held by <D>)`` — a live
  ``measure_window`` belongs to another design (or the caller names none): answered before
  the router is probed, so a measured window never yields its slot.

``--design D``: the window's owner waits for a busy slot (a probe every ``POLL_S``, at most
``MAX_WAIT_S``, inside the 300 s cache TTL); ``--wait-s S`` sets the wait (clamped).
Either flag appends `` waited=<s>``. ``release`` has two forms: bare, it gives nothing back (the
probe takes nothing) — ``lease: released``; with ``--agent-id X`` it drops that finished agent's
hold through ``release_agent`` — ``lease: released (<outcome>)``, exit 0 whatever the outcome.
``gpu-fair-share-parallel-phases`` would replace these bodies.
``--endpoint E`` limits the probe to that slot key (default: every endpoint). Every ``acquire``
first records the session's busy policy for the router (``router_busy_policy``; ``--busy-policy``,
else ``TP_LOCAL_MODE``), so under ``wait`` a request the router can't admit is held, never
rewritten to Sonnet. A probe that loses the router's lock budget reads its lock-free ``peek``
instead of answering ``unchecked``. Stdlib only.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Mapping

import children_route
import measure_window
import router_busy_policy
import wait_budget

BUSY_EXIT = 3
BUSY_REASON = "local-busy"
BUSY_STATES = ("busy", "busy-measure")
MAX_WAIT_S = wait_budget.WAIT_BUDGET_S  # inside the 300 s cache TTL
POLL_S = 15
IDLE_S = 120.0  # the router's own default, only a last resort if it names no window


def resolve_endpoint(endpoint: str | None, env: Mapping[str, str] | None = None) -> str:
    """The explicit endpoint, else ``$ANTHROPIC_BASE_URL``, else ``default``."""
    if endpoint:
        return endpoint
    source = children_route.effective_env(os.environ if env is None else env, os.getcwd())
    return source.get("ANTHROPIC_BASE_URL") or "default"


def slot_owner_module(which=shutil.which):
    """The router's own ``slot_owner`` module (beside the resolved ``tp-local``), or None."""
    binary = which("tp-local")
    path = Path(os.path.realpath(binary)).parent / "slot_owner.py" if binary else None
    if path is None or not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("tp_local_slot_owner", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _slot_state(owner) -> dict | None:
    """The slot state file's mapping (endpoint -> slot), or ``None`` with no state file."""
    try:
        with open(owner.state_path, encoding="utf-8") as fh:
            return json.load(fh) or {}
    except FileNotFoundError:
        return None


def _slot_keys(owner) -> list[str] | None:
    """The slot state file's keys (its endpoints), or ``None`` when there is no state file."""
    state = _slot_state(owner)
    return None if state is None else list(state)


def _same_agent(a, b) -> bool:
    """The router's own id rule (``_same_agent``): equal, or one is a prefix (>= 8 chars) of
    the other — a hold may be recorded under the full agent id or the id8 the router logs."""
    if not isinstance(a, str) or not isinstance(b, str) or not a or not b:
        return False
    if a == b:
        return True
    short, long_ = sorted((a, b), key=len)
    return len(short) >= 8 and long_.startswith(short)


def _idle_window(module, owner) -> float:
    """The router's idle window: its ``IDLE_S``, else the owner instance's, else its default."""
    for value in (getattr(module, "IDLE_S", None), getattr(owner, "idle_s", None)):
        try:
            if value is not None and float(value) > 0:
                return float(value)
        except (TypeError, ValueError):
            pass
    return IDLE_S


def _in_flight_agent(slot) -> str | None:
    """A non-``main`` agent with a request in flight (entry ``<pid>:<n>:<agent>``), or ``None``.

    The first rule of the router's ``SlotOwner._agent_busy``: any other agent in flight makes the
    next spawn ``agent-busy``, whatever ``owner_agent`` / ``released`` / ``agent_seen`` say (a
    stopped runaway whose stream is still open; a first request, ``agent_seen`` stamped only on
    close). ``main`` is the dispatcher itself, never a hold on its own spawn.
    """
    flight = slot.get("in_flight")
    if not isinstance(flight, dict):
        return None
    agents = {e.split(":", 2)[2] for e in flight if isinstance(e, str) and e.count(":") >= 2}
    agents -= {"", "-", "main"}
    return sorted(agents)[0] if agents else None


def _agent_holder(slot, module, owner) -> str | None:
    """The subagent still holding a slot THIS session owns, or ``None`` (Behavior 6).

    The router's own rule (``SlotOwner._agent_busy``): an agent in flight holds it first; then
    ``owner_agent`` is the sticky holder, ``main`` is never held off, a ``released`` entry is
    served but never sticky again, and a hold ends past ``IDLE_S``. Never raises: an unreadable
    or unexpected slot answers ``None``, keeping the session-level answer (Behavior 7) — the
    agent read can only ever make a spawn wait, never break one.
    """
    try:
        flying = _in_flight_agent(slot)
        if flying:
            return flying
        holder = slot.get("owner_agent")
        if not isinstance(holder, str) or holder == "main":
            return None
        released = slot.get("released")
        if isinstance(released, dict) and any(_same_agent(holder, a) for a in released):
            return None
        seen = slot.get("agent_seen")
        if not isinstance(seen, (int, float)) or time.time() - seen >= _idle_window(module, owner):
            return None
        return holder
    except Exception:  # noqa: BLE001 — no agent read is better than a wrong busy
        return None


def _fresh_slot(owner, ep, slots) -> dict:
    """``ep``'s slot as the router left it after the probe (its ``acquire`` reaps dead and
    ``STALE_S``-old in-flight entries and saves), else the pre-probe read. Never raises."""
    try:
        fresh = (_slot_state(owner) or {}).get(ep)
        if isinstance(fresh, dict):
            return fresh
    except Exception:  # noqa: BLE001 — a failed re-read keeps the pre-probe slot
        pass
    return slots.get(ep) or {}


def _peek_on_contention(owner, ep, why) -> str:
    """``why`` unchanged, unless the probe lost the router's 50 ms lock budget ("slot state
    busy" — a router serving another run back to back holds the flock almost continuously):
    then the router's lock-free ``peek`` answers instead, in the probe's words. That answer used
    to be ``unchecked``, which spawns — straight into a slot another session held
    (wait-mode-router-leak). Never raises; an owner without ``peek`` keeps ``why``."""
    if why != "slot state busy" or not callable(getattr(owner, "peek", None)):
        return why
    try:
        free, holder = owner.peek(ep)
    except Exception:  # noqa: BLE001 — keep the original answer
        return why
    return "unowned" if free else f"slot held by {holder}"


def _note_policy(env, module, which, busy_policy) -> None:
    """Record this session's busy policy for the router (``router_busy_policy``), so a request
    the router can't admit waits instead of going to Sonnet under ``wait``. Never raises."""
    policy = busy_policy
    try:
        if policy is None:  # TP_LOCAL_MODE, else the repo's strata_spawn.busy (lazy: it imports us)
            import strata_spawn
            policy = strata_spawn.busy_policy(strata_spawn._raw_config(None), None, env)
        module = module or slot_owner_module(which)
        if module is not None and not router_busy_policy.record(
                module.SlotOwner().state_path, env.get("CLAUDE_CODE_SESSION_ID"), policy) \
                and policy == "wait":
            print("lease: warning: busy policy wait not recorded for the router "
                  "(no session id or state write failed); a refused request may go to Sonnet",
                  file=sys.stderr)
    except Exception:  # noqa: BLE001 — the note never blocks a spawn
        pass


def _probe(endpoint, env, module, which) -> tuple[str, str]:
    """One router probe: ``(state, why)``, ``free`` | ``busy`` | ``unchecked``. Never raises.

    The session probe answers per conversation; a live agent hold of this session's is read
    from the state file alongside it (Behavior 6) — ``slot held by agent <id8>``, the same
    answer the next spawn would have got from the router itself.
    """
    try:
        module = module or slot_owner_module(which)
        if module is None:
            return "unchecked", "no local router install (tp-local / slot_owner.py)"
        owner = module.SlotOwner()
        slots = _slot_state(owner)
        if slots is None:
            return "free", "no slot state"
        mine, ours = (env.get("CLAUDE_CODE_SESSION_ID") or "")[:8], False
        for ep in [endpoint] if endpoint else slots:
            _token, why = owner.acquire(ep, "tp-lease-probe", subagent=False)
            why = _peek_on_contention(owner, ep, why)
            held = why.startswith("slot held by ")
            if held and (not mine or why.removeprefix("slot held by ") != mine):
                return "busy", why
            if not held and why != "unowned":
                return "unchecked", why
            ours = ours or held
            if held:  # this session owns it — is one of its agents still holding?
                holder = _agent_holder(_fresh_slot(owner, ep, slots), module, owner)
                if holder:
                    return "busy", f"slot held by agent {holder[:8]}"
        return "free", "held by this session" if ours else "unowned"
    except Exception as exc:  # noqa: BLE001 — a probe failure never blocks a spawn
        return "unchecked", f"slot probe failed: {exc}"


def acquire_timed(endpoint: str | None = None, *, env: Mapping[str, str] | None = None,
                  module=None, which=shutil.which, design: str | None = None,
                  wait_s: float | None = None, clock=time.monotonic,
                  sleep=time.sleep, busy_policy: str | None = None) -> tuple[str, str, float]:
    """``(state, why, waited_s)``: a live window not ``design``'s is ``busy-measure``, unprobed;
    ``wait_s=None`` is ``MAX_WAIT_S`` for its owner, else 0; clamped to it. First records the
    session's ``busy_policy`` (else ``TP_LOCAL_MODE``'s) for the router. Never raises."""
    env = os.environ if env is None else env
    _note_policy(env, module, which, busy_policy)
    try:
        window = measure_window.load(env)
        role = measure_window.role(window, design) if window else "off"
        if role == "other":
            return "busy-measure", f"measurement window held by {window['design']}", 0.0
        if wait_s is None:
            wait_s = MAX_WAIT_S if role == "owner" else 0
        wait = min(max(float(wait_s), 0.0), MAX_WAIT_S)
        start = clock()
        state, why = _probe(endpoint, env, module, which)
        while state == "busy" and (left := start + wait - clock()) > 0:
            sleep(min(POLL_S, left))
            state, why = _probe(endpoint, env, module, which)
        return state, why, round(clock() - start, 1)
    except Exception as exc:  # noqa: BLE001 — a lease failure never blocks a spawn
        return "unchecked", f"slot probe failed: {exc}", 0.0


def acquire(endpoint: str | None = None, *, env: Mapping[str, str] | None = None,
            module=None, which=shutil.which, design: str | None = None,
            wait_s: float | None = None, clock=time.monotonic,
            sleep=time.sleep) -> tuple[str, str]:
    """``(state, why)``: ``free`` | ``busy`` | ``busy-measure`` | ``unchecked``. Never raises."""
    return acquire_timed(endpoint, env=env, module=module, which=which, design=design,
                         wait_s=wait_s, clock=clock, sleep=sleep)[:2]


def release_agent(agent_id: str | None, *, env: Mapping[str, str] | None = None,
                  module=None, which=shutil.which) -> dict:
    """Drop a finished agent's hold on every slot key: ``{"outcome", "endpoints"}``. Never raises.

    design: slot-release-on-attempt-end (Behaviors 4, 7). The full agent id is passed unchanged —
    the router's ``_same_agent`` prefix-matches it against a hold recorded under the full id or
    its id8. ``outcome`` is the closed set of design.md: ``released`` (some endpoint released it) |
    ``not-holder`` (nothing did, or no state / no id) | ``no-router`` | ``unsupported`` (the router
    predates ``release_agent``) | ``disabled`` (``TP_SLOT_RELEASE=0``, checked before any load) |
    ``error: <msg>``. The release is a router-state write only: an agent that sends again is still
    served while the slot is free, so an early one costs only cache warmth.
    """
    env = os.environ if env is None else env
    try:
        if env.get("TP_SLOT_RELEASE") == "0":
            return {"outcome": "disabled", "endpoints": []}
        if not agent_id:
            return {"outcome": "not-holder", "endpoints": []}
        module = module or slot_owner_module(which)
        if module is None:
            return {"outcome": "no-router", "endpoints": []}
        if not hasattr(module.SlotOwner, "release_agent"):
            return {"outcome": "unsupported", "endpoints": []}
        owner = module.SlotOwner()
        endpoints = _slot_keys(owner) or []
        # One call per key — never short-circuited: the agent can hold more than one endpoint.
        released = any([owner.release_agent(ep, agent_id) for ep in endpoints])
        return {"outcome": "released" if released else "not-holder", "endpoints": endpoints}
    except Exception as exc:  # noqa: BLE001 — a release failure never breaks a caller
        return {"outcome": f"error: {exc}", "endpoints": []}


def release(endpoint: str | None = None) -> None:
    """Nothing to release: the probe never takes the slot. The id-carrying form is
    ``release_agent``."""


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="The local-rung slot check.")
    parser.add_argument("action", choices=("acquire", "release"))
    parser.add_argument("--endpoint", default=None, help="one slot key (default: all)")
    parser.add_argument("--agent-id", default=None,
                        help="a finished agent whose router hold to drop (release only)")
    parser.add_argument("--design", default=None, help="this run's design (window owner waits)")
    parser.add_argument("--busy-policy", choices=router_busy_policy.POLICIES, default=None,
                        help="the run's busy policy for the router (default: from TP_LOCAL_MODE)")
    parser.add_argument("--wait-s", type=float, default=None,
                        help=f"busy re-probe budget in seconds (clamped to {MAX_WAIT_S})")
    args = parser.parse_args(argv)
    if args.action == "release":
        if args.agent_id:
            outcome = release_agent(args.agent_id)["outcome"]
            print(f"lease: released ({outcome})")
        else:
            release(args.endpoint)
            print("lease: released")
        return 0
    state, why, waited = acquire_timed(args.endpoint, design=args.design, wait_s=args.wait_s,
                                       busy_policy=args.busy_policy)
    timed = args.design is not None or args.wait_s is not None
    print(f"lease: {state} ({why})" + (f" waited={waited:g}" if timed else ""))
    return BUSY_EXIT if state in BUSY_STATES else 0


if __name__ == "__main__":
    sys.exit(main())
