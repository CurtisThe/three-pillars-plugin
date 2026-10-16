"""Per-role runtime/output caps for cheap-engine agents, and the cap verdict.

design: one-cheap-engine (Task 1.4). One table (CAPS) keyed by the
cheap_classes cheap-site names; the task slot (task, tp-task-worker,
tp-task-worker-*) has no row because the tier ladder keeps its own limits.

verdict() returns:
  "stop"     span_s >= hard_s or output_tokens >= hard_tokens
  "wrap-up"  past soft on either axis and not yet warned (the driver's signal)
  "ok"       otherwise (under soft, or past soft but already warned)
Boundaries are inclusive: a value equal to a cap counts as past it.

Task 3.2 adds the driver-facing side: `check()` measures the two axes (span from
the driver's start time, tokens from the router log or the transcript), `main()`
prints the verdict plus one `soft-cap:` note on `wrap-up`, `put_capped()` marks a
stopped agent's partial reply `capped`, and `ledger_row()` builds its ledger row.
`attempt_watchdog.verdict` is not reused here: it is attempt-scoped, not per role.
"""
from __future__ import annotations

import argparse
import datetime
import fnmatch
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import NamedTuple

import cheap_classes
import router_stats
import transcript_tail
import transcript_usage

OK = "ok"
WRAP_UP = "wrap-up"
STOP = "stop"
CAP_FIELD = "capped"  # marks a finding a capped agent produced
FINDING_MARK = "FINDING "  # a finder's inline delivery marker: `FINDING {json}`
BUDGET_LINE = ("Budget: about 15 minutes; at 25 minutes you are stopped and only what you have "
               "delivered counts. Deliver each finding as soon as you confirm it.")
WRAP_UP_MESSAGE = "Soft cap: give your verdict from what you have now, and list what you did not check."


class Cap(NamedTuple):
    soft_s: int
    soft_tokens: int
    hard_s: int
    hard_tokens: int


# Numbers from the seed's router.log data: soft 900 s / 150k, hard 1500 s / 250k.
_DEFAULT = Cap(900, 150_000, 1500, 250_000)

_TASK_SLOT = frozenset({"task", "tp-task-worker", "tp-task-worker-*"})

CAPS: dict[str, Cap] = {
    name: _DEFAULT
    for name in sorted(cheap_classes.cheap_sites() - _TASK_SLOT)
}


def cap_for(role: str) -> Cap:
    """The cap row for `role`; KeyError for the task slot, judgment roles and
    unclassed names."""
    if cheap_classes.klass(role) != cheap_classes.CHEAP:
        raise KeyError(f"{role!r} is not a cheap role; no cap row")
    if role in _TASK_SLOT or fnmatch.fnmatchcase(role, "tp-task-worker-*"):
        raise KeyError(f"{role!r} is the task slot; the ladder keeps its own limits")
    if role in CAPS:
        return CAPS[role]
    for pattern, cap in CAPS.items():
        if fnmatch.fnmatchcase(role, pattern):
            return cap
    raise KeyError(f"{role!r} has no agent_caps.CAPS row")


def verdict(role: str, span_s: float, output_tokens: int, warned: bool,
            scale: float = 1.0) -> str:
    """`scale` (0 < scale <= 1) shrinks the span axis only: a review segment's deadline."""
    cap = cap_for(role)
    scale = min(1.0, scale) if scale > 0 else 1.0
    if span_s >= cap.hard_s * scale or output_tokens >= cap.hard_tokens:
        return STOP
    if span_s >= cap.soft_s * scale or output_tokens >= cap.soft_tokens:
        return OK if warned else WRAP_UP
    return OK


# --- the cap check (Task 3.2) ------------------------------------------------

NO_TOKENS_NOTE = "no-tokens"


def _router_tokens(router_log, agent_id) -> int | None:
    """The agent's total router output tokens, or None when it has no stats rows.

    The sum over the agent's LOCAL-STATS lines — `router_stats.gen_stats` reports
    per-request `max`/`p50`, not a total, so it is not used here.
    """
    if router_log is None:
        return None
    events, _ = router_stats.read_since(router_log, 0)
    rows = [ev for ev in router_stats.for_agent(events, agent_id)
            if ev.get("kind") == "stats"]
    return sum(ev["output_tokens"] for ev in rows) if rows else None


def _transcript_tokens(transcript) -> int | None:
    """The agent's output tokens from its own transcript; None with nothing readable.

    A stopped agent's transcript keeps its partial turns (the design's Part C
    assumption, pinned by test_agent_caps_check's fake-agent test), so a cut-off
    final turn still counts.
    """
    if transcript is None:
        return None
    try:
        records = transcript_tail.read_records(transcript)
    except OSError:
        return None
    tokens = transcript_usage.summarize(records).get("output_tokens")
    # 0 / absent means the transcript reports no usage at all — the same rule as
    # `transcript_usage.token_total`, so the caller falls back to the note.
    return tokens if isinstance(tokens, int) and tokens > 0 else None


def check(role, agent_id, started, *, transcript=None, router_log=None, now=None,
          warned=False, scale=1.0) -> tuple[str, list]:
    """(verdict, notes) for one cheap agent: span from `started`, tokens from the
    router log when it has rows for this agent, else from the transcript.

    Neither source gives tokens: the token axis is skipped and one
    `no-tokens: <role> <agent>` note says so. `router_log=None` means no router
    log at all; a missing file reads as no rows. Never raises on a bad input file.
    """
    span_s = max(0.0, float(now if now is not None else time.time()) - float(started))
    tokens = _router_tokens(router_log, agent_id)
    if tokens is None:
        tokens = _transcript_tokens(transcript)
    notes = [] if tokens is not None else [f"{NO_TOKENS_NOTE}: {role} {agent_id}"]
    # A skipped token axis is 0 tokens — under every row's soft token cap — so the
    # one `verdict()` decides the span axis alone.
    return verdict(role, span_s, tokens if tokens is not None else 0, warned, scale), notes


def _partial_findings(text):
    """The findings list in a partial reply, or None when it is not parseable.

    Bare JSON or one ```json fence, as `escape_ledger._parse_reply` reads a reply;
    here a dict without a `findings` list is unparsable too — a capped agent's
    reply is kept as prose rather than dropped.
    """
    if not isinstance(text, str):
        return None
    candidates = [text] + [m.strip() for m in reversed(
        re.findall(r"```json\s*(.*?)```", text, re.S))]
    for cand in candidates:
        try:
            obj = json.loads(cand)
        except ValueError:
            continue
        if isinstance(obj, dict) and isinstance(obj.get("findings"), list):
            return obj["findings"]
    return None


def partial_path(reply_path) -> Path:
    """`R.partial.ndjson` beside a reply path `R` — the finder's delivered findings."""
    return Path(str(reply_path) + ".partial.ndjson")


def _json_obj(line):
    """json.loads(line) when it parses to a JSON object, else None."""
    try:
        obj = json.loads(line)
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None


def harvest(text) -> list:
    """Every `FINDING {json}` object in `text`, as JSON strings; JSONL transcript lines
    expand to their assistant text, so inline deliveries survive a mid-turn stop."""
    scan = [text] + [b.get("text", "") for line in text.splitlines() if (rec := _json_obj(line))
                     for b in (rec.get("message") or {}).get("content") or []
                     if isinstance(b, dict) and isinstance(b.get("text"), str)]
    out, dec = [], json.JSONDecoder()
    for body in scan:
        i = -1
        while (i := body.find(FINDING_MARK, i + 1)) >= 0:
            try:
                obj, i = dec.raw_decode(body, i + len(FINDING_MARK))
                if isinstance(obj, dict):
                    out.append(json.dumps(obj, sort_keys=True))
            except ValueError:
                i += len(FINDING_MARK)
    return out


def put_capped(reply_path, text, *, partial_lines=None) -> list:
    """Write a capped agent's partial reply to `reply_path`, every finding marked
    `"capped": true`. Delivered findings (`partial_lines`, else the sidecar) win over
    its reply text; an unparsable partial with none becomes one capped prose finding."""
    raw = _partial_findings(text)
    if raw is None and partial_lines is not None:
        raw = [o for o in map(_json_obj, partial_lines) if o] or None
    if raw is None:
        findings = [{"text": text if isinstance(text, str) else "", CAP_FIELD: True}]
    else:
        findings = [{**f, CAP_FIELD: True} if isinstance(f, dict)
                    else {"text": str(f), CAP_FIELD: True} for f in raw]
    path = Path(reply_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"findings": findings}, sort_keys=True) + "\n",
                    encoding="utf-8")
    return findings


def ledger_row(role, engine, design, span_s, output_tokens) -> dict:
    """One escape-ledger row for a capped agent.

    `kept` is unknown at cap time — the Opus check step back-fills it through
    `escape_ledger` (Task 3.4) — so it is written as null. There is no
    `disposition`: a cap row is not a finding disposition, and
    `escape_ledger.report` counts it under its role's `capped` key.
    """
    cap_for(role)  # only a cheap role with a cap row can be capped this way
    return {"role": role, "engine": engine, "design": design, "span_s": span_s,
            "output_tokens": output_tokens, CAP_FIELD: True, "kept": None}


def _started_epoch(value) -> float:
    """`--started` as epoch seconds: a number, or an ISO local wall time."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return datetime.datetime.fromisoformat(str(value)).timestamp()


def _args(argv) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="agent_caps.py")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--role", required=True)
    c.add_argument("--agent-id", dest="agent_id", required=True)
    c.add_argument("--started", required=True)
    c.add_argument("--transcript")
    c.add_argument("--router-log", dest="router_log")
    c.add_argument("--now", type=float)
    c.add_argument("--warned", action="store_true")
    c.add_argument("--scale", type=float, default=1.0,
                   help="span-axis fraction of the cap (a review segment's deadline_fraction)")
    pc = sub.add_parser("put-capped")
    pc.add_argument("--reply-path", dest="reply_path", required=True)
    pc.add_argument("--partial")
    pc.add_argument("--from-transcript", dest="from_transcript")
    pp = sub.add_parser("put-partial")
    pp.add_argument("--reply-path", dest="reply_path", required=True)
    pp.add_argument("--finding", required=True)
    sub.add_parser("budget-line")
    sub.add_parser("wrap-up-message")
    return p.parse_args(argv)


def main(argv=None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    if argv[:1] in (["spawned"], ["watch"]):  # the watch loop's CLI (Task 7.3)
        import agent_caps_watch  # lazy: agent_caps_watch imports this module
        return agent_caps_watch.main(argv)
    a = _args(argv)
    if a.cmd in ("budget-line", "wrap-up-message"):  # the driver's text for the agent
        print(BUDGET_LINE if a.cmd == "budget-line" else WRAP_UP_MESSAGE)
        return 0
    if a.cmd == "put-partial":
        if (obj := _json_obj(a.finding)) is None:
            print("agent_caps: put-partial: --finding must be a JSON object", file=sys.stderr)
            return 2
        side = partial_path(a.reply_path)
        side.parent.mkdir(parents=True, exist_ok=True)
        with side.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(obj, sort_keys=True) + "\n")
        return 0
    if a.cmd == "put-capped":
        try:
            text = Path(a.partial).read_text(encoding="utf-8") if a.partial else ""
            side = partial_path(a.reply_path)
            lines = (harvest(Path(a.from_transcript).read_text(encoding="utf-8"))
                     if a.from_transcript else side.read_text(encoding="utf-8").splitlines()
                     if side.exists() else None)
        except (OSError, UnicodeDecodeError) as exc:
            print(f"agent_caps: cannot read partial reply: {exc}", file=sys.stderr)
            return 1
        put_capped(a.reply_path, text, partial_lines=lines)
        return 0
    try:
        v, notes = check(a.role, a.agent_id, _started_epoch(a.started),
                         transcript=a.transcript,
                         router_log=a.router_log or router_stats.log_path(os.environ),
                         now=a.now, warned=a.warned, scale=a.scale)
    except (KeyError, ValueError, OSError) as exc:
        print(f"agent_caps: check: {exc}", file=sys.stderr)
        return 2
    print(v)
    if v == WRAP_UP:  # the one note the driver logs (and messages the agent with)
        print(f"soft-cap: {a.role} {a.agent_id}")
    for note in notes:
        print(note)
    return 0


if __name__ == "__main__":
    sys.exit(main())
