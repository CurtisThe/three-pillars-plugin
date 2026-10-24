#!/usr/bin/env python3
"""tier_ladder.py — the per-task retry/escalation state machine (explicit total table).

design: local-implement-and-review (Behaviors 4, 6, 7); run-throughput (rungs, classes)

A task climbs rungs (``ladder_rungs``: ``<family>-<effort>``). ``next_step(record, outcome,
cfg, evidence=None)`` is pure: it returns ``(action, rung, record')`` with an updated copy.
A record's legacy family entries (``local``/``sonnet``/``opus``) are read through
``ladder_rungs.LEGACY``. ``attempts[rung]`` counts attempts that ran, never ``unavailable``,
``env-error`` or a cheap rung's ``FAIL`` ``no oracle``; ``N = 1 + max_retries`` per cheap rung.
A FAIL is classed by ``failure_class`` (``evidence``: failing ids, hook tail, row).

| rung     | outcome / class                  | action                                    |
|----------|----------------------------------|-------------------------------------------|
| any      | PASS / PASS-unverified           | done (/-unverified)                       |
| any      | env-error; ``agent-unresolved:`` | halt (final env-error), never a fallback  |
| cheap    | unavailable                      | ``unavailable_next`` (same effort)        |
| opus-*   | unavailable                      | block (no family above opus)              |
| any      | FAIL hook-refused (Red refused)  | halt (env-error), stuck hook-refused      |
| any      | FAIL deterministic:<c>           | ``jump(rung, target)``, stuck; top: block |
| local-*  | FAIL runaway, 0 router requests  | ``ladder_outage``: wait, else same-effort |
|          |                                  | sonnet (one attempt, no 2nd local clock)  |
| local-*  | FAIL runaway                     | ``quality_next``, no same-rung retry      |
| any      | FAIL, same fingerprint this rung | ``quality_next``, stuck repeated-failure  |
| cheap    | FAIL quality, attempts < N / = N | retry / ``quality_next``                  |
| opus-*   | FAIL quality                     | ``opus-xhigh``; from ``opus-xhigh`` block |

Any move with ``escalate: false`` blocks. Every target is floored by the record's ``route``
(``route_floor``, same effort) and the floored rung is what the record appends (with
``floored_from``). CLI (the record is a JSON file carried across dispatcher turns):
``start --task ID --tier T --record R [--route JSON | --route-from PATH] [--root .]``
(``T``: a rung, or a legacy family via ``LEGACY``) floors, writes the record and prints
``{tier, rung, agent, agent_ref, model, reason, plan_tier, display}``; ``next --record R
--outcome O`` rewrites R, prints ``{action, tier, rung, agent, agent_ref, model}``. ``agent``
is the bare (telemetry) name, ``agent_ref`` the spawn's ``subagent_type`` (``agent_ref.py``,
``--plugin-root``; unresolvable: exit 2 after the write). ``entry`` / ``telemetry --record
R``; ``entry --record -`` reads stdin. A usage error or a final record exits 2. Stdlib only.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path

_SHARED = str(Path(__file__).resolve().parent)
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

import agent_ref as agent_refs  # noqa: E402 — in-repo, stdlib-only sibling (the resolver)
import local_implement_config  # noqa: E402 — in-repo, stdlib-only sibling
import children_route  # noqa: E402 — in-repo sibling
import local_route_check, local_route_log  # noqa: E402,E401 — in-repo siblings (L3, one-way)
import failure_class, ladder_busy, ladder_outage, model_policy  # noqa: E402,E401 — in-repo siblings
from ladder_entry import (  # noqa: E402,F401
    MISSING, bracket, build_evidence, dispatch_reason, now_stamp, served_verdict, to_decision_entry,
    to_telemetry)
from ladder_rungs import (  # noqa: E402,F401
    LADDER, RUNGS, SAFE_CLAUDE, agent, as_rung, display, effective_model, family, jump,
    quality_next, route_floor, unavailable_next)

OUTCOMES = ("PASS", "PASS-unverified", "FAIL", "unavailable", "env-error")
_DONE = {"PASS": "done", "PASS-unverified": "done-unverified"}
NO_ORACLE = "no oracle"  # task_verify's cheap-rung reason prefix (no runnable Test)

# --- Effective-tier seam: the no-Haiku rule's one home --------------------------------

MALFORMED, STALE = "malformed-route", "stale-route"


def route_label(route=None, route_from_text: str | None = None,
                 env: Mapping[str, str] = {}) -> str:
    """``"<state>/<reason>"`` for the current routing decision. ``route`` (a
    ``--route`` dict or JSON string) wins when given: MALFORMED unless
    ``local_route_check.parse_result`` accepts it. Else ``route_from_text``
    (a design's decisions.md text) is read via ``local_route_log.
    current_route``: MISSING when it is None (absent text, an unreadable
    file mapped to None by the caller, an empty or closed window). A
    file-borne ``routed`` entry is env-bound: STALE unless ``local_route_
    check.target(env)`` succeeds and the entry's ``base_url`` matches
    ``redact_url(env["ANTHROPIC_BASE_URL"])``; any other state returns its
    own label unconditionally. ``route`` itself is never env-bound. Pure."""
    if route is not None:
        parsed = local_route_check.parse_result(route)
        if parsed is None:
            return MALFORMED
        return f"{parsed['state']}/{parsed['reason']}"
    if route_from_text is None:
        return MISSING
    current = local_route_log.current_route(route_from_text)
    if current is None:
        return MISSING
    label = f"{current['state']}/{current['reason']}"
    if current["state"] != "routed":
        return label
    env = children_route.effective_env(env, os.getcwd())
    _url, reason = local_route_check.target(env)
    if reason is not None:
        return STALE
    if current["base_url"] != local_route_check.redact_url(env.get("ANTHROPIC_BASE_URL")):
        return STALE
    return label


def model_for(tier: str, cfg: dict) -> str | None:
    """The model a rung spawns with (delegates to ``model_policy.rung_model``)."""
    return model_policy.rung_model(tier, cfg)


def start(task_id: str, tier: str) -> dict:
    """A fresh ladder record for ``task_id`` starting at ``tier``: a rung, or a legacy
    family read through ``LEGACY`` (``local`` → ``local-medium``)."""
    if tier not in RUNGS + LADDER:
        raise ValueError(f"unknown tier {tier!r}; expected one of {RUNGS + LADDER}")
    tier = as_rung(tier)
    return {"task_id": str(task_id), "tier_path": [tier], "attempts": {tier: 0},
            "escalated": False, "final": None, "verdicts": [], "tokens": None}


def _finish(rec: dict, action: str, final: str) -> tuple[str, None, dict]:
    rec["final"] = final
    return action, None, rec


def _normalize(rec: dict) -> dict:
    """Legacy family entries → rungs, on read (plan-notes §Legacy ladder records)."""
    rec["tier_path"] = [as_rung(t) for t in rec["tier_path"]]
    attempts: dict = {}
    for key, n in rec["attempts"].items():
        attempts[as_rung(key)] = attempts.get(as_rung(key), 0) + int(n)
    rec["attempts"] = attempts
    return rec


def _move(rec: dict, target: str, action: str = "escalate") -> tuple[str, str, dict]:
    """Go to ``target`` floored by the record's route; a floor turns a retry into a move."""
    label = rec.get("route")
    rung, floored = route_floor(target, label) if label is not None else (target, False)
    if floored:
        rec.setdefault("floored_from", target)
    if rung == rec["tier_path"][-1]:
        return action, rung, rec
    rec["tier_path"].append(rung)
    rec["attempts"].setdefault(rung, 0)
    rec["escalated"] = True
    return "escalate", rung, rec


def _up(rec: dict, cfg: dict, target: str | None) -> tuple[str, str | None, dict]:
    if target is None or not cfg["escalate"]:
        return _finish(rec, "blocked", "blocked")
    return _move(rec, target)


def _verdict(rung: str, outcome: str, reason: str, ev: dict, klass: str, fp: str) -> dict:
    # `tier` is rung-labelled too: the `[tier]` entry and telemetry render it as-is.
    v = {"tier": rung, "rung": rung, "outcome": outcome, "reason": reason,
         "class": klass, "fingerprint": fp, "stuck": None,
         "flags": list(ev.get("flags") or []),
         **{k: ev.get(k) for k in ("tokens", "wall_s", "started_at", "ended_at")}}
    if family(rung) == "local":
        v["gen"], v["served"] = ev.get("gen"), ev.get("served")
    if "lease_wait_s" in ev:
        v["lease_wait_s"] = ev["lease_wait_s"]
    return served_verdict(v, outcome)


def next_step(record: dict, outcome: str, cfg: dict, *, reason: str = "",
              red_at_base: str | None = None,
              evidence: dict | None = None, busy_policy: str = "fallback",
              waited_since: float | None = None,
              now: float | None = None) -> tuple[str, str | None, dict]:
    """→ ``(action, rung, record')``; ``action`` ∈ done|retry|escalate|blocked|halt|wait.

    ``rung`` is the rung to run next (retry/escalate), else None. ``record`` is never
    mutated. ``evidence`` (optional): ``failing_tests``/``failing_targets``, ``hook_tail``
    (only from a hook-failed reply), ``row``, and the verdict's ``flags``/``tokens``/
    ``wall_s``/``gen``/``served``. ``red_at_base``, when given, is kept for the entry.
    """
    if outcome not in OUTCOMES:
        raise ValueError(f"unknown outcome {outcome!r}; expected one of {OUTCOMES}")
    if record.get("final"):
        raise ValueError(f"task {record.get('task_id')} is already final: {record['final']}")
    if outcome not in _DONE and str(reason).startswith(agent_refs.UNRESOLVED):
        outcome = "env-error"  # a rejected subagent_type halts; never walks the ladder
    rec = _normalize(copy.deepcopy(record))
    rung = rec["tier_path"][-1]
    fam = family(rung)
    ev = evidence or {}
    tail = str(ev.get("hook_tail") or "")
    klass = failure_class.classify("hook-failed" if outcome == "FAIL" and tail else outcome,
                                   reason, hook_tail=tail, row=ev.get("row"), flags=ev.get("flags"),
                                   first_commit=bool(ev.get("first_commit")))
    if fam == "local" and outcome == "FAIL":  # zero router requests at the clock: a dead backend
        klass = ladder_outage.reclass(klass, reason, ev)
    failing = list(ev.get("failing_tests") or ev.get("failing_targets") or [])
    fp = failure_class.fingerprint(outcome, reason, failing)
    prev = next((v for v in reversed(rec["verdicts"])
                 if v.get("rung") == rung and v.get("outcome") == "FAIL"), None)
    verdict = _verdict(rung, outcome, reason, ev, klass, fp)
    if klass == ladder_outage.OUTAGE:
        verdict["probe"] = ev.get("probe")
    rec["verdicts"].append(verdict)
    verdict["model"] = effective_model(rung, cfg, rec.get("route", MISSING))
    verdict["why"] = dispatch_reason(rec["verdicts"], len(rec["verdicts"]) - 1)
    if red_at_base is not None:
        rec["red_at_base"] = red_at_base
    if outcome == "env-error":
        return _finish(rec, "halt", "env-error")
    no_oracle = klass == "deterministic:no-oracle" and fam != "opus"
    if outcome != "unavailable" and not no_oracle and klass != ladder_outage.OUTAGE:
        rec["attempts"][rung] = rec["attempts"].get(rung, 0) + 1
    if outcome in _DONE:
        return _finish(rec, "done", _DONE[outcome])
    if outcome == "unavailable":
        if ladder_busy.applies(busy_policy, rung, reason) or ladder_outage.waits(
                busy_policy, rung, reason):
            return ladder_busy.step(rec, rung, waited_since, now)
        return _up(rec, cfg, unavailable_next(rung))
    if klass == failure_class.HOOK_REFUSED:  # the hook refuses the same Red on any rung: end the task
        verdict["stuck"], verdict["reason"] = klass, failure_class.hook_refused_reason(reason, tail)
        return _finish(rec, "halt", "env-error")
    if klass.startswith("deterministic:"):
        verdict["stuck"] = "deterministic"
        return _up(rec, cfg, jump(rung, failure_class.target_for(klass)))
    if klass == ladder_outage.OUTAGE:  # one attempt: wait/halt per policy, else the same-effort sonnet
        return (ladder_outage.step(rec, rung, busy_policy, waited_since, now)
                or _up(rec, cfg, unavailable_next(rung)))
    if klass == "runaway" and fam == "local":
        verdict["stuck"] = "runaway"
        return _up(rec, cfg, quality_next(rung))
    if prev is not None and prev.get("fingerprint") == fp:
        verdict["stuck"] = "repeated-failure"
        return _up(rec, cfg, quality_next(rung))
    if fam != "opus" and rec["attempts"][rung] < 1 + int(cfg["max_retries"]):
        return _move(rec, rung, "retry")
    return _up(rec, cfg, quality_next(rung))


# --- `[tier]` decision entry and telemetry -------------------------------------------

# `[tier]` entry/telemetry live in ladder_entry; route_floor/effective_model/display in
# ladder_rungs (re-exported above).


# --- CLI: the record is a plain JSON file carried across dispatcher turns ------------

def _read(path: str) -> dict:
    if path == "-":
        return json.load(sys.stdin)
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _write(path: str, record: dict) -> None:
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=2, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path)


def _route_from_text(path: str | None) -> str | None:
    """The text at ``path`` (utf-8), or ``None`` on any read/decode failure
    (including ``path is None``) — never an error exit."""
    if path is None:
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except (OSError, UnicodeDecodeError):
        return None


def _check_reason(path) -> str:
    """The ``reason`` of a task_verify check JSON; '' when absent or unreadable."""
    try:
        with open(path, encoding="utf-8") as fh:
            return str(json.load(fh).get("reason") or "")
    except (OSError, ValueError, TypeError, AttributeError):
        return ""


def _spawn_ref(rung: str | None, plugin_root) -> str | None:
    """The ``subagent_type`` for ``rung``'s worker (None inline); raises ``AgentRefError``."""
    name = agent(rung) if rung else None
    return agent_refs.resolve(name, plugin_root) if name else None


def _cmd(args) -> str:
    if args.record == "-" and args.cmd not in ("entry", "telemetry"):
        raise ValueError(f"--record - (stdin) is read-only; {args.cmd} rewrites the record")
    if args.cmd == "start":
        cfg = local_implement_config.load(args.root) or dict(local_implement_config.DEFAULTS)
        label = route_label(args.route, _route_from_text(args.route_from), os.environ)
        asked = as_rung(args.tier)
        rung, floored = route_floor(asked, label)  # before the write: no unrouted local rung
        record = start(args.task, rung)
        record["route"] = label
        record["stepped_at"] = now_stamp()  # the first attempt opens after this step
        if floored:
            record["floored_from"] = asked
        _write(args.record, record)
        return json.dumps({"tier": family(rung), "rung": rung, "agent": agent(rung),
                           "agent_ref": _spawn_ref(rung, args.plugin_root),
                           "model": effective_model(rung, cfg, label), "reason": label,
                           "plan_tier": args.tier,
                           "display": display(family(asked), family(rung), label)},
                          sort_keys=True)
    record = _read(args.record)
    if args.cmd == "entry":
        return to_decision_entry(record).rstrip("\n")
    if args.cmd == "telemetry":
        return json.dumps(to_telemetry(record), indent=2, sort_keys=True)
    cfg = local_implement_config.load(args.root) or dict(local_implement_config.DEFAULTS)
    record.setdefault("route", MISSING)  # a pre-hybrid record: floor its targets
    ev = bracket(build_evidence(record["task_id"], args.check_json, args.scan, args.reply_json,
                                args.plan, args.phase, args.watch_json, args.root,
                                args.probe_json),
                 record.get("stepped_at"), now := now_stamp())  # H2: the attempt's span
    if args.lease_wait_s is not None:
        ev["lease_wait_s"] = args.lease_wait_s
    reason = args.reason or _check_reason(args.check_json)
    action, rung, record = next_step(record, args.outcome, cfg, reason=reason,
                                     red_at_base=args.red_at_base, evidence=ev,
                                     busy_policy=args.busy_policy, waited_since=args.waited_since)
    record["stepped_at"] = now  # the next attempt (retry/escalate) opens after this step
    _write(args.record, record)
    model = effective_model(rung, cfg, record["route"]) if rung else None
    return json.dumps({"action": action, "tier": family(rung) if rung else None,
                       "rung": rung, "agent": agent(rung) if rung else None,
                       "agent_ref": _spawn_ref(rung, args.plugin_root),
                       "model": model}, sort_keys=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Per-task tier ladder over a JSON record.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("start")
    sp.add_argument("--task", required=True)
    sp.add_argument("--tier", required=True, choices=RUNGS + LADDER)
    sp.add_argument("--root", default=".", help="repo whose config is read (default: .)")
    route_group = sp.add_mutually_exclusive_group()
    route_group.add_argument("--route", help="a route result, as a JSON object or string")
    route_group.add_argument("--route-from", help="a decisions.md path to read the route from")
    sp = sub.add_parser("next")
    sp.add_argument("--outcome", required=True, choices=OUTCOMES)
    sp.add_argument("--root", default=".", help="repo whose config is read (default: .)")
    sp.add_argument("--reason")
    sp.add_argument("--red-at-base")
    for flag in ("--check-json", "--scan", "--reply-json", "--plan", "--watch-json",
                 "--probe-json"):
        sp.add_argument(flag)
    sp.add_argument("--phase", type=int)
    sp.add_argument("--lease-wait-s", type=float)
    sp.add_argument("--busy-policy", choices=("fallback", "wait"), default="fallback")
    sp.add_argument("--waited-since", type=float)
    for name in ("entry", "telemetry"):
        sub.add_parser(name)
    for sp in sub.choices.values():
        sp.add_argument("--record", required=True, help="the ladder record JSON file")
    for name in ("start", "next"):
        sub.choices[name].add_argument(
            "--plugin-root", default=None,
            help="framework root whose plugin.json names the agents (default: this install)")
    args = parser.parse_args(argv)
    try:
        print(_cmd(args))
    except (OSError, ValueError, KeyError) as exc:
        print(f"tier_ladder: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
