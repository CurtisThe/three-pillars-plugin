"""design_run_backend.py — which backend a design-run window starts on.

design: main-thread-direct-backend (S4); launch-role-precedence (1.5)

A design run is a main thread, so it should talk to Anthropic directly while its
spawned children stay routed to the local model. Today's launch is `route` (the
folder's routes row decides, so the window can end up hybrid). `direct` starts the
window with the Homelab launcher's `run` role — direct backend plus Remote Control
— by putting `CLAUDE_LAUNCHER_ROLE=run` in the window command's env assignments.
`--direct` asks for it for one run; the repo's `design_run_backend` key makes it
the default, and stays `"route"` until one run proves its Strata children still
reach the router (the S4 proof, recorded in the design's `decisions.md`).

This module only answers which backend. The role itself is `design_run_role`'s,
and the precedence is `design_run_launch_plan`'s: flags on this launch, then the
role (backend and Remote Control only), then routes.conf, and never the launching
session's own env — the parent's launcher names are unset, whatever it holds.

Stdlib only; no side effect, no subprocess.
"""
from __future__ import annotations

from typing import Mapping

BACKENDS = ("route", "direct")
DEFAULT_BACKEND = "route"


def resolve(cfg, direct: bool) -> str:
    """The backend for this launch: `--direct`, else the repo's
    `design_run_backend`, else `route`. A value outside `BACKENDS` never
    reaches here (the config loader prunes it with its warning); anything
    unrecognised still falls back to `route`."""
    if direct:
        return "direct"
    key = cfg.get("design_run_backend") if isinstance(cfg, Mapping) else None
    return key if key in BACKENDS else DEFAULT_BACKEND


def is_backend_drop_warning(warning: str) -> bool:
    """True for a loader warning that dropped `design_run_backend` (a value
    outside `BACKENDS` — the run then stays `route`)."""
    key = warning.removeprefix("config: dropped ").split(" ", 1)[0]
    return key == "design_run_backend"
