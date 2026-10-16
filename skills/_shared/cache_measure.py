#!/usr/bin/env python3
"""cache_measure.py — what a run's prompt cache cost, per agent type.

design: prompt-cache-aware-dispatch (Task 1.2, Behavior 5)

The 10-15 run lost 1.38M cache-write tokens to one `tp-worker` dispatcher waiting
past the 300 s prompt cache between its own task calls: every wake re-wrote a
prefix already paid for. This is the measurement that finding came from — read a
run's main transcript(s) and its subagents' and answer, per agent type, how many
turns it took, how much it read from the cache, how much it wrote, how many of
its turns started more than `wait_budget.CACHE_TTL_S` after the previous one and
how much cache write those gaps paid for. The turn grouping and the agent type
come from `run_cost` (a streamed reply counts once; the type is the sibling
`.meta.json`'s `agentType`), so the two scripts never disagree about what a turn
is. Nothing here prices anything — tokens only; `run_cost.py` does money.
`reader` and `role_of` are the injectable seams. Stdlib only.
CLI: `cache_measure.py [--project-dir DIR | --cwd DIR --config-dir DIR]
[--line] [--append PATH]`.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

import run_cost
import transcript_tail
import wait_budget

__all__ = ["MTOK", "LINE_PREFIX", "NO_TRANSCRIPTS", "measure", "run_paths",
           "project_dir", "format_line", "append_line", "main"]

MTOK = 1_000_000
LINE_PREFIX = "[cache] "
NO_TRANSCRIPTS = "cache: no transcripts"
FIELDS = ("turns", "cache_read", "cache_write", "gaps_over_ttl", "gap_cache_write")


def _tokens(usage, name: str) -> int:
    """One usage field as an int; 0 when absent or not a number."""
    value = usage.get(name) if isinstance(usage, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _over_ttl(turns: list[dict]) -> tuple[int, int]:
    """(turns starting over the TTL after the previous one, their cache write).

    A gap is per transcript: the previous timestamped turn of the *same* transcript,
    never another role's. Exactly `CACHE_TTL_S` later is still inside the cache."""
    gaps, write, prev = 0, 0, None
    for turn in turns:
        if turn["ts"] is None:
            continue
        if prev is not None and (turn["ts"] - prev).total_seconds() > wait_budget.CACHE_TTL_S:
            gaps += 1
            write += _tokens(turn["usage"], "cache_creation_input_tokens")
        prev = turn["ts"]
    return gaps, write


def measure(main_paths, sub_paths, *, reader=transcript_tail.read_records,
            role_of=run_cost.role_of_transcript) -> dict:
    """`{role: {turns, cache_read, cache_write, gaps_over_ttl, gap_cache_write}}`.

    Each main transcript is role `run_cost.ORCHESTRATOR`; each subagent's role is
    its agent type (`role_of`) — same-role transcripts share one bucket, so N
    `tp-worker` subagents report as one dispatcher population. A transcript that
    cannot be opened is skipped, never fatal: a run whose transcripts are
    half-written still measures."""
    roles: dict = {}
    buckets = ([(run_cost.ORCHESTRATOR, p) for p in main_paths]
               + [(role_of(p), p) for p in sub_paths])
    for role, path in buckets:
        try:
            turns = run_cost._turns(reader(path))
        except OSError:
            continue
        bucket = roles.setdefault(role, {name: 0 for name in FIELDS})
        bucket["turns"] += len(turns)
        for turn in turns:
            bucket["cache_read"] += _tokens(turn["usage"], "cache_read_input_tokens")
            bucket["cache_write"] += _tokens(turn["usage"], "cache_creation_input_tokens")
        gaps, gap_write = _over_ttl(turns)
        bucket["gaps_over_ttl"] += gaps
        bucket["gap_cache_write"] += gap_write
    return roles


def run_paths(directory) -> tuple[list, list]:
    """The run's (main transcripts, subagent transcripts) under `directory`."""
    base = Path(directory)
    try:
        mains = sorted(base.glob("*.jsonl"))
        subs = sorted(base.glob("*/subagents/*.jsonl"))
    except OSError:
        return [], []
    return mains, subs


def project_dir(cwd, config_dir) -> Path:
    """Claude Code's transcript dir for `cwd`: `<config>/projects/<path, non-alnum -> '-'>`."""
    return Path(config_dir) / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(cwd))


def _mtok(tokens: int) -> str:
    """Tokens as millions, 2 decimals — the scale these numbers live at."""
    return f"{tokens / MTOK:.2f}M"


def format_line(result: dict) -> str:
    """One line for the whole run: the richest role first, no newlines.

    The shape `/tp-design-learn` appends to `decisions.md`, so a run's cache
    profile is one grep away in its own design log."""
    if not result:
        return NO_TRANSCRIPTS
    segments = []
    ordered = sorted(result.items(), key=lambda kv: (-kv[1]["cache_write"], kv[0]))
    for role, stats in ordered:
        segments.append(
            f"{role} turns={stats['turns']} read={_mtok(stats['cache_read'])}"
            f" write={_mtok(stats['cache_write'])}"
            f" gaps>{wait_budget.CACHE_TTL_S}s={stats['gaps_over_ttl']}"
            f" gap_write={_mtok(stats['gap_cache_write'])}")
    return LINE_PREFIX + "; ".join(segments)


def append_line(path, line: str) -> None:
    """Append `line` to `path`, creating a missing file.

    `/tp-design-learn` calls this with the one line `format_line` produced, so a
    design log ends with its own run's cache profile. A file that ends mid-line
    gets its newline first, so the appended line stays a line of its own."""
    target = Path(path)
    existing = target.read_text(encoding="utf-8") if target.exists() else ""
    sep = "" if not existing or existing.endswith("\n") else "\n"
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(f"{sep}{line}\n")


def main(argv=None) -> int:
    """Measure the run in `--project-dir`, or in the project dir for `--cwd`."""
    ap = argparse.ArgumentParser(prog="cache_measure.py",
                                 description="Per-agent-type cache read/write and over-TTL gaps.")
    ap.add_argument("--project-dir", help="a run's transcript dir, already slugged")
    ap.add_argument("--cwd", default=os.getcwd(), help="the run's worktree (default: here)")
    ap.add_argument("--config-dir", help="the config dir (default: $CLAUDE_CONFIG_DIR or ~/.claude)")
    ap.add_argument("--line", action="store_true", help="print the one `[cache]` line")
    ap.add_argument("--append", metavar="PATH",
                    help="print the line and append it to PATH (a design's decisions.md)")
    args = ap.parse_args(argv)
    config = args.config_dir or os.environ.get("CLAUDE_CONFIG_DIR") or str(Path.home() / ".claude")
    directory = Path(args.project_dir) if args.project_dir else project_dir(args.cwd, config)
    result = measure(*run_paths(directory))
    if args.append:
        line = format_line(result)
        print(line)
        append_line(args.append, line)
        return 0
    if args.line or not result:
        print(format_line(result))
        return 0
    for role, stats in sorted(result.items(), key=lambda kv: (-kv[1]["cache_write"], kv[0])):
        print(f"{role}: turns={stats['turns']} cache_read={stats['cache_read']}"
              f" cache_write={stats['cache_write']}"
              f" gaps>{wait_budget.CACHE_TTL_S}s={stats['gaps_over_ttl']}"
              f" gap_write={stats['gap_cache_write']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
