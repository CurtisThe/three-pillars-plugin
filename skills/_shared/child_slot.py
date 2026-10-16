#!/usr/bin/env python3
"""child_slot.py — the router slot of a spawned child session: its busy policy.

design: strata-session-isolation (task 2.4)

``local_lease._note_policy`` records the run's busy policy for the router keyed by
``$CLAUDE_CODE_SESSION_ID`` — the id every request of THIS conversation carries. A child
session spawned by ``child_spawn`` is a different conversation: its requests carry the
child's own session id, so the run's note does not cover it. Under ``wait`` that gap is
silent and expensive — the router admits a request it cannot serve to nobody, and with no
``wait`` entry for the child's key it falls back upstream to Sonnet, which is exactly what
``wait`` exists to forbid. So the spawn site notes the policy for the child key before it
launches, into the same ``busy-policy.json`` beside the router's slot state
(``router_busy_policy``), and the router's own ``bin/busy_policy.py`` reads it on a refused
local request.

The policy is the run's effective one — the same resolution ``strata_spawn`` uses
(``override``, else ``TP_LOCAL_MODE``, else ``strata_spawn.busy`` in the repo config, else
``fallback``), not a guess from the env alone.

``can_release_session`` is the capability check the probe and the release path need: the
router's ``slot_owner`` module predates ``SlotOwner.release_session`` on some installs, and
releasing a child session's hold is impossible there. The probe answers
``router lacks release_session`` before spending a smoke spawn on a child that can never be
released cleanly.

``release`` ends the child's claim on the router when its turn is over: the finished inner
agent's hold via the already-shipped ``local_lease.release_agent`` (reused unchanged), then
the router's ``SlotOwner.release_session(endpoint, child)`` once per key in the slot state
file. A child killed mid-request leaves an ``in_flight`` entry the release cannot get past,
so a not-owner answer runs one side-traffic probe — ``SlotOwner.acquire(ep, child,
subagent=False)``, which is the router's own reaper of dead in-flight entries — and retries
the release once. That is the whole retry budget: one probe per key, one second attempt.

All three answer with a value, never an exception: a missing router, an unreadable config or
a lost state-file lock is ``False`` / an outcome from the closed set, and under ``wait`` a
note that did not land is one stderr warning line (the failure is only visible later, as a
Sonnet answer to a request that should have waited). Stdlib only.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time

import local_lease
import router_busy_policy


def parent_policy(env, module=None, *, clock=time.time) -> str | None:
    """The policy already recorded for THIS session's key, or ``None`` when there is none.

    The lease wrote it for ``$CLAUDE_CODE_SESSION_ID`` before this spawn; the child is a
    different conversation and its own env may say something else (the launcher's scrub,
    another folder's ``strata_spawn.busy``), so the parent's record — not a re-derivation —
    is what the run decided. ``None`` (never an exception) with no router module, no entry
    for this session, an unreadable file, a value outside ``POLICIES``, or an entry past
    ``TTL_S`` — the age the router itself stops honouring.
    """
    try:
        module = module or local_lease.slot_owner_module()
        if module is None:
            return None
        entry = router_busy_policy._load(
            router_busy_policy.path_for(module.SlotOwner().state_path)).get(
                env.get("CLAUDE_CODE_SESSION_ID"))
        if not isinstance(entry, dict) or entry.get("policy") not in router_busy_policy.POLICIES:
            return None
        at = entry.get("at")
        if not isinstance(at, (int, float)) or clock() - at >= router_busy_policy.TTL_S:
            return None
        return entry["policy"]
    except Exception:  # noqa: BLE001 — a parent record that cannot be read is no record
        return None


def resolved_policy(override=None, env=os.environ, module=None) -> str:
    """The policy a child spawn should carry: ``override``, else the parent's record, else env/config.

    The one resolution ``note_policy`` writes and ``cmd_start`` puts in the child's env, so the
    child never re-derives it from env of its own. Never raises: an unloadable ``strata_spawn``
    degrades to ``router_busy_policy.policy_from_env``.
    """
    try:
        if override:
            return override
        parent = parent_policy(env, module)
        if parent:
            return parent
        import strata_spawn  # lazy: strata_spawn imports local_lease
        return strata_spawn.busy_policy(strata_spawn._raw_config(None), None, env)
    except Exception:  # noqa: BLE001 — the resolution never blocks a spawn
        return router_busy_policy.policy_from_env(env)


def note_policy(child, override=None, env=os.environ, module=None) -> bool:
    """Record the run's effective busy policy for ``child``'s session key.

    -> ``True`` when the entry landed. ``False`` (and, under ``wait``, one stderr line)
    when there is no router module, the child key is empty, or the state write failed.
    Never raises: a lost note must not stop a spawn — it degrades to the router's
    fallback, which under ``wait`` is the thing worth warning about.
    """
    try:
        policy = resolved_policy(override, env, module)
        module = module or local_lease.slot_owner_module()
        written = bool(module is not None and router_busy_policy.record(
            module.SlotOwner().state_path, child, policy))
        if not written and policy == "wait":
            print("child_slot: warning: busy policy wait not recorded for the child "
                  "session; a refused request may go to Sonnet", file=sys.stderr)
        return written
    except Exception:  # noqa: BLE001 — the note never blocks a spawn
        return False


def can_release_session(which=shutil.which, module=None) -> bool:
    """``True`` when the router install exposes ``SlotOwner.release_session``.

    ``False`` with no router on ``PATH``, with a module that predates the method, or on any
    failure loading it. Never raises.
    """
    try:
        module = module or local_lease.slot_owner_module(which)
        return callable(getattr(getattr(module, "SlotOwner", None), "release_session", None))
    except Exception:  # noqa: BLE001 — an unloadable router is simply "cannot release"
        return False


def release(inner_id, child, module=None) -> dict:
    """End a child session's claim on the router: ``{"agent": …, "session": …}``. Never raises.

    ``agent`` is ``local_lease.release_agent(inner_id)``'s own outcome, passed through — the
    finished inner agent's sticky hold, reused unchanged. ``session`` is the child key's
    outcome from ``_release_session``. The agent release runs first (it is the one that works
    on today's router installs) and on every session outcome, including ``unsupported``.
    """
    agent = local_lease.release_agent(inner_id, module=module)
    return {"agent": agent["outcome"], "session": _release_session(child, module)}


def _release_session(child, module) -> str:
    """``released`` | ``not-owner`` | ``unsupported`` | ``error: <msg>`` for the child key.

    One ``SlotOwner.release_session(ep, child)`` per key in the router's slot state file
    (never short-circuited — the child can hold more than one endpoint). If none of them
    released it, one side-traffic ``acquire(ep, child, subagent=False)`` per key lets the
    router reap a dead child's in-flight entry, then exactly one retry; still nothing is
    ``not-owner`` (a key another session owns is left alone, and a missing state file means
    there was nothing to release). No router module, or one predating the method, is
    ``unsupported`` — the same answer ``can_release_session`` refuses to spend a smoke on.
    """
    try:
        module = module or local_lease.slot_owner_module()
        if module is None or not hasattr(module.SlotOwner, "release_session"):
            return "unsupported"
        owner = module.SlotOwner()
        keys = local_lease._slot_keys(owner) or []
        # One call per key — never short-circuited: the list forces every release to run.
        if any([owner.release_session(ep, child) for ep in keys]):
            return "released"
        for ep in keys:
            owner.acquire(ep, child, subagent=False)
        return "released" if any([owner.release_session(ep, child) for ep in keys]) else "not-owner"
    except Exception as exc:  # noqa: BLE001 — a release failure never breaks the caller's exit
        return f"error: {exc}"
