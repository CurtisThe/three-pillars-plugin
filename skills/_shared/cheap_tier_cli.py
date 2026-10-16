#!/usr/bin/env python3
"""cheap_tier_cli.py — the cheap-tier `spec` / `task-table` CLI every site calls.

design: cheap-tier-offload (Phase 3)

    python3 "$TP_ROOT"/skills/_shared/cheap_tier_cli.py spec --slot S --root R \
        [--cheap-tier {on,ab}] [--route JSON | --route-from PATH] [--probe] [--design D] \
        [--busy-policy {fallback,wait}] [--waited-since EPOCH]
    python3 "$TP_ROOT"/skills/_shared/cheap_tier_cli.py task-table --plan P --phase N \
        --root R [--cheap-tier {on,ab}]
    python3 "$TP_ROOT"/skills/_shared/cheap_tier_cli.py slots --root R

`spec` prints one JSON object for slot S:

- `{"slot": S, "rung": null}` when the slot is off (`models.<S>: "off"`, or no shipped default
  and no `models.<S>` in the config): the site runs today's path unchanged. The cheap tier is
  always on (design: one-cheap-engine 2.4): an absent `--cheap-tier` is `on`, and
  `--cheap-tier=ab` runs as `on` and prints one `deprecated:` line on stderr;
- `{slot, rung: "code", oracle, on_fail, mode}` for a `code` slot (no model, no
  route, no lease, no agent — D8);
- else `{slot, rung, why, agent, agent_ref, model, oracle, on_fail, mode}`, after the
  route and lease check (`cheap_tier.resolve`). The lease is probed only when the
  route label is `routed/ok`, so an unrouted site never takes the machine-wide lease.

`classifier_judge` has one more gate (Behavior 7, Task 6.6), checked before the
route and lease: its rung is null unless `CLASSIFIER_VERDICT`
(`skills/tp-pr-iterate/eval/classifier-rung.json`, written by `run_eval.py --rung`)
holds `thresholds_met: true`, its `local_model` equals the current
`local_implement.model`, and its `route` equals the router identity (`base_url`) of
the route passed in. No route passed (every site today) is null. The gate reads that
file only; `run_eval` is dev-only and is never imported, so a consumer repo (no
file) keeps today's classifier.

`--probe` (design: cheap-tier-local-routing, Task 5.1) replaces that route and lease check
with one `cheap_route.probe(slot, rung, root, design=D)` (`--design` is optional: absent is
`None`, a non-owner of any measurement window), whose labels go to `cheap_tier.resolve`. A
model spec then also carries `requested_rung` (the configured rung), `fallback` (a reason or
null), `lease_wait_s` (a number) and `measure` (`off`/`owner`/`other`). A null or `code` spec
never probes and keeps its shape. A kept `local-*` rung also carries `mirror_rung` (its
`cheap_tier.MIRROR`), `mirror_agent_ref` and `mirror_model` (resolved as `agent_ref` and `model`
are): the spawn-failed fallback of `cheap-dispatch.md` §Local rung. Without `--probe` the output
is unchanged.

`--busy-policy` (default `strata_spawn.busy_policy`: `TP_LOCAL_MODE`, else `strata_spawn.busy`
in the config, else `fallback`) changes one case. Under `wait` with the lease busy, `spec` makes
one bounded `strata_spawn.wait` call (a 270 s budget, `started_at` = `--waited-since`, so it fits
the 300 s cache TTL) and prints the kept local rung with `"action": "wait"` and `waited_since`;
the site re-runs the same `spec` with `--waited-since <waited_since>`. Past
`strata_spawn.CEILING_S` it prints `"action": "halt"` (the finalizer's case). A slot that came
free during the wait prints no `action`; an unrouted router falls to the Sonnet mirror (M51).

The config is read raw (`json.loads` of `.three-pillars/config.json`), never through
`repo_config_load.load_repo_config`, which would prune an excluded or unknown
`models` key before `cheap_tier.load_slots` could refuse it (plan.md Deviations 7).
A programmatic `cheap_flag="off"` (not a CLI value) reads no config at all.

Exit codes: 0 (a spec, null included); 2 (a config error, an unknown slot, or `--slot
task`, which uses `task-table`) with one stderr line; 3 (`agent-unresolved: …`, a
broken install) with that line on stderr. A site reads any non-zero exit, or
unparseable output, as a null rung (`skills/_shared/cheap-dispatch.md` step 1).

`task-table` is the task lever (D7). Unless `models.task` is `"off"` it prints `cheap_tier.task_table(task_eligibility.phase_rows(...))` as JSON and exits 0:
local rows start at `sonnet-xhigh`, clerical rows at `sonnet-medium`. The rows come
from `task_eligibility`'s own derivation, never re-derived here (plan.md Deviations
6), and no `local_implement` block is needed. With the lever off (`models.task: "off"`) it
prints `[]` and exits 1; that exit is the D7 permission key. A config or plan error exits 2.

`slots` is the orchestrator's Tier 1 preflight (`tp-run-full-design/cheap-tier.md`):
`cheap_tier.load_slots` on the raw config, printed as a `{slot: rung}` JSON map (exit
0), or one stderr line and exit 2 for an excluded or unknown slot, a bad rung or an
unreadable config.
Stdlib-only; no model is ever called here.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

_SHARED = str(Path(__file__).resolve().parent)
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

import agent_ref  # noqa: E402 — in-repo, stdlib-only sibling
import cheap_route  # noqa: E402 — in-repo, stdlib-only sibling
import cheap_deprecation  # noqa: E402 — in-repo, stdlib-only sibling
import cheap_tier  # noqa: E402 — in-repo, stdlib-only sibling
import ladder_rungs  # noqa: E402 — in-repo, stdlib-only sibling
import local_implement_config  # noqa: E402 — in-repo, stdlib-only sibling
import local_lease  # noqa: E402 — in-repo, stdlib-only sibling
import local_route_check  # noqa: E402 — in-repo, stdlib-only sibling
import local_route_log  # noqa: E402 — in-repo, stdlib-only sibling
import strata_spawn  # noqa: E402 — in-repo, stdlib-only sibling
import task_eligibility  # noqa: E402 — in-repo, stdlib-only sibling
import tier_ladder  # noqa: E402 — in-repo, stdlib-only sibling
import wait_budget  # noqa: E402 — in-repo, stdlib-only sibling

CONFIG_REL = ".three-pillars/config.json"
WAIT_BUDGET_S = wait_budget.WAIT_BUDGET_S  # one strata_spawn.wait per spec: inside the 300 s TTL
DRAFTERS = {"medium": "tp-drafter", "xhigh": "tp-drafter-xhigh"}
CLASSIFIER_VERDICT = (Path(__file__).resolve().parent.parent / "tp-pr-iterate" / "eval"
                      / "classifier-rung.json")


def raw_config(root) -> dict:
    """`.three-pillars/config.json` under `root` as a dict, read raw ({} when absent).

    Unreadable text, invalid JSON or a non-object config raises `ValueError`."""
    path = Path(root) / CONFIG_REL
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError(f"{CONFIG_REL} unreadable: {exc}") from None
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ValueError(f"{CONFIG_REL} is not valid JSON: {exc}") from None
    if not isinstance(data, dict):
        raise ValueError(f"{CONFIG_REL} is not a JSON object")
    return data


def _route_text(path: str | None) -> str | None:
    if path is None:
        return None
    try:
        return Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _router(route, route_text: str | None) -> str | None:
    """The router identity (`base_url`) of the route passed in, else None."""
    if route is not None:
        parsed = local_route_check.parse_result(route)
    else:
        parsed = local_route_log.current_route(route_text) if route_text is not None else None
    return (parsed or {}).get("base_url")


def classifier_gate(root, route, route_text: str | None) -> bool:
    """True only when the eval verdict file shows the local rung meets its thresholds
    for the current local model and router (see the module docstring)."""
    try:
        verdict = json.loads(CLASSIFIER_VERDICT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(verdict, dict) or verdict.get("thresholds_met") is not True:
        return False
    router = _router(route, route_text)
    local_cfg = local_implement_config.load(root) or local_implement_config.DEFAULTS
    return (router is not None and verdict.get("route") == router
            and verdict.get("local_model") == local_cfg["model"])


def _flag(cheap_flag):
    """The run flag as it behaves: absent (None) and `ab` run as `on`; an explicit `off` stays."""
    return "on" if cheap_flag in (None, "ab") else cheap_flag


def _poll(rung, action, design, waited_since, now):
    """`(rung, why, extra)` once `cheap_tier.resolve` said `wait` or `halt`: one bounded
    `strata_spawn.wait` for `wait`; `extra` holds `action` / `waited_since` while still waiting."""
    started = waited_since if waited_since is not None else (time.time() if now is None else now)
    pending = {"waited_since": started}
    if action == cheap_tier.HALT:
        return rung, f"{rung}: waited past the {strata_spawn.CEILING_S} s ceiling", {
            **pending, "action": "halt"}
    state, why, _waited = strata_spawn.wait(design, budget_s=WAIT_BUDGET_S, started_at=started,
                                            policy="wait")
    if state in ("free", "unchecked"):  # the slot came free: the rung runs, no action
        return rung, f"{rung}: routed/ok, lease free", {}
    if state == "still-busy":
        return rung, f"{rung}: waiting for the slot ({why})", {**pending, "action": "wait"}
    if state in ("wait-exhausted", "unhealthy"):
        return rung, f"{rung}: {why}", {**pending, "action": "halt"}
    mirror = cheap_tier.MIRROR[rung]  # unrouted, or a fallback answer: the Sonnet mirror (M51)
    return mirror, f"{rung}->{mirror}: {why}", {}


def spec(slot: str, root, *, cheap_flag="on", route=None, route_from=None, probe=False,
         design=None, busy_policy=None, waited_since=None, now=None) -> dict:
    """The spec dict for `slot` (see the module docstring). Raises `ValueError` for a
    config error or a bad slot, and `agent_ref.AgentRefError` for a broken install."""
    if slot == "task":
        raise ValueError("--slot task: the task lever uses task-table, not spec")
    cheap_flag = _flag(cheap_flag)
    config = raw_config(root) if cheap_flag == "on" else None
    rung = cheap_tier.slot_rung(slot, config, cheap_flag=cheap_flag)
    if rung is None:
        return {"slot": slot, "rung": None}
    row = cheap_tier.SLOTS[slot]
    tail = {"oracle": row.oracle, "on_fail": row.on_fail, "mode": cheap_flag}
    if rung == "code":
        return {"slot": slot, "rung": "code", **tail}
    route_text = _route_text(route_from)
    if slot == "classifier_judge" and not classifier_gate(root, route, route_text):
        return {"slot": slot, "rung": None}
    extra = {}
    if probe:
        found = cheap_route.probe(slot, rung, root, design=design, route=route,
                                  route_text=route_text)
        label, lease_state = found["route_label"], found["lease_state"]
        extra = {"requested_rung": rung, "fallback": found["fallback"],
                 "lease_wait_s": found["lease_wait_s"], "measure": found["measure"]}
    else:
        label = tier_ladder.route_label(route, route_text, os.environ)
        lease_state = local_lease.acquire()[0] if label == "routed/ok" else "unchecked"
    policy = strata_spawn.busy_policy(config or {}, busy_policy)
    rung, why = cheap_tier.resolve(rung, route_label=label, lease_state=lease_state,
                                   busy_policy=policy, waited_since=waited_since, now=now)
    if why in (cheap_tier.WAIT, cheap_tier.HALT):
        rung, why, held = _poll(rung, why, design, waited_since, now)
        extra.update(held)
        if probe and rung.startswith("local-"):
            extra["fallback"] = None  # waiting (or halting) is no fallback
    agent = DRAFTERS[rung.rsplit("-", 1)[1]]
    local_cfg = local_implement_config.load(root) or dict(local_implement_config.DEFAULTS)
    if probe and rung in cheap_tier.MIRROR:  # a kept local-* rung: its spawn-failed mirror
        mirror = cheap_tier.MIRROR[rung]
        extra.update(mirror_rung=mirror,
                     mirror_agent_ref=agent_ref.resolve(DRAFTERS[mirror.rsplit("-", 1)[1]]),
                     mirror_model=ladder_rungs.effective_model(mirror, local_cfg, label))
    return {"slot": slot, "rung": rung, "why": why, "agent": agent,
            "agent_ref": agent_ref.resolve(agent),  # the framework root, never --root
            "model": ladder_rungs.effective_model(rung, local_cfg, label), **tail, **extra}


def task_table(plan: str, phase: int, root, *, cheap_flag="on") -> list[dict] | None:
    """The lever's tier table, or None when the lever is off (`models.task: "off"`). An
    absent flag is `on` (design: one-cheap-engine 2.4). A config or plan error raises
    `ValueError`."""
    if _flag(cheap_flag) != "on":
        return None
    if "task" not in cheap_tier.load_slots(raw_config(root)):
        return None
    try:
        text = Path(plan).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError(f"plan unreadable: {exc}") from None
    return cheap_tier.task_table(task_eligibility.phase_rows(text, phase, root))


_FLAG_HELP = "deprecated, changes nothing: the cheap tier is always on (ab runs as on)"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="The cheap-tier spec for one slot, "
                                     "or the task lever's tier table.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("spec", help="print the cheap-tier spec for one slot")
    sp.add_argument("--slot", required=True)
    sp.add_argument("--root", default=".", help="repository root (default: .)")
    sp.add_argument("--cheap-tier", choices=("on", "ab"), default=None, help=_FLAG_HELP)
    sp.add_argument("--busy-policy", choices=strata_spawn.BUSY_POLICIES, default=None,
                    help="a busy slot: fallback (Sonnet) or wait; default strata_spawn.busy_policy")
    sp.add_argument("--waited-since", type=float, default=None, metavar="EPOCH",
                    help="when the wait began (the last spec's waited_since); default: now")
    sp.add_argument("--probe", action="store_true",
                    help="probe the route, lease and measurement window (cheap_route.probe)")
    sp.add_argument("--design", default=None, help="the design asking (default: none)")
    route = sp.add_mutually_exclusive_group()
    route.add_argument("--route", help="a route result, as a JSON object or string")
    route.add_argument("--route-from", help="a decisions.md path to read the route from")
    tt = sub.add_parser("task-table", help="print the task lever's tier table")
    tt.add_argument("--plan", required=True, help="path to plan.md")
    tt.add_argument("--phase", type=int, required=True)
    tt.add_argument("--root", default=".", help="repository root (default: .)")
    tt.add_argument("--cheap-tier", choices=("on", "ab"), default=None, help=_FLAG_HELP)
    sl = sub.add_parser("slots", help="the Tier 1 preflight: load_slots on the raw config")
    sl.add_argument("--root", default=".", help="repository root (default: .)")
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    if args.cmd != "slots" and args.cheap_tier == "ab":  # only `ab` is noisy; the sites pass `on`
        for note in cheap_deprecation.notes({}, cheap_tier=args.cheap_tier):
            print(note, file=sys.stderr)
    if args.cmd == "slots":
        try:
            print(json.dumps(cheap_tier.load_slots(raw_config(args.root)), sort_keys=True))
        except ValueError as exc:
            print(f"cheap-tier: {exc}", file=sys.stderr)
            return 2
        return 0
    if args.cmd == "task-table":
        try:
            rows = task_table(args.plan, args.phase, args.root, cheap_flag=args.cheap_tier)
        except ValueError as exc:
            print(f"cheap-tier: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(rows or [], indent=2, sort_keys=True))
        return 0 if rows is not None else 1
    try:
        out = spec(args.slot, args.root, cheap_flag=args.cheap_tier, route=args.route,
                   route_from=args.route_from, probe=args.probe, design=args.design,
                   busy_policy=args.busy_policy, waited_since=args.waited_since)
    except agent_ref.AgentRefError as exc:  # a ValueError subclass: caught first
        print(str(exc), file=sys.stderr)
        return 3
    except ValueError as exc:
        print(f"cheap-tier: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(out, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
