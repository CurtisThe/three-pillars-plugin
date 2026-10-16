#!/usr/bin/env python3
"""run_cost.py — what a design run cost, per role, at API-equivalent prices.

design: strata-spend-leaks (Task 3.3). The seat's cost scripts were never kept, so
this is the kept one: read the orchestrator's transcript plus its subagents' and
answer "what did this run cost, and where did it go". The prices are the design's
seed weights — Opus $5 in / $25 out per Mtok, Sonnet $3 / $15; a 5-minute cache
write 1.25x input, a 1-hour write 2x, a cache read 0.1x input. A non-Claude family
(Strata, any `local-*` rung, `qwen*`) is $0 — the GPU is already paid for — so the
total is what the run *would* cost on the API, comparable to the fable-escalation
#272 baseline ($238, 35 tasks). Money is exact `fractions.Fraction` arithmetic and
becomes a float only in the returned dict, so 1M Opus input is exactly $5.00, not
a float wobble. `reader` and `role_of` are the injectable seams. Stdlib only.
CLI: `run_cost.py <main.jsonl> [--subagents DIR] [--json]`.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path

import model_policy
import transcript_tail
import wait_budget

__all__ = ["PRICES", "MTOK", "CACHE_TTL_S", "ORCHESTRATOR", "message_cost",
           "expiry_waste", "breakdown", "role_of_transcript", "subagent_paths", "main"]

MTOK = 1_000_000
CACHE_TTL_S = wait_budget.CACHE_TTL_S  # the prompt cache whose lapse costs a rewrite
ORCHESTRATOR = "orchestrator"          # the main transcript's role

# family -> ($ per Mtok input, $ per Mtok output); the cache weights are multiples of
# the input price. A Claude family with no row counts $0 and names itself in `unpriced`.
PRICES = {"opus": (Fraction(5), Fraction(25)), "sonnet": (Fraction(3), Fraction(15))}
CACHE_WRITE = Fraction(5, 4)      # 1.25x input — the 5-minute write
CACHE_1H_EXTRA = Fraction(3, 4)   # a 1-hour write is 2x: the 1.25x plus this
CACHE_READ = Fraction(1, 10)      # 0.1x input
USAGE_FIELDS = ("input_tokens", "cache_creation_input_tokens",
                "cache_read_input_tokens", "output_tokens")


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _usage(msg: dict) -> dict:
    return msg["usage"] if isinstance(msg.get("usage"), dict) else {}


def _field(usage, name: str) -> int:
    value = usage.get(name) if isinstance(usage, dict) else None
    return value if _is_int(value) else 0


def _price(model):
    """The family's `PRICES` row; None when `model` is not a priced Claude."""
    return PRICES.get(model_policy.agent_alias(model))


def _write_split(usage: dict) -> tuple[int, int]:
    """(cache-write tokens, of those the 1-hour ones): `usage.cache_creation.
    ephemeral_1h_input_tokens` breaks the 1-hour portion out when the transcript
    reports it, else the whole write is a 5-minute write, clamped to its whole."""
    total = _field(usage, "cache_creation_input_tokens")
    one_hour = _field(usage.get("cache_creation"), "ephemeral_1h_input_tokens")
    return total, min(one_hour, total)


def _turn_cost(model, usage) -> Fraction:
    """Exact dollars for one turn's `usage`; $0 for a model outside `PRICES` (a
    local family, or a Claude family with no row)."""
    price = _price(model)
    if price is None or not isinstance(usage, dict):
        return Fraction(0)
    write_total, one_hour = _write_split(usage)
    inside = (_field(usage, "input_tokens")
              + CACHE_READ * _field(usage, "cache_read_input_tokens")
              + CACHE_WRITE * write_total + CACHE_1H_EXTRA * one_hour)
    return (price[0] * inside + price[1] * _field(usage, "output_tokens")) / MTOK


def message_cost(model, usage) -> float:
    """Dollars for one assistant turn's `usage` — the public face of `_turn_cost`."""
    return float(_turn_cost(model, usage))


def _is_final(msg: dict) -> bool:
    return msg.get("stop_reason") is not None or "output_tokens_details" in _usage(msg)


def _pick(msgs: list[dict], name: str) -> int:
    """`transcript_usage`'s rule: the last final record's value for `name` where one
    has it, else the max over the snapshots — a streamed reply counts once."""
    for msg in reversed([m for m in msgs if _is_final(m)]):
        value = _usage(msg).get(name)
        if _is_int(value):
            return value
    values = [_usage(m).get(name) for m in msgs if not _is_final(m)]
    values = [v for v in values if _is_int(v)]
    return max(values) if values else 0


def _stamp(value):
    """An ISO-8601 record timestamp as an aware datetime, else None."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _turns(records: list[dict]) -> list[dict]:
    """Assistant records grouped by `message.id` (fallback `requestId`), first-seen
    order — one group, one reply. Each turn is {model, usage, ts} for that reply."""
    groups: dict = {}
    for index, rec in enumerate(records):
        if not isinstance(rec, dict) or rec.get("type") != "assistant":
            continue
        msg = rec["message"] if isinstance(rec.get("message"), dict) else {}
        turn = groups.setdefault(msg.get("id") or rec.get("requestId") or f"#{index}",
                                 {"msgs": [], "models": [], "ts": None})
        turn["msgs"].append(msg)
        if isinstance(msg.get("model"), str):
            turn["models"].append(msg["model"])
        turn["ts"] = _stamp(rec.get("timestamp")) or turn["ts"]
    turns = []
    for turn in groups.values():
        usage = {name: _pick(turn["msgs"], name) for name in USAGE_FIELDS}
        # the last record of the turn reporting the 5m/1h split, if any
        msgs = reversed(turn["msgs"])
        detail = next((d for d in (_usage(m).get("cache_creation") for m in msgs)
                       if isinstance(d, dict)), None)
        if detail is not None:
            usage["cache_creation"] = detail
        turns.append({"model": turn["models"][-1] if turn["models"] else "",
                      "usage": usage, "ts": turn["ts"]})
    return turns


def _waste(turns: list[dict]) -> Fraction:
    """Cache writes that re-wrote a prefix whose TTL had already lapsed.

    A turn starting more than `CACHE_TTL_S` after the previous one woke to an
    expired cache, so its whole write paid again for tokens already paid for —
    the dispatcher's over-TTL waits, priced. A local model's rewrite is not Claude
    spend, so it is not waste."""
    total, prev = Fraction(0), None
    for turn in turns:
        price = _price(turn["model"])
        if price is not None and prev is not None and turn["ts"] is not None:
            if (turn["ts"] - prev).total_seconds() > CACHE_TTL_S:
                write_total, one_hour = _write_split(turn["usage"])
                total += (price[0] * (CACHE_WRITE * write_total
                                      + CACHE_1H_EXTRA * one_hour)) / MTOK
        if turn["ts"] is not None:
            prev = turn["ts"]
    return total


def expiry_waste(records: list[dict]) -> float:
    """Dollars of cache-expiry re-write in one transcript (see `_waste`)."""
    return float(_waste(_turns(records)))


def role_of_transcript(path) -> str:
    """A subagent's role: its sibling `.meta.json`'s `agentType` when present, else
    the transcript's file stem."""
    p = Path(path)
    try:
        meta = json.loads((p.parent / (p.stem + ".meta.json")).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        meta = None
    agent_type = meta.get("agentType") if isinstance(meta, dict) else None
    if isinstance(agent_type, str) and agent_type.strip():
        return agent_type.strip()
    return p.stem


def subagent_paths(directory) -> list:
    """Every `*.jsonl` under `directory`, sorted; [] when it is unreadable."""
    try:
        return sorted(Path(directory).glob("*.jsonl"))
    except OSError:
        return []


def breakdown(main_path, subagent_paths=(), *, reader=transcript_tail.read_records,
              role_of=role_of_transcript) -> dict:
    """`{total, roles, cache_expiry_waste, turns, unpriced}` for one run.

    The main transcript is role `orchestrator`; each subagent's role comes from
    `role_of` (its agent type, else its file stem) — same-role transcripts share one
    bucket. `reader(path)` is the injectable transcript seam. `unpriced` names the
    Claude families seen with no `PRICES` row: counted at $0, but said out loud."""
    roles: dict = {ORCHESTRATOR: Fraction(0)}
    waste, turns, unpriced = Fraction(0), 0, set()
    for role, path in [(ORCHESTRATOR, main_path)] + [(role_of(p), p) for p in subagent_paths]:
        turn_list = _turns(reader(path))
        turns += len(turn_list)
        for turn in turn_list:
            family = model_policy.agent_alias(turn["model"])
            if family is not None and family not in PRICES:
                unpriced.add(family)
            roles[role] = roles.get(role, Fraction(0)) + _turn_cost(turn["model"], turn["usage"])
        waste += _waste(turn_list)
    return {"total": float(sum(roles.values())),
            "roles": {r: float(v) for r, v in roles.items()},
            "cache_expiry_waste": float(waste), "turns": turns,
            "unpriced": sorted(unpriced)}


def main(argv=None) -> int:
    """Print the breakdown for `<main.jsonl>` (+ `--subagents DIR`); `--json` raw."""
    ap = argparse.ArgumentParser(prog="run_cost.py",
                                 description="Per-run cost at API-equivalent prices.")
    ap.add_argument("main_transcript", help="the orchestrator's transcript (.jsonl)")
    ap.add_argument("--subagents", help="a directory of subagent transcripts")
    ap.add_argument("--json", action="store_true", help="print the breakdown as JSON")
    args = ap.parse_args(argv)
    paths = subagent_paths(args.subagents) if args.subagents else []
    try:
        result = breakdown(args.main_transcript, paths)
    except OSError as exc:  # a missing transcript is said, never a traceback
        print(f"run cost: unreadable transcript — {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    print(f"run cost: ${result['total']:.2f} over {result['turns']} turns")
    for role, cost in sorted(result["roles"].items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"  {role}: ${cost:.2f}")
    print(f"  cache-expiry waste: ${result['cache_expiry_waste']:.2f}")
    if result["unpriced"]:
        print("  unpriced Claude families (counted $0): " + ", ".join(result["unpriced"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
