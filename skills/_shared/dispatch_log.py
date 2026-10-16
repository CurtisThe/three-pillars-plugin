#!/usr/bin/env python3
"""dispatch_log.py — one dispatch/telemetry record: ndjson + a decisions.md line.

design: run-throughput (detailed-design-part-a.md §Telemetry — dispatch_log.py)

`record(...)` builds the one dict per dispatch attempt — model/effort resolved through
`model_policy.agent_spec`, never from an agent's own frontmatter. `line(rec)` renders the
`[dispatch]` decisions.md line. The CLI writes the record to
`<design_dir>/dispatch-telemetry.ndjson` (one `O_APPEND` write) and, when `--decisions` is
given, appends `line(rec)` through `local_route_log.append_entry` — the ONLY decisions.md
write this module ever makes. dispatch_log.py never opens decisions.md itself.

Measurement (operator ruling Q3, Decision 12): every record also carries `started_at` /
`ended_at` (ISO UTC), `wall_s` (given, else their difference), `tokens` (the subagent usage total
when the spawn reports it; else null with a `tokens_reason` — never 0), `served_by`
(`router_stats.served_by`, the one derivation shared with the ladder: local | sonnet | opus |
fallback, never the requested rung) and `rung` / `phase` for `dispatch_report`'s totals. An inline
record (`--inline`) records `wall_s` at least.
"""
from __future__ import annotations

import argparse
import datetime
import json
import math
import os
import sys
from pathlib import Path

_SHARED = str(Path(__file__).resolve().parent)
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

import attempt_scan  # noqa: E402
import local_implement_config  # noqa: E402
import local_route_log  # noqa: E402
import model_policy  # noqa: E402
import repo_config_load  # noqa: E402
import router_stats  # noqa: E402
import served_rung  # noqa: E402
import transcript_tail  # noqa: E402
import transcript_usage  # noqa: E402

NDJSON_NAME = "dispatch-telemetry.ndjson"

_USAGE_KEYS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens",
               "output_tokens", "thinking_tokens")


def _transcript_usage(agent_id: str, config_dir) -> dict:
    """``usage`` / ``usage_source`` / ``usage_reason`` plus ``fresh`` — the transcript's
    cumulative fresh total — when one is recorded (M47: the row's ``tokens`` becomes it,
    the harness number stays ``tokens_harness``). One leading ``agent-`` is stripped
    before locating; an unfound or unparseable transcript is a ``usage_reason``, never a
    raise (telemetry never gates a dispatch)."""
    fields = {"usage": None, "usage_source": None, "usage_reason": None}
    try:
        agent_id = str(agent_id).removeprefix("agent-")
        path = attempt_scan.locate(agent_id, config_dir)
        if path is None:
            fields["usage_reason"] = "no transcript for agent id"
            return fields
        s = transcript_usage.summarize(transcript_tail.read_records(path))
        fresh = s["fresh_tokens"]
        if not (isinstance(fresh, int) and not isinstance(fresh, bool) and fresh > 0):
            fields["usage_reason"] = "transcript has no usage"
            return fields
        fields.update(usage={key: s.get(key) for key in _USAGE_KEYS},
                      usage_source=s.get("source"))
        fields["fresh"] = fresh
    except Exception:  # noqa: BLE001 — a broken transcript is a reason, not an error
        fields["usage_reason"] = fields.get("usage_reason") or "transcript unreadable"
    return fields


def _stamp(value) -> str | None:
    """An ISO UTC stamp (``...Z``) for an ISO string, epoch seconds or numeric string, else None."""
    epoch = isinstance(value, (int, float)) or str(value).replace(".", "", 1).isdigit()
    try:
        when = (datetime.datetime.fromtimestamp(float(value), datetime.timezone.utc)
                if epoch else
                datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00")))
    except (TypeError, ValueError, OverflowError):
        return None
    when = when if when.tzinfo else when.replace(tzinfo=datetime.timezone.utc)
    return when.astimezone(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def measure(*, started_at=None, ended_at=None, wall_s=None, tokens=None, tokens_reason=None,
            family=None, local_requests=None) -> dict:
    """The Q3 measurement fields; ``tokens`` is never 0 (0 or absent → null + reason)."""
    start, end = _stamp(started_at), _stamp(ended_at)
    if wall_s is None and start and end:
        wall_s = (datetime.datetime.fromisoformat(end[:-1])
                  - datetime.datetime.fromisoformat(start[:-1])).total_seconds()
    good = isinstance(tokens, int) and not isinstance(tokens, bool) and tokens > 0
    return {"started_at": start, "ended_at": end,
            "wall_s": round(float(wall_s), 1) if wall_s is not None else None,
            "tokens": tokens if good else None,
            "tokens_reason": None if good else (tokens_reason or (
                "the spawn reported 0 (never recorded as 0)" if tokens == 0
                else "the spawn reported no usage total")),
            "served_by": router_stats.served_by(family, local_requests)}


def record(design_dir, *, role, agent, reason, outcome, route="-", served=None,
           config=None, rung=None, phase=None, local_requests=None, slot=None,
           oracle=None, escalated=None, ab_pair=None, findings=None, shape=None,
           ab_arm=None, requested_rung=None, fallback=None, fallback_requests=None,
           lease_wait_s=None, measure_state=None, agent8=None, **timing) -> dict:
    """One dispatch telemetry record: `{role, agent, model, effort, route,
    reason, outcome}`, plus `served` when given (not None).

    The other fields are added only when not None, so a legacy call gives a byte-identical row:
    `slot`, `oracle`, `escalated`, `ab_pair` (cheap-tier-offload), `findings` (`{n, classes}`),
    `shape`, `ab_arm` (review-prep 7.1), and the served-rung `requested_rung`, `fallback`,
    `fallback_requests`, `lease_wait_s`, `measure_state` (stored as `measure`), `agent8`. A
    `requested_rung` also sets `served_rung` / `fallback` from `served_rung.served(...)`.

    `agent=None` is the inline-Opus dispatcher attempt (a slot the dispatcher itself ran, never
    spawned): model is `model_policy.PINNED`, effort is the literal `"inline (dispatcher
    effort)"` — no `agent_spec` lookup. Any other `agent` resolves model/effort via
    `model_policy.agent_spec(agent, config, local_cfg)`, never from the agent's own frontmatter.
    `local_cfg` is `config["local_implement"]` merged over `local_implement_config.DEFAULTS`
    (DEFAULTS alone when the block is absent), so a partial block still labels each arm and a
    `tp-task-worker-local-*` rung name never raises. A spawned `agent` with a ladder `rung` logs
    `rung_model(rung, local_cfg)` as its model, so a `tp-drafter` sonnet or opus arm never logs
    its `rung:local` default; `code` and `agent=None` are unchanged.
    """
    if agent is None:
        model, effort = model_policy.PINNED, "inline (dispatcher effort)"
    else:
        block = (config or {}).get("local_implement")
        local_cfg = {**local_implement_config.DEFAULTS,
                     **(block if isinstance(block, dict) else {})}
        try:
            spec = model_policy.agent_spec(agent, config, local_cfg)
            model, effort = spec["model"], spec["effort"]
        except (KeyError, ValueError):  # an agent with no AGENTS row is still logged
            model, effort = "-", "-"
        if rung:  # the arm that ran is the rung, not a `rung:local` AGENTS row (tp-drafter)
            try:
                model = model_policy.rung_model(rung, local_cfg)
            except ValueError:  # `code`, or a rung with no model: the agent's model stands
                pass
    family = (rung.rsplit("-", 1)[0] if rung else "opus" if agent is None
              else model_policy.agent_alias(model) or "local")
    rec = {
        "role": role, "agent": agent, "model": model, "effort": effort,
        "route": route, "reason": reason, "outcome": outcome, "rung": rung,
        "phase": str(phase) if phase is not None else None,
        **measure(family=family, local_requests=local_requests, **timing),
    }
    optional = {"served": served, "slot": slot, "oracle": oracle, "escalated": escalated,
                "ab_pair": ab_pair, "findings": findings, "shape": shape, "ab_arm": ab_arm,
                "requested_rung": requested_rung, "fallback": fallback, "agent8": agent8,
                "fallback_requests": fallback_requests, "measure": measure_state}
    if requested_rung is not None:
        optional["served_rung"], optional["fallback"] = served_rung.served(
            requested_rung, rung, rec["served_by"], fallback, fallback_requests or 0)
    rec.update({k: v for k, v in optional.items() if v is not None})
    if lease_wait_s is not None:  # a non-finite wait (an unusable flag) is a null, never a drop
        rec["lease_wait_s"] = lease_wait_s if math.isfinite(lease_wait_s) else None
    return rec


SLOT_ORACLES = ("pass", "fail")  # a cheap-tier row's `oracle` (cheap-dispatch.md, Record)


def _bool_flag(value: str) -> bool:
    """argparse type for `--escalated {true,false}`."""
    if value not in ("true", "false"):
        raise argparse.ArgumentTypeError(f"expected true or false, not {value!r}")
    return value == "true"


def _findings_json(value: str) -> dict:
    """argparse type for `--findings`: a JSON object `{"n": int, "classes": [...]}`
    and nothing else — anything else is a usage error (exit 2)."""
    try:
        parsed = json.loads(value)
    except (ValueError, TypeError) as exc:
        raise argparse.ArgumentTypeError(f"--findings is not a JSON object: {exc}")
    if (not isinstance(parsed, dict) or set(parsed) != {"n", "classes"}
            or isinstance(parsed["n"], bool) or not isinstance(parsed["n"], int)
            or not isinstance(parsed["classes"], list)):
        raise argparse.ArgumentTypeError(
            "--findings must be a JSON object with exactly an int 'n' and a list 'classes'")
    return parsed


def line(rec: dict) -> str:
    """`"[dispatch] <role> → <agent|inline> (<model>, <effort>, <route>) —
    <reason>: <outcome>"`. `rec["agent"] is None` renders as `inline`."""
    who = rec["agent"] if rec["agent"] is not None else "inline"
    return (f"[dispatch] {rec['role']} → {who} ({rec['model']}, {rec['effort']}, "
            f"{rec['route']}) — {rec['reason']}: {rec['outcome']}")


def resolve_dir(design_dir) -> Path:
    """``design_dir``, or — when it is a ``tp-designs/<slug>`` that Tier 5.6 has archived —
    its ``completed-tp-designs/<slug>``, so a post-archive row (the design-complete dispatch,
    Slot 10, every Slot 11 angle) lands in the archived ndjson the Tier 7 flush commit stages."""
    path = Path(design_dir)
    if not path.is_dir() and path.parent.name == "tp-designs":
        archived = path.parent.parent / "completed-tp-designs" / path.name
        if archived.is_dir():
            return archived
    return path


def _write_ndjson(design_dir, rec: dict) -> None:
    """One `O_WRONLY|O_CREAT|O_APPEND` open, one `os.write` per record —
    `dispatch_log`'s own file, never touched by `local_route_log`."""
    path = Path(design_dir) / NDJSON_NAME
    payload = (json.dumps(rec, sort_keys=True) + "\n").encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(fd, payload)
    finally:
        os.close(fd)


write_ndjson = _write_ndjson  # public: dispatch_tasks appends task-attempt rows through it


def _served_fields(args) -> dict:
    """`record` kwargs from the served-rung flags; a bad free-text value is a note, never exit 2."""
    fb, ms, ws, req = args.fallback, args.measure, args.lease_wait_s, args.requested_rung
    aid = (args.agent_id or "").removeprefix("agent-")[:8] if req is not None else ""
    if fb is not None and served_rung.normalize(fb) != fb:
        print(f"dispatch_log: fallback {fb} unlisted, recorded as unrecorded", file=sys.stderr)
    if ms not in (None, "off", "owner", "other"):
        print(f"dispatch_log: measure {ms} ignored", file=sys.stderr)
    try:
        wait = None if ws is None else float(ws)
    except ValueError:
        wait = math.nan
    if wait is not None and not math.isfinite(wait):
        print(f"dispatch_log: lease-wait-s {ws} ignored", file=sys.stderr)
    if str(args.rung).startswith("local-") and args.local_requests is None:
        print("dispatch_log: local rung recorded without --local-requests", file=sys.stderr)
    return {"requested_rung": req, "fallback_requests": args.fallback_requests,
            "fallback": None if fb is None else served_rung.normalize(fb), "lease_wait_s": wait,
            "measure_state": ms if ms in ("owner", "other") else None, "agent8": aid or None}


def main(argv: list[str] | None = None) -> int:
    """`record --design-dir D --role R --agent A|--inline --reason X --outcome
    Y [--route L] [--decisions PATH]` — writes the ndjson record, optionally
    appends the decisions.md line through `local_route_log.append_entry`, and
    prints the record JSON on stdout. Always exits 0."""
    parser = argparse.ArgumentParser(description="dispatch/telemetry record")
    sub = parser.add_subparsers(dest="command", required=True)
    rp = sub.add_parser("record", help="build, log and print one dispatch record")
    rp.add_argument("--design-dir", required=True, type=Path)
    rp.add_argument("--role", required=True)
    agent_group = rp.add_mutually_exclusive_group(required=True)
    agent_group.add_argument("--agent")
    agent_group.add_argument("--inline", action="store_true")
    rp.add_argument("--reason", required=True)
    rp.add_argument("--outcome", required=True)
    rp.add_argument("--route", default="-")
    rp.add_argument("--decisions", type=Path)
    rp.add_argument("--root", default=".", help="repo whose config models resolve against")
    for flag in ("--started-at", "--ended-at", "--tokens-reason", "--rung", "--phase",
                 "--slot", "--oracle", "--ab-pair", "--requested-rung", "--fallback",
                 "--lease-wait-s", "--measure"):
        rp.add_argument(flag)
    rp.add_argument("--escalated", type=_bool_flag, metavar="{true,false}")
    rp.add_argument("--findings", type=_findings_json,
                    help='JSON {"n": int, "classes": [...]}; anything else is a usage error')
    rp.add_argument("--shape")
    rp.add_argument("--ab-arm", choices=("base", "prep"))
    rp.add_argument("--wall-s", type=float)
    rp.add_argument("--tokens", type=int)
    rp.add_argument("--local-requests", type=int)
    rp.add_argument("--fallback-requests", type=int)
    rp.add_argument("--agent-id", help="the spawn's agentId: tokens from its transcript")
    rp.add_argument("--config-dir", help="config dir for the transcript (default: "
                                         "$CLAUDE_CONFIG_DIR, then ~/.claude)")
    args = parser.parse_args(argv)
    if args.slot is not None and args.oracle not in (None, *SLOT_ORACLES):
        # cheap_ab rates only `pass`: any other string would read as a silent fail
        parser.error(f"--oracle must be one of {', '.join(SLOT_ORACLES)} when --slot is given")

    agent = None if args.inline else args.agent
    args.design_dir = resolve_dir(args.design_dir)
    if args.decisions is not None:
        args.decisions = resolve_dir(args.decisions.parent) / args.decisions.name
    try:
        config = repo_config_load.load_repo_config(args.root).config
    except Exception:  # noqa: BLE001 — telemetry never fails on a bad config
        config = None
    rec = record(args.design_dir, role=args.role, agent=agent, reason=args.reason,
                 outcome=args.outcome, route=args.route, config=config, rung=args.rung,
                 phase=args.phase, local_requests=args.local_requests,
                 started_at=args.started_at, ended_at=args.ended_at, wall_s=args.wall_s,
                 tokens=args.tokens, tokens_reason=args.tokens_reason, slot=args.slot,
                 oracle=args.oracle, escalated=args.escalated, ab_pair=args.ab_pair,
                 findings=args.findings, shape=args.shape, ab_arm=args.ab_arm,
                 **_served_fields(args))
    if args.agent_id is not None:
        # M47 (task-worker-sonnet 1.5): the slot row's tokens come from the spawn's
        # transcript cumulative usage; the harness number is kept as tokens_harness.
        tu = _transcript_usage(args.agent_id, args.config_dir)
        rec.update(usage=tu["usage"], usage_source=tu["usage_source"],
                   usage_reason=tu["usage_reason"], tokens_harness=args.tokens)
        if "fresh" in tu:
            rec["tokens"] = tu["fresh"]
            rec["tokens_reason"] = None  # the recorded total supersedes the report reason
    _best_effort("ndjson row", _write_ndjson, args.design_dir, rec)
    if args.decisions is not None:
        _best_effort("decisions.md line", local_route_log.append_entry, args.decisions, line(rec))
    print(json.dumps(rec, sort_keys=True))
    return 0


def _best_effort(what: str, write, *args) -> None:
    """Run one write; an ``OSError`` (e.g. a missing design dir) is a stderr note, never
    an exit: telemetry never gates a dispatch."""
    try:
        write(*args)
    except OSError as exc:
        print(f"dispatch_log: {what} not written ({type(exc).__name__}: {exc})",
              file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
