#!/usr/bin/env python3
"""strata_spawn.py — the busy policy and slot wait for Strata-routed spawns.

design: local-role-routing (Task 2.1), one-cheap-engine (Task 2.3).
`busy_policy` resolves how a busy local slot is handled: override, else
`TP_LOCAL_MODE` (via `cheap_engine.local_mode`), else the `strata_spawn.busy`
config key, else `fallback`. `fallback` waits `BUSY_GRACE_S` (3 s) for a busy slot, then
lets the spawn go ahead (the router serves it on Sonnet); `wait` polls the slot, halting at an overall
ceiling. `wait` wraps one `local_lease.acquire_timed` call and returns
`(state, why, waited)`. Before the lease it probes this session's route: an
`unrouted` route is its own state (exit 6, `decide` -> `sonnet`, the M51
degrade), a `router-down` route is `unhealthy` (exit 4, the halt); a probe that
cannot answer is fail-open and says so in `why`. `decide` never names Opus. The default probe is `local_route_check.check()` and runs only for the
real lease — an injected lease is the test seam, so no test reaches a live
router. Under `wait` each poll writes one stderr line (strata-fair-queue
Behavior 9): `queued, position <p> of <n>, waited <XmYs>` from the router's
queue, else the old `busy (<why>)`; a grant ends with the total wait since
`started_at`. stdout stays the one JSON object. Stdlib-only.
"""
from __future__ import annotations

import argparse
import inspect
import json
import os
import re
import sys
import time
from pathlib import Path

_SHARED_DIR = Path(__file__).resolve().parent
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

import cheap_engine  # noqa: E402
import lease_queue  # noqa: E402
import local_lease  # noqa: E402
import local_route_check  # noqa: E402
import model_policy  # noqa: E402
import router_stats  # noqa: E402
import wait_budget  # noqa: E402

SLOT_LOSS_SUFFIX = ("Keep every command under 120 s (wrap in timeout 100); run targeted tests only; "
                    "never kill by name or pattern.")
BUSY_POLICIES = ("fallback", "wait")
DEFAULT_BUSY = "fallback"
CEILING_S = 4 * 3600
BUSY_GRACE_S = 3  # the fallback policy's wait for a busy slot before Sonnet
RESPAWN_MAX = 2
SERVED_STATES = ("strata", "fallback-busy", "fallback", "unhealthy", "unrouted")
POLL_S = local_lease.POLL_S
BUSY_RE = re.compile(r"->\s+FALLBACK upstream \((?:slot held by|agent-busy) (\S+)\)")


def busy_policy(config, override=None, env=None) -> str:
    """`override`, else a set `TP_LOCAL_MODE`, else the raw config's
    `strata_spawn.busy`, else `fallback`."""
    if override is not None:
        return override
    env = os.environ if env is None else env
    if env.get("TP_LOCAL_MODE"):
        policy, notes = cheap_engine.local_mode(env)
        for note in notes:
            print(f"strata_spawn: {note}", file=sys.stderr)
        return policy
    block = config.get("strata_spawn") if isinstance(config, dict) else None
    value = block.get("busy") if isinstance(block, dict) else None
    if value is None:
        return DEFAULT_BUSY
    if value not in BUSY_POLICIES:
        print(f"strata_spawn: unknown busy policy {value!r}; using {DEFAULT_BUSY}",
              file=sys.stderr)
        return DEFAULT_BUSY
    return value


_REAL_LEASE = local_lease  # the real lease, captured before any test patches the global
_ROUTE_CHECK = None  # the CLI's route-check seam: main passes it as `route_check=`

ROUTE_FAIL_NOTE = "route check"


def _default_route_check() -> dict:
    """The default route probe: `local_route_check.check()` at call time
    (read-only: one `GET /health`, no lease write, no config write)."""
    return local_route_check.check()


def _route_probe(route_check, lease):
    """The check `wait` runs, or `None` for no probe. An explicit `route_check`
    always wins; the default probe runs only for the real lease module, so an
    injected (fake) lease is the test seam and never reaches a live router."""
    if route_check is not None:
        return route_check
    return _default_route_check if lease is _REAL_LEASE else None


def _route_verdict(probe) -> tuple[str, str]:
    """`("", "")` to go on with the lease, `("unrouted", why)` to degrade to
    Sonnet, or `("unhealthy", why)` to halt (router-down).
    Fail-open: a probe that raises or answers with no usable `state` notes it
    and lets the spawn proceed — a broken probe is never a halt."""
    try:
        result = probe()
    except Exception as exc:  # noqa: BLE001 — a probe failure never blocks a spawn
        return "", f"{ROUTE_FAIL_NOTE} failed: {exc}"
    state = result.get("state") if isinstance(result, dict) else None
    if state == "routed":
        return "", ""
    if state in local_route_check.STATES:
        reason = result.get("reason") or state
        verdict = "unrouted" if state == "unrouted" else "unhealthy"
        return verdict, f"{ROUTE_FAIL_NOTE} {state} ({reason})"
    return "", f"{ROUTE_FAIL_NOTE} returned no usable state " \
               f"(got {type(result).__name__})"


def _takes_on_poll(lease) -> bool:
    """`lease.acquire_timed` accepts `on_poll` (a lease from before the fair queue does not)."""
    try:
        params = inspect.signature(lease.acquire_timed).parameters
    except (AttributeError, TypeError, ValueError):
        return False
    return "on_poll" in params or any(
        p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())


def _print_poll(state, why, info) -> None:
    """One stderr line per busy poll: the queue position and the router's wait, else the
    old busy text (an older router reports no queue)."""
    if state != "busy":
        return
    try:
        line = (f"queued, position {info['position']} of {info['total']}, "
                f"waited {lease_queue.fmt_wait(info['waited_s'])}")
    except (KeyError, TypeError):
        line = f"busy ({why})"
    print(f"strata_spawn: {line}", file=sys.stderr)


def wait(design=None, budget_s=wait_budget.WAIT_BUDGET_S, started_at=None, ceiling_s=CEILING_S,
         policy=DEFAULT_BUSY, *, lease=local_lease, clock=time.time, sleep=time.sleep,
         route_check=None):
    """`(state, why, waited)`: free | busy-fallback | still-busy | unhealthy |
    unrouted | unchecked | wait-exhausted. A route that is not `routed` is
    `unrouted` or `unhealthy` before the lease is touched, under either policy; a route probe that cannot answer is fail-open and names itself in
    `why`."""
    probe = _route_probe(route_check, lease)
    note = ""
    if probe is not None:
        state, why = _route_verdict(probe)
        if state:
            return state, why, 0.0
        note = why
    waiting = policy == "wait"
    if waiting and started_at is not None and clock() - started_at >= ceiling_s:
        return "wait-exhausted", f"waited past the {ceiling_s} s ceiling", 0.0
    since = started_at if started_at is not None else clock()
    progress = {"on_poll": _print_poll} if waiting and _takes_on_poll(lease) else {}
    state, why, waited = lease.acquire_timed(
        design=design, wait_s=budget_s if waiting else BUSY_GRACE_S, busy_policy=policy,
        **progress)
    if waiting and state == "free":
        print(f"strata_spawn: granted, waited {lease_queue.fmt_wait(clock() - since)}",
              file=sys.stderr)
    if note:
        why = f"{why}; {note}"
    if state == "busy-measure":
        sleep(POLL_S)  # another design's window: never spin, never spawn into it
        return "still-busy", why, waited
    if state == "busy":
        return ("still-busy" if waiting else "busy-fallback"), why, waited
    if state in ("free", "unhealthy", "unchecked"):
        return state, why, waited
    return "unchecked", why, waited


def mark(env=None) -> int:
    """The router-log byte offset now (0 when there is no log)."""
    try:
        return router_stats.log_path(os.environ if env is None else env).stat().st_size
    except OSError:
        return 0


def verify(agent_id, since, env=None) -> dict:
    """Who served `agent_id`'s requests since `since`: strata | fallback-busy | fallback."""
    path = router_stats.log_path(os.environ if env is None else env)
    events, _ = router_stats.read_since(path, since)
    reqs = [e for e in router_stats.for_agent(events, agent_id) if e.get("kind") == "request"]
    local = sum(1 for e in reqs if e.get("route") == "local")
    fallbacks = sum(1 for e in reqs if e.get("route") == "FALLBACK")
    reasons, busy = [], 0
    prefix = (agent_id or "")[:8]
    try:
        with open(path, "rb") as fh:
            fh.seek(since if since <= path.stat().st_size else 0)
            lines = fh.read().decode("utf-8", errors="replace").splitlines()
    except OSError:
        lines = []
    for line in lines:
        if not re.search(rf"\sagent={re.escape(prefix)}\s", line):
            continue
        m = BUSY_RE.search(line)
        if m:
            busy += 1
            reasons.append(m.group(1))
    if fallbacks == 0 and router_stats.served_by("local", local) == "local":
        served = "strata"
    elif fallbacks > 0 and busy == fallbacks:
        served = "fallback-busy"
    else:
        served = "fallback"
    return {"served": served, "local_requests": local, "fallback_requests": fallbacks,
            "fallback_reasons": list(dict.fromkeys(reasons))}


def decide(attempt, served, role, policy=DEFAULT_BUSY) -> str:
    """accept | respawn | sonnet | proceed-empty | halt. Total over known inputs;
    never names Opus. attempt >= RESPAWN_MAX counts as exhausted."""
    if role not in model_policy.ENGINE_ROLES:
        raise ValueError(f"unknown role {role!r}")
    if policy not in BUSY_POLICIES:
        raise ValueError(f"unknown policy {policy!r}")
    if served not in SERVED_STATES:
        raise ValueError(f"unknown served state {served!r}")
    if served == "strata":
        return "accept"
    if served == "unhealthy":
        return "halt"
    if served == "unrouted":
        return "sonnet"
    if served == "fallback-busy" and policy == "fallback":
        return "accept"
    if attempt < RESPAWN_MAX:
        return "respawn"
    return "proceed-empty" if role == "context_scout" else "sonnet"


def release(agent_id, *, release_agent=None):
    """Free the slot held by `agent_id` (delegates to `local_lease.release_agent`)."""
    return (release_agent or local_lease.release_agent)(agent_id)


def _raw_config(path) -> dict:
    """Raw JSON config at `path` (default `<cwd>/.three-pillars/config.json`); bad -> {}."""
    target = Path(path) if path else Path(".three-pillars") / "config.json"
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="strata_spawn")
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("wait")
    w.add_argument("--design")
    w.add_argument("--budget-s", type=float, default=wait_budget.WAIT_BUDGET_S)
    w.add_argument("--started-at", type=float)
    w.add_argument("--ceiling-s", type=float, default=CEILING_S)
    d = sub.add_parser("decide")
    d.add_argument("attempt", type=int)
    d.add_argument("served")
    d.add_argument("role")
    for p in (w, d):
        p.add_argument("--busy", choices=BUSY_POLICIES)
        p.add_argument("--config")
    sub.add_parser("mark")
    v = sub.add_parser("verify")
    v.add_argument("agent_id")
    v.add_argument("since", type=int)
    r = sub.add_parser("release")
    r.add_argument("agent_id")
    return ap


_WAIT_EXIT = {"still-busy": 3, "unhealthy": 4, "wait-exhausted": 5, "unrouted": 6}


def main(argv=None) -> int:
    a = _parser().parse_args(argv)
    if a.cmd == "wait":
        policy = busy_policy(_raw_config(a.config), a.busy)
        started = a.started_at if a.started_at is not None else time.time()
        state, why, waited = wait(a.design, a.budget_s, started, a.ceiling_s, policy,
                                  lease=local_lease, clock=time.time, sleep=time.sleep,
                                  route_check=_ROUTE_CHECK)
        print(json.dumps({"state": state, "why": why, "waited": waited,
                          "started_at": started}))
        return _WAIT_EXIT.get(state, 0)
    if a.cmd == "mark":
        print(json.dumps(mark()))
        return 0
    if a.cmd == "verify":
        out = verify(a.agent_id, a.since)
        print(json.dumps(out))
        return 0 if out["served"] == "strata" else 3
    if a.cmd == "decide":
        policy = busy_policy(_raw_config(a.config), a.busy)
        try:
            action = decide(a.attempt, a.served, a.role, policy)
        except ValueError as exc:
            print(exc, file=sys.stderr)
            return 2
        print(action)
        return 4 if action == "halt" else 0
    out = release(a.agent_id, release_agent=local_lease.release_agent)
    payload = {"agent_id": a.agent_id, **(out if isinstance(out, dict) else {"outcome": out})}
    print(json.dumps(payload))
    return 0


if __name__ == "__main__":
    sys.exit(main())
