#!/usr/bin/env python3
"""child_transcript.py — a child session's transcripts, and proof its host did one thing.

design: strata-session-isolation (child spawn; host verification)

A child session is a second `claude -p` process launched by the dispatcher; its transcripts
land under the same Claude config dir as the orchestrator's. `host_path` finds the child's
own host transcript, `inner_ids` lists the inner subagent transcripts that host spawned, and
`verify_host` proves the host made exactly one `Agent`/`Task` call for the requested
subagent and model — the shape the child spawn protocol requires. `cfg=None` resolves like
`attempt_scan.locate`: `$CLAUDE_CONFIG_DIR`, else `~/.claude`. Stdlib only; nothing here
raises past a return value. `inner_done` says whether an inner subagent's turn has ended
(the same predicate the watchdog reads), and `last_text` is what it finally said. With
`cfg=None` the lookup polls the pinned profile's dir first, then sibling profiles as the
logged fallback (`child_profile`).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Callable, Optional, TypeVar

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import attempt_scan  # noqa: E402
import child_profile  # noqa: E402
import design_run_command  # noqa: E402
import transcript_tail  # noqa: E402

__all__ = ["host_path", "inner_ids", "verify_host", "inner_done", "last_text"]

HOST_TOOLS = ("Agent", "Task")

T = TypeVar("T")


def _cfg(cfg: str | Path | None = None) -> Path:
    """The Claude config dir: `cfg` when given, else `$CLAUDE_CONFIG_DIR`, else `~/.claude`."""
    return Path(cfg) if cfg is not None \
        else Path(design_run_command.resolve_config_dir(os.environ)[0] or Path.home() / ".claude")


def _search(key: str, cfg: str | Path | None, find: Callable[[Path], Optional[T]]) -> Optional[T]:
    """The first non-empty `find(d)` over the dirs a child id should be polled in.

    An explicit `cfg` keeps today's single-dir lookup; `cfg=None` polls
    `child_profile.candidate_dirs` — the primary config dir first, then sibling profiles —
    and notes once, per (id, dir), when the win came from somewhere other than the primary.
    Never raises: a scan error in one dir reads as nothing found there.
    """
    dirs = [Path(cfg)] if cfg is not None else child_profile.candidate_dirs(_cfg())
    primary = dirs[0]
    for d in dirs:
        try:
            hit = find(d)
        except OSError:
            hit = None
        if hit:
            if d != primary:
                child_profile.note_found(key, d, primary)
            return hit
    return None


def host_path(child: str, cfg: str | Path | None = None) -> Path | None:
    """The child's host transcript `projects/*/<child>.jsonl`, or None when absent.

    Newest by mtime when more than one project dir carries the id, so a re-spawned
    session with the same id wins over a stale file.
    """
    def find(d: Path) -> Optional[Path]:
        matches = [p for p in d.glob(f"projects/*/{child}.jsonl") if p.is_file()]
        return max(matches, key=lambda p: p.stat().st_mtime) if matches else None

    return _search(child, cfg, find)


def inner_ids(child: str, cfg: str | Path | None = None) -> list[str]:
    """Sorted ids of the child host's inner subagents.

    The stems of `projects/*/<child>/subagents/agent-<id>.jsonl` — the `agent-` prefix and
    `.jsonl` suffix stripped. Empty when the host spawned nothing.
    """
    def find(d: Path) -> list[str]:
        ids = {p.name[len("agent-"):-len(".jsonl")]
               for p in d.glob(f"projects/*/{child}/subagents/agent-*.jsonl") if p.is_file()}
        return sorted(ids)

    return _search(child, cfg, find) or []


def _inner_records(agent_id: str, cfg: str | Path | None = None) -> list[dict]:
    """The inner subagent's records, or [] when its transcript is absent."""
    path = _search(agent_id, cfg, lambda d: attempt_scan.locate(agent_id, d))
    return transcript_tail.read_records(path) if path is not None else []


def inner_done(agent_id: str, cfg: str | Path | None = None) -> bool:
    """Has the inner subagent ended its turn? Never raises — any failure reads as False.

    The answer is `transcript_tail.end_of_turn`'s, the same predicate the watchdog uses,
    so the two readers can never disagree about when a child is finished.
    """
    try:
        return transcript_tail.end_of_turn(_inner_records(agent_id, cfg)) is not None
    except Exception:  # noqa: BLE001 - a reader of a live transcript never raises
        return False


def last_text(agent_id: str, cfg: str | Path | None = None) -> str:
    """The inner agent's final reply. "" when there is no transcript or no text; never raises.

    When its turn has ended this is `transcript_tail.end_of_turn`'s text — the watchdog's
    `reply_text` — so an agent that ends by calling `SubagentHandback` (CLI 2.1.285+) yields
    the hand-back `message`, not "". Otherwise the last text block of its last `assistant`
    record."""
    try:
        records = _inner_records(agent_id, cfg)
        final = transcript_tail.end_of_turn(records)
        if final is not None and final.get("text"):
            return final["text"]
        last = next((rec for rec in reversed(records)
                     if isinstance(rec, dict) and rec.get("type") == "assistant"), None)
        if last is None:
            return ""
        texts = [b.get("text") for b in transcript_tail._blocks(last)
                 if b.get("type") == "text" and isinstance(b.get("text"), str)]
        return texts[-1] if texts else ""
    except Exception:  # noqa: BLE001 - a reader of a live transcript never raises
        return ""


def _tool_uses(records) -> list[dict]:
    """Every `tool_use` block of every `assistant` record, in stream order.

    The block walk is `transcript_tail._blocks` — the same one the watchdog reads a
    transcript with — so the two readers cannot drift apart.
    """
    calls = []
    for rec in records if isinstance(records, list) else []:
        if isinstance(rec, dict) and rec.get("type") == "assistant":
            calls += [b for b in transcript_tail._blocks(rec) if b.get("type") == "tool_use"]
    return calls


def verify_host(records, agent_ref: str, model: str) -> tuple[bool, str]:
    """Did the host make exactly one matching subagent call? `(ok, why)` — never raises.

    One `tool_use` block, named `Agent` (or `Task`), whose `input.subagent_type` equals
    `agent_ref` and `input.model` equals `model`. Every rejection names its cause: the call
    count, the tool name, or the field that disagreed.
    """
    calls = _tool_uses(records)
    if not calls:
        return False, "no Agent call"
    if len(calls) != 1:
        return False, f"{len(calls)} tool calls, expected 1"
    call = calls[0]
    name = call.get("name")
    if name not in HOST_TOOLS:
        return False, f"tool call {name} is not {'/'.join(HOST_TOOLS)}"
    inp = call.get("input") if isinstance(call.get("input"), dict) else {}
    got_ref = inp.get("subagent_type")
    if got_ref != agent_ref:
        return False, f"subagent_type {got_ref!r} != {agent_ref!r}"
    got_model = inp.get("model")
    if got_model != model:
        return False, f"model {got_model!r} != {model!r}"
    return True, f"1 {name} call {agent_ref} {model}"
