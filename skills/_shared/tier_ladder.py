#!/usr/bin/env python3
"""tier_ladder.py — the per-task retry/escalation state machine (explicit total table).

design: local-implement-and-review (Behaviors 4, 6, 7)

A task climbs ``local`` → ``sonnet`` → ``opus``. ``next_step(record, outcome, cfg)`` is
pure: it returns ``(action, tier, record')`` with an updated copy. ``attempts[tier]``
counts attempts that ran (``PASS``/``PASS-unverified``/``FAIL``), never ``unavailable``,
``env-error`` or a cheap rung's ``FAIL`` ``no oracle`` (deterministic: a retry cannot fix
it, so it escalates at once like ``unavailable``); ``N = 1 + max_retries`` per cheap rung.

| tier         | outcome              | condition              | action                    |
|--------------|----------------------|------------------------|---------------------------|
| any          | PASS/PASS-unverified | —                      | done (/-unverified)       |
| local/sonnet | FAIL                 | attempts < N           | retry, same tier          |
| local/sonnet | FAIL                 | attempts == N, escalate| escalate next rung        |
| local/sonnet | FAIL                 | attempts == N, no esc. | blocked                   |
| local/sonnet | unavailable          | escalate / not         | escalate / blocked        |
| local/sonnet | FAIL ``no oracle``   | escalate / not         | escalate / blocked        |
| opus         | FAIL                 | —                      | blocked (one inline try)  |
| opus         | unavailable          | —                      | ValueError (unreachable)  |
| any          | env-error            | —                      | halt (final env-error)    |

``model_for`` maps a tier to the spawn model from config; ``None`` for ``opus`` means the
dispatcher does the task inline in an attempt worktree. CLI (the record is a JSON file
carried across dispatcher turns): ``start --task ID --tier T --record R``; ``next --record R
--outcome O [--root .]`` rewrites R and prints ``{action, tier, model}``; ``entry`` /
``telemetry --record R``. ``entry --record -`` reads a ``telemetry.task_tiers[]`` item on
stdin (the orchestrator's full-design ``[tier]`` entry). A usage error or a final record
exits 2. Stdlib only.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from pathlib import Path

_SHARED = str(Path(__file__).resolve().parent)
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

import local_implement_config  # noqa: E402 — in-repo, stdlib-only sibling

LADDER = ("local", "sonnet", "opus")
OUTCOMES = ("PASS", "PASS-unverified", "FAIL", "unavailable", "env-error")
_DONE = {"PASS": "done", "PASS-unverified": "done-unverified"}
NO_ORACLE = "no oracle"  # task_verify's cheap-rung reason prefix (no runnable Test)


def model_for(tier: str, cfg: dict) -> str | None:
    """The model a rung spawns with: ``cfg["model"]`` / ``cfg["fallback_model"]`` / None."""
    if tier == "local":
        return cfg["model"]
    if tier == "sonnet":
        return cfg["fallback_model"]
    if tier == "opus":
        return None
    raise ValueError(f"unknown tier {tier!r}; expected one of {LADDER}")


def start(task_id: str, tier: str) -> dict:
    """A fresh ladder record for ``task_id`` starting at ``tier``."""
    if tier not in LADDER:
        raise ValueError(f"unknown tier {tier!r}; expected one of {LADDER}")
    return {"task_id": str(task_id), "tier_path": [tier], "attempts": {tier: 0},
            "escalated": False, "final": None, "verdicts": [], "tokens": None}


def _escalate(rec: dict, tier: str) -> tuple[str, str, dict]:
    up = LADDER[LADDER.index(tier) + 1]
    rec["tier_path"].append(up)
    rec["attempts"][up] = 0
    rec["escalated"] = True
    return "escalate", up, rec


def _finish(rec: dict, action: str, final: str) -> tuple[str, None, dict]:
    rec["final"] = final
    return action, None, rec


def next_step(record: dict, outcome: str, cfg: dict, *, reason: str = "",
              red_at_base: str | None = None) -> tuple[str, str | None, dict]:
    """→ ``(action, tier, record')``; ``action`` ∈ done|retry|escalate|blocked|halt.

    ``tier`` is the rung to run next (retry/escalate), else None. ``record`` is never
    mutated. ``reason`` (the check's reason) is kept in ``verdicts``; ``red_at_base``,
    when given, is recorded for the ``[tier]`` entry.
    """
    if outcome not in OUTCOMES:
        raise ValueError(f"unknown outcome {outcome!r}; expected one of {OUTCOMES}")
    if record.get("final"):
        raise ValueError(f"task {record.get('task_id')} is already final: {record['final']}")
    rec = copy.deepcopy(record)
    tier = rec["tier_path"][-1]
    if tier == "opus" and outcome == "unavailable":
        raise ValueError("opus is the dispatcher itself: it cannot be unavailable")
    rec["verdicts"].append({"tier": tier, "outcome": outcome, "reason": reason})
    if red_at_base is not None:
        rec["red_at_base"] = red_at_base
    if outcome == "env-error":
        return _finish(rec, "halt", "env-error")
    no_oracle = outcome == "FAIL" and tier != "opus" and reason.startswith(NO_ORACLE)
    if outcome != "unavailable" and not no_oracle:
        rec["attempts"][tier] = rec["attempts"].get(tier, 0) + 1
    if outcome in _DONE:
        return _finish(rec, "done", _DONE[outcome])
    if tier == "opus":
        return _finish(rec, "blocked", "blocked")
    if outcome == "FAIL" and not no_oracle and rec["attempts"][tier] < 1 + int(
            cfg["max_retries"]):
        return "retry", tier, rec
    if cfg["escalate"]:
        return _escalate(rec, tier)
    return _finish(rec, "blocked", "blocked")


# --- `[tier]` decision entry and telemetry -------------------------------------------

def _count(n: int) -> str:
    return f"{n} attempt" + ("" if n == 1 else "s")


def to_decision_entry(record: dict) -> str:
    """The ``### [tier] {task_id} — {final}`` block for ``decisions.md``: tier path,
    attempts per rung (an ``unavailable`` rung shows ``0 attempts``), verdict reasons,
    ``red_at_base``, and tokens when known."""
    attempts = record.get("attempts") or {}
    verdicts = "; ".join(
        f"{v['tier']} {v['outcome']}" + (f" ({v['reason']})" if v.get("reason") else "")
        for v in record.get("verdicts") or []
    ) or "; ".join(record.get("outcomes") or []) or "none"  # a telemetry item: outcomes only
    lines = [
        f"### [tier] {record['task_id']} — {record.get('final') or 'pending'}",
        f"**Tier path**: {' → '.join(record.get('tier_path') or [])}",
        "**Attempts**: " + ", ".join(f"{t}: {_count(int(attempts.get(t, 0)))}"
                                     for t in record.get("tier_path") or []),
        f"**Verdicts**: {verdicts}",
        f"**Red-at-base**: {record.get('red_at_base') or 'n/a'}",
    ]
    if record.get("tokens") is not None:
        lines.append(f"**Tokens**: {record['tokens']}")
    return "\n".join(lines) + "\n"


_REASON_CHARS = 200  # a check reason is one line; the tail never rides in telemetry


def to_telemetry(record: dict) -> dict:
    """One flat telemetry record per task (a copy; never a view of ``record``). It keeps
    ``verdicts [{tier, outcome, reason}]`` so the orchestrator's ``[tier]`` entry renders
    the same rung-labelled verdicts as the interactive one."""
    return {
        "task_id": record["task_id"], "final": record.get("final"),
        "tier_path": list(record.get("tier_path") or []),
        "attempts": dict(record.get("attempts") or {}),
        "escalated": bool(record.get("escalated")),
        "outcomes": [v["outcome"] for v in record.get("verdicts") or []],
        "verdicts": [{"tier": v.get("tier"), "outcome": v.get("outcome"),
                      "reason": str(v.get("reason") or "")[:_REASON_CHARS]}
                     for v in record.get("verdicts") or []],
        "red_at_base": record.get("red_at_base"), "tokens": record.get("tokens"),
    }


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


def _cmd(args) -> str:
    if args.record == "-" and args.cmd not in ("entry", "telemetry"):
        raise ValueError(f"--record - (stdin) is read-only; {args.cmd} rewrites the record")
    if args.cmd == "start":
        record = start(args.task, args.tier)
        _write(args.record, record)
        return json.dumps(record, indent=2, sort_keys=True)
    record = _read(args.record)
    if args.cmd == "entry":
        return to_decision_entry(record).rstrip("\n")
    if args.cmd == "telemetry":
        return json.dumps(to_telemetry(record), indent=2, sort_keys=True)
    cfg = local_implement_config.load(args.root) or dict(local_implement_config.DEFAULTS)
    action, tier, record = next_step(record, args.outcome, cfg, reason=args.reason or "",
                                     red_at_base=args.red_at_base)
    _write(args.record, record)
    model = model_for(tier, cfg) if tier else None
    return json.dumps({"action": action, "tier": tier, "model": model}, sort_keys=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Per-task tier ladder over a JSON record.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("start")
    sp.add_argument("--task", required=True)
    sp.add_argument("--tier", required=True, choices=LADDER)
    sp = sub.add_parser("next")
    sp.add_argument("--outcome", required=True, choices=OUTCOMES)
    sp.add_argument("--root", default=".", help="repo whose config is read (default: .)")
    sp.add_argument("--reason")
    sp.add_argument("--red-at-base")
    for name in ("entry", "telemetry"):
        sub.add_parser(name)
    for sp in sub.choices.values():
        sp.add_argument("--record", required=True, help="the ladder record JSON file")
    args = parser.parse_args(argv)
    try:
        print(_cmd(args))
    except (OSError, ValueError, KeyError) as exc:
        print(f"tier_ladder: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
