#!/usr/bin/env python3
"""cheap_route.py — the route + lease probe `cheap_tier_cli spec --probe` runs for a cheap slot.

design: cheap-tier-local-routing (detailed-design.md §Interfaces `cheap_route.probe`, §Notes 4)

`probe` says whether a slot's configured `local-*` rung may keep the local GPU slot and, when
it may not, why: the `fallback` reason a dispatch row records (`served_rung.FALLBACKS`). Each
step runs only when the one before let the rung stay local:

1. the rung is `local-*` (any other rung is no local request: nothing probed, no fallback);
2. the slot is in `ROUTED_SLOTS`, else `route_label "unrouted/slot"`, fallback `unrouted-slot`;
3. the route label is `routed/ok`: `route` > `route_text` (`tier_ladder.route_label`) > one
   live `local_route_check.check(env)`; else `unrouted` (no `ANTHROPIC_BASE_URL`, the consumer
   case) or `unreachable` (any other label);
4. no orphan holds the GPU: `attempt_watchdog.orphans(dir, phase=None)` (a cheap probe has no
   task phase) over `<root>/.tp-scratch/cheap-watch/` and the task ladder
   `<git-common-dir>/tp-ladder/<slug>` (every `tp-ladder/*` dir when `design` is None);
5. the lease, `local_lease.acquire_timed(design=...)`: its `MAX_WAIT_S` is the one owner wait.
   `busy` → `local-busy`, `busy-measure` → `local-busy-measure`; `unchecked` (no slot-owner
   module) passes `lease_state "free"` on, so the rung spawns and served evidence decides.

`lease_wait_s` is a float on every branch (`0.0` unless the lease was probed) and `measure`
is the window role (`off`/`owner`/`other`). Never raises: a failed scan or probe fails open.
`check`, `lease` and `orphans` are test seams. Stdlib only.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Mapping

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import children_route  # noqa: E402 — a direct run's children route
import attempt_watchdog  # noqa: E402 — orphans (the running/done rule)
import ladder_files  # noqa: E402 — the per-design ladder dir
import local_lease  # noqa: E402 — acquire_timed (the one wait budget)
import local_route_check  # noqa: E402 — the live /health check
import measure_window  # noqa: E402 — the window role
import router_stats  # noqa: E402 — the router log the orphan rule reads
import scratch_root  # noqa: E402 — the scratch parent cheap-watch lives under
import task_attempts  # noqa: E402 — common_dir
import tier_ladder  # noqa: E402 — route_label

ROUTED_SLOTS = frozenset({"history_line", "handoff", "docs_draft"})
CHEAP_WATCH = Path(scratch_root.SCRATCH_DIR) / "cheap-watch"
ROUTED_OK = "routed/ok"
LEASE_FALLBACK = {"busy": "local-busy", "busy-measure": "local-busy-measure"}


def _measure(env: Mapping[str, str], design: str | None) -> str:
    """The measurement window's role for `design`: `off` | `owner` | `other`."""
    try:
        window = measure_window.load(env)
        return measure_window.role(window, design) if window else "off"
    except Exception:  # noqa: BLE001 — an unreadable window is no window
        return "off"


def _label(env, route, route_text, check) -> str:
    """`route` > `route_text` > one live check, as a `<state>/<reason>` label."""
    try:
        if route is not None or route_text is not None:
            return tier_ladder.route_label(route, route_text, env)
        return tier_ladder.route_label(check(env), None, env)
    except Exception:  # noqa: BLE001 — a failed check reads as a down router
        return "router-down/error"


def _ladder_dirs(root, design: str | None) -> list[Path]:
    """The task ladder dir(s) to scan: the design's, or every one when `design` is None."""
    try:
        if design is not None:
            return [ladder_files.ladder_dir(root, design)]
        base = Path(task_attempts.common_dir(root)) / ladder_files.LADDER
        return sorted(p for p in base.iterdir() if p.is_dir())
    except Exception:  # noqa: BLE001 — no repo, a bad slug or no ladder: nothing to scan
        return []


def _orphan_held(root, design, env, orphans) -> str | None:
    """Why an orphan still holds the GPU (the first dir with one), else None."""
    try:
        log = router_stats.log_path(env)
    except Exception:  # noqa: BLE001 — the orphan rule falls back to its own default
        log = None
    for scan_dir in [Path(root) / CHEAP_WATCH, *_ladder_dirs(root, design)]:
        try:
            found = orphans(scan_dir, phase=None, router_log=log)
        except Exception:  # noqa: BLE001 — a failed scan never blocks the route
            continue
        if isinstance(found, dict) and found.get("holds_gpu"):
            return f"orphan holds the gpu ({scan_dir})"
    return None


def _lease(lease, design, env) -> tuple[str, str, float]:
    """`(state, why, waited_s)` from the lease; any failure is `unchecked`, 0 s."""
    try:
        state, why, waited = lease(design=design, env=env)
        return str(state), str(why), float(waited or 0.0)
    except Exception as exc:  # noqa: BLE001 — a lease failure never blocks a spawn
        return "unchecked", f"lease probe failed: {exc}", 0.0


def _out(label, lease_state, lease_why, waited, measure, fallback) -> dict:
    return {"route_label": label, "lease_state": lease_state, "lease_why": lease_why,
            "lease_wait_s": float(waited), "measure": measure, "fallback": fallback}


def probe(slot: str, rung: str, root, *, design: str | None,
          env: Mapping[str, str] | None = None, route=None, route_text: str | None = None,
          check=None, lease=None, orphans=None) -> dict:
    """`{route_label, lease_state, lease_why, lease_wait_s, measure, fallback}` for `slot`
    on `rung` (see the module docstring). `lease_state` is what `cheap_tier.resolve` takes:
    `free` exactly when the rung stays local. Never raises."""
    env = os.environ if env is None else env
    measure = _measure(env, design)
    if not str(rung or "").startswith("local-"):
        return _out("unrouted/rung", "unchecked", "not probed: not a local rung", 0.0,
                    measure, None)
    if slot not in ROUTED_SLOTS:
        return _out("unrouted/slot", "unchecked", "not probed: slot not routed", 0.0,
                    measure, "unrouted-slot")
    label = _label(env, route, route_text, check or local_route_check.check)
    if label != ROUTED_OK:
        routed = (children_route.effective_env(env, root).get("ANTHROPIC_BASE_URL") or "").strip()
        return _out(label, "unchecked", f"not probed: route {label}", 0.0, measure,
                    "unreachable" if routed else "unrouted")
    held = _orphan_held(root, design, env, orphans or attempt_watchdog.orphans)
    if held:
        return _out(label, "busy", held, 0.0, measure, "orphan-holds-gpu")
    state, why, waited = _lease(lease or local_lease.acquire_timed, design, env)
    if state in ("free", "unchecked"):
        return _out(label, "free", why if state == "free" else "unchecked", waited, measure,
                    None)
    return _out(label, state, why, waited, measure, LEASE_FALLBACK.get(state, "unrecorded"))
