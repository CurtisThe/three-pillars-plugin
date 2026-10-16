#!/usr/bin/env python3
"""cheap_engine.py — the one cheap-engine resolver (design: one-cheap-engine 1.2).

`engine_for(site, run, route_state, available)` answers which engine a site
runs on: judgment sites always `opus`; cheap sites `sonnet` without `--local`,
and under `--local` `strata` when the backend is present and the route is
`routed/*`, `sonnet` plus one M51 note when it is not, `halt` when the router
is down or the route is malformed. `TP_LOCAL_MODE` picks the busy policy
(`fallback` or `wait`; `exclusive` is `wait`). Stdlib-only; no model is called.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import cheap_classes
import cheap_tier_default
import ladder_entry
import local_backend
import local_implement_config
import local_route_check
import model_policy
import repo_config_load
import tier_ladder

MODES = ("fallback", "wait", "exclusive")


def local_mode(env=None) -> tuple[str, list[str]]:
    """`(busy policy, notes)` from `TP_LOCAL_MODE`: unset/`""` -> fallback;
    `exclusive` -> wait; unknown -> fallback plus one note line."""
    env = os.environ if env is None else env
    value = env.get("TP_LOCAL_MODE") or ""
    if not value:
        return "fallback", []
    if value not in MODES:
        return "fallback", [f'warning: TP_LOCAL_MODE="{value}" is not one of '
                            f'{"/".join(MODES)}; using fallback']
    return ("wait" if value == "exclusive" else value), []


def resolve_run(cfg, *, local: bool = False, no_local: bool = False, env=None) -> dict:
    """`{local, busy, notes}` for the run; `local` through `cheap_tier_default.resolve_local`."""
    on = cheap_tier_default.resolve_local(cfg, local=local, no_local=no_local, env=env)
    busy, notes = local_mode(env)
    return {"local": on, "busy": busy, "notes": notes}


def _strata_model(root) -> str:
    cfg = local_implement_config.load(root) or local_implement_config.DEFAULTS
    return (model_policy.agent_alias(cfg["model"])
            or local_implement_config.DEFAULTS["model"])


def _m51(why: str) -> str:
    return f"M51: {why}; cheap site falls back to sonnet"


def engine_for(site, run, route_state, available, root=".") -> dict:
    """`{engine, model, effort, note}` for `site`. `available` is a zero-arg
    backend probe, called only for a cheap site under `--local`."""
    if cheap_classes.klass(site) != cheap_classes.CHEAP:
        return {"engine": "opus", "model": "opus", "effort": None, "note": None}
    if not run.get("local"):
        return {"engine": "sonnet", "model": "sonnet", "effort": None, "note": None}
    state = route_state.split("/", 1)[0]
    if route_state == tier_ladder.MALFORMED or state == "router-down":
        return {"engine": "halt", "model": None, "effort": None,
                "note": f"router unusable ({route_state}); halting"}
    if state in ("routed", "unrouted") and "/" in route_state:
        pass
    elif route_state not in (ladder_entry.MISSING, tier_ladder.STALE):
        raise ValueError(f"unknown route label: {route_state!r}")
    if state == "routed" and "/" in route_state:
        if available():
            return {"engine": "strata", "model": _strata_model(root), "effort": None,
                    "note": None}
        return {"engine": "sonnet", "model": "sonnet", "effort": None,
                "note": _m51("tp-local backend absent")}
    return {"engine": "sonnet", "model": "sonnet", "effort": None,
            "note": _m51(f"route {route_state}")}


def busy_action(policy, waited_since, now, ceiling_s) -> str:
    """`fallback` -> sonnet; `wait` -> wait until the ceiling, then halt."""
    if policy != "wait":
        return "sonnet"
    return "halt" if now - waited_since >= ceiling_s else "wait"


def main(argv=None, *, route_check=local_route_check.check,
         available=local_backend.available) -> int:
    ap = argparse.ArgumentParser(prog="cheap_engine.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("resolve")
    r.add_argument("site")
    r.add_argument("--root", default=".")
    g = r.add_mutually_exclusive_group()
    g.add_argument("--local", action="store_true")
    g.add_argument("--no-local", action="store_true")
    args = ap.parse_args(argv)
    cfg = repo_config_load.load_repo_config(args.root).config
    run = resolve_run(cfg, local=args.local, no_local=args.no_local, env=os.environ)
    label = ladder_entry.MISSING
    if run["local"] and cheap_classes.klass(args.site) == cheap_classes.CHEAP:
        label = tier_ladder.route_label(route=route_check(os.environ))
    row = engine_for(args.site, run, label, available, root=args.root)
    row["notes"] = run["notes"]
    print(json.dumps(row))
    return 0


if __name__ == "__main__":
    sys.exit(main())
