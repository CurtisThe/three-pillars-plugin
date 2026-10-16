#!/usr/bin/env python3
"""attempt_scan.py — locate a worker's subagent transcript; flag runaway patterns (never a stop).

design: run-throughput (Part S, runaway ceiling; Behavior 3)

`locate` finds the newest `projects/*/*/subagents/agent-<id>.jsonl` under a Claude config
dir (task 1.6). `scan` reads one transcript through `transcript_tail` and reports flags
only — the wall-clock / generation stop lives in `attempt_watchdog.py`, not here. Served-by
and generation stats are not derived here (seat finding B6, LOCAL-STATS v1); a local rung
gets those from the watchdog. Stdlib only; the CLI always exits 0.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import design_run_command  # noqa: E402
import transcript_tail  # noqa: E402
import transcript_usage  # noqa: E402

__all__ = ["locate", "scan", "THRESHOLDS"]

THRESHOLDS = {"identical_calls_total": 5, "identical_calls_consecutive": 3,
              "reverted_edits": 2, "same_test_red_cycles": 5,
              "turn_output_tokens": 24_000, "toolfree_turns": 2}


def locate(agent_id: str, config_dir: str | Path | None = None) -> Path | None:
    """The newest subagent transcript for `agent_id`, or None when absent.

    `config_dir=None` resolves through `design_run_command.resolve_config_dir`
    ($CLAUDE_CONFIG_DIR), else falls back to `~/.claude`. Newest by mtime, so a
    re-spawned agent wins over a stale same-id file.
    """
    cfg = Path(config_dir) if config_dir is not None \
        else Path(design_run_command.resolve_config_dir(os.environ)[0] or Path.home() / ".claude")
    matches = [p for p in cfg.glob(f"projects/*/*/subagents/agent-{agent_id}.jsonl") if p.is_file()]
    if not matches:
        return None
    return max(matches, key=lambda p: p.stat().st_mtime)


def _blocks(rec: dict) -> list[dict]:
    msg = rec.get("message") if isinstance(rec.get("message"), dict) else {}
    content = msg.get("content")
    return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []


def _tool_calls(records: list[dict]) -> list[dict]:
    """`{id, name, input, key, index}` for each `tool_use` block, in stream order."""
    calls = []
    for i, rec in enumerate(records):
        if rec.get("type") != "assistant":
            continue
        for b in _blocks(rec):
            if b.get("type") == "tool_use":
                inp = b.get("input") if isinstance(b.get("input"), dict) else {}
                calls.append({"id": b.get("id"), "name": b.get("name"), "input": inp,
                              "key": (b.get("name"), json.dumps(inp, sort_keys=True)),
                              "index": i})
    return calls


def _result_text(block: dict) -> str:
    c = block.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "".join(x.get("text", "") for x in c
                       if isinstance(x, dict) and isinstance(x.get("text"), str))
    return ""


def _tool_results(records: list[dict]) -> dict:
    """`tool_use_id -> result text`, from `user` records' `tool_result` blocks."""
    results = {}
    for rec in records:
        if rec.get("type") != "user":
            continue
        for b in _blocks(rec):
            if b.get("type") == "tool_result" and b.get("tool_use_id"):
                results[b["tool_use_id"]] = _result_text(b)
    return results


def _identical_calls(calls: list[dict], thresholds: dict) -> list[str]:
    """The same `(tool, input)` pair, total ≥`identical_calls_total` or ≥`identical_calls_consecutive` in a row."""
    keys = [c["key"] for c in calls]
    totals = Counter(keys)
    max_run: dict = {}
    run_key, run_len = None, 0
    for key in keys:
        run_len = run_len + 1 if key == run_key else 1
        run_key = key
        max_run[key] = max(max_run.get(key, 0), run_len)
    flags = []
    for key, cnt in totals.items():
        if cnt >= thresholds["identical_calls_total"] \
                or max_run.get(key, 0) >= thresholds["identical_calls_consecutive"]:
            flags.append(f"identical-calls {cnt}x {key[0]}")
    return flags


def _reverted_edits(calls: list[dict], thresholds: dict) -> list[str]:
    """An Edit whose `(old, new)` inverts an earlier Edit on the same path, seen ≥`reverted_edits` times."""
    edits = [c for c in calls if c["name"] == "Edit"]
    seen: list[tuple] = []
    reverts = 0
    path = None
    for e in edits:
        path = e["input"].get("file_path")
        old, new = e["input"].get("old_string"), e["input"].get("new_string")
        if any(p == path and o == new and n == old for p, o, n in seen):
            reverts += 1
        seen.append((path, old, new))
    if reverts >= thresholds["reverted_edits"]:
        return [f"reverted-edit {reverts}x {path}"]
    return []


def _same_test_red(calls: list[dict], results: dict, thresholds: dict) -> list[str]:
    """The same `FAILED <id>` in ≥`same_test_red_cycles` consecutive pytest runs, with an Edit or Write between each."""
    runs = []
    for c in calls:
        if c["name"] == "Bash" and "pytest" in str(c["input"].get("command", "")):
            ids = set(re.findall(r"FAILED (\S+)", results.get(c["id"], "")))
            runs.append({"ids": ids, "index": c["index"]})
    if not runs:
        return []
    edits_at = sorted(c["index"] for c in calls if c["name"] in ("Edit", "Write"))

    def edited_between(i1: int, i2: int) -> bool:
        return any(i1 < e < i2 for e in edits_at)

    cur_ids = runs[0]["ids"]
    cur_len = 1 if cur_ids else 0
    best_len, best_id = cur_len, next(iter(cur_ids), None)
    for prev, cur in zip(runs, runs[1:]):
        common = cur_ids & cur["ids"] if edited_between(prev["index"], cur["index"]) else set()
        cur_ids, cur_len = (common, cur_len + 1) if common else (cur["ids"], 1 if cur["ids"] else 0)
        if cur_len > best_len:
            best_len, best_id = cur_len, next(iter(cur_ids), None)
    if best_len >= thresholds["same_test_red_cycles"]:
        return [f"same-test-red {best_len}x {best_id}"]
    return []


def _reasoning_without_action(records: list[dict], thresholds: dict) -> list[str]:
    """One turn ≥`turn_output_tokens`, or ≥`toolfree_turns` tool-free assistant turns in a row before the final reply."""
    all_turns = sorted(transcript_tail.turns(records), key=lambda t: t["last_index"])
    if not all_turns:
        return []
    flags = []
    biggest = max(t["output_tokens"] for t in all_turns)
    if biggest >= thresholds["turn_output_tokens"]:
        flags.append(f"reasoning-without-action {biggest}-token turn")
    run = best = 0
    for t in all_turns[:-1]:
        run = run + 1 if not t["has_tool_use"] else 0
        best = max(best, run)
    if best >= thresholds["toolfree_turns"]:
        flags.append(f"reasoning-without-action {best}x tool-free turns")
    return flags


def _ts(rec: dict) -> float | None:
    raw = rec.get("timestamp")
    try:
        return datetime.datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp() \
            if isinstance(raw, str) else None
    except ValueError:
        return None


def _wall_s(records: list[dict]) -> float | None:
    """The transcript's first-to-last stamp span; None when it carries no stamp (never a
    fabricated 0.0: the ladder then brackets the span itself and derives ``wall_s`` from it)."""
    stamps = [t for t in (_ts(r) for r in records) if t is not None]
    return round(max(stamps) - min(stamps), 1) if stamps else None


def _iso(epoch: float) -> str:
    when = datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc)
    return when.isoformat().replace("+00:00", "Z")


def _span(records: list[dict]) -> dict:
    """The attempt's ``started_at`` / ``ended_at`` (ISO UTC): the transcript's first and
    last stamps, the same ones ``wall_s`` spans; None when it carries no stamp."""
    stamps = [t for t in (_ts(r) for r in records) if t is not None]
    return ({"started_at": _iso(min(stamps)), "ended_at": _iso(max(stamps))} if stamps
            else {"started_at": None, "ended_at": None})


def _token_totals(records: list[dict]) -> dict:
    """The final-usage breakdown from ``transcript_usage.summarize`` (cache split and
    ``thinking``), the ``source`` marker, and the legacy two-field totals for comparison."""
    s = transcript_usage.summarize(records)
    return {"input": s["input_tokens"], "output": s["output_tokens"],
            "cache_write": s["cache_creation_input_tokens"],
            "cache_read": s["cache_read_input_tokens"],
            "thinking": s["thinking_tokens"], "source": s["source"], "legacy": s["legacy"]}


def scan(path, thresholds: dict = THRESHOLDS) -> dict:
    """Flags for one transcript; never a stop signal. `{flags, tokens, wall_s, started_at,
    ended_at, turns}`,
    or `{flags: [], error}` on any read error (missing file, bad path, ...)."""
    try:
        records = transcript_tail.read_records(path)
    except OSError as exc:
        return {"flags": [], "error": str(exc)}
    calls = _tool_calls(records)
    results = _tool_results(records)
    flags = (_identical_calls(calls, thresholds) + _reverted_edits(calls, thresholds)
             + _same_test_red(calls, results, thresholds)
             + _reasoning_without_action(records, thresholds))
    return {"flags": flags, "tokens": _token_totals(records), "wall_s": _wall_s(records),
            **_span(records), "turns": len(transcript_tail.turns(records))}


def _args(argv):
    p = argparse.ArgumentParser(prog="attempt_scan.py")
    p.add_argument("cmd", choices=["scan"])
    p.add_argument("--agent-id", dest="agent_id")
    p.add_argument("--config-dir", dest="config_dir")
    p.add_argument("--path", dest="path")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = _args(argv if argv is not None else sys.argv[1:])
    path = args.path or (locate(args.agent_id, args.config_dir) if args.agent_id else None)
    if path is None:
        out = {"flags": [], "error": "attempt_scan: no --path and no transcript for --agent-id"}
    else:
        try:
            out = scan(path)
        except Exception as exc:  # noqa: BLE001 - the CLI always prints JSON, exit 0
            out = {"flags": [], "error": f"attempt_scan: {exc}"}
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
