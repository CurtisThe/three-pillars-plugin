#!/usr/bin/env python3
"""transcript_usage.py — the one usage parser over a Claude Code JSONL transcript.

design: task-worker-sonnet (task 1.2)

Claude Code writes one JSONL record per streamed event; one message's records share
`message.id` (fallback `requestId`). A streaming reply has a usage *snapshot* record
(no `stop_reason`) and a *final* record (`stop_reason`, or `output_tokens_details`);
the final record's usage may be partial (e.g. `output_tokens` only), so per message
each usage field takes the last final record's value where that record has it, else
the max over the message's snapshots. `summarize` sums the four usage fields across
messages, carries `thinking_tokens` (a breakdown already inside `output_tokens`, never
added to it — `None` when no record reports it) and the `legacy` totals of the old
`attempt_scan._token_totals` body (moved here verbatim). Stdlib only; never raises on
bad records — garbage is skipped.
"""
from __future__ import annotations

__all__ = ["summarize", "token_total", "USAGE_FIELDS"]

USAGE_FIELDS = ("input_tokens", "cache_creation_input_tokens",
                "cache_read_input_tokens", "output_tokens")


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _message(rec: dict) -> dict:
    return rec.get("message") if isinstance(rec.get("message"), dict) else {}


def _usage(msg: dict) -> dict:
    return msg.get("usage") if isinstance(msg.get("usage"), dict) else {}


def _is_final(msg: dict) -> bool:
    return msg.get("stop_reason") is not None or "output_tokens_details" in _usage(msg)


def _groups(records: list[dict]) -> dict:
    """Assistant records grouped by `message.id` (fallback `requestId`), in first-seen order."""
    groups: dict = {}
    for rec in records:
        if not isinstance(rec, dict) or rec.get("type") != "assistant":
            continue
        msg = _message(rec)
        key = msg.get("id") or rec.get("requestId")
        if key is None:
            continue
        groups.setdefault(key, []).append(msg)
    return groups


def _pick(finals: list[dict], snaps: list[dict], getter) -> int | None:
    """The last final record's value where that record has it, else the max over the
    message's snapshots; None when neither reports a valid int.

    `getter` receives the *usage* dict (not the message).
    """
    for msg in reversed(finals):
        value = getter(_usage(msg))
        if _is_int(value):
            return value
    values = [getter(_usage(msg)) for msg in snaps]
    values = [v for v in values if _is_int(v)]
    return max(values) if values else None


def _thinking(usage: dict):
    details = usage.get("output_tokens_details")
    return details.get("thinking_tokens") if isinstance(details, dict) else None


def _token_totals(records: list[dict]) -> dict:
    per_turn: dict = {}
    for rec in records:
        if rec.get("type") != "assistant":
            continue
        msg = rec.get("message") if isinstance(rec.get("message"), dict) else {}
        key = msg.get("id") or rec.get("requestId")
        if key is None:
            continue
        usage = msg.get("usage") if isinstance(msg.get("usage"), dict) else {}
        cur = per_turn.setdefault(key, {"input": 0, "output": 0})
        for field, src in (("input", "input_tokens"), ("output", "output_tokens")):
            v = usage.get(src)
            if isinstance(v, int) and not isinstance(v, bool):
                cur[field] = max(cur[field], v)
    return {"input": sum(t["input"] for t in per_turn.values()),
            "output": sum(t["output"] for t in per_turn.values())}


def summarize(records: list[dict]) -> dict:
    """Per-message usage with the cache breakdown, `source` marker, and legacy totals."""
    groups = _groups(records)
    totals = {field: 0 for field in USAGE_FIELDS}
    totals["thinking_tokens"] = None
    reported = False
    final_messages = 0
    for msgs in groups.values():
        finals = [m for m in msgs if _is_final(m)]
        snaps = [m for m in msgs if not _is_final(m)]
        final_messages += 1 if finals else 0
        for field in USAGE_FIELDS:
            value = _pick(finals, snaps, lambda usage, f=field: usage.get(f))
            if _is_int(value):
                totals[field] += value
        thinking = _pick(finals, snaps, _thinking)
        if _is_int(thinking):
            reported = True
            totals["thinking_tokens"] = (totals["thinking_tokens"] or 0) + thinking
    messages = len(groups)
    if messages == 0:
        source = None
    elif final_messages == messages:
        source = "final"
    elif final_messages == 0:
        source = "message_start"
    else:
        source = "mixed"
    return {
        **totals,
        "fresh_tokens": totals["input_tokens"] + totals["cache_creation_input_tokens"]
                        + totals["output_tokens"],
        "thinking_tokens": totals["thinking_tokens"] if reported else None,
        "messages": messages,
        "final_messages": final_messages,
        "source": source,
        "legacy": _token_totals(records) if records else {"input": 0, "output": 0},
    }


def token_total(value) -> int | None:
    """The one row-total rule: a dict with `source` gives `input + cache_write + output`;
    a legacy `{input, output}` dict their sum; a positive int itself. Anything else —
    including 0 or a dict summing to 0 — gives None."""
    if isinstance(value, dict):
        keys = ("input", "cache_write", "output") if "source" in value else ("input", "output")
        total = sum(v for v in (value.get(k) for k in keys) if _is_int(v))
        return total if total > 0 else None
    if _is_int(value) and value > 0:
        return value
    return None
