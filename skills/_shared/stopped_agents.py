#!/usr/bin/env python3
"""stopped_agents.py — the backstop writer for the stopped-agents file.

design: m44-orphan-reaper (detailed-design.md Part B)

The router (companion local-llm-skills) reads this file before admitting a
new request from an agent. One JSON line per stopped agent:

    {"v": 1, "agent": "<full agent id>", "agent8": "<first 8 chars>",
     "attempt": "<attempt id>", "stopped_at": <epoch float>}

`agent` is the FULL id, `agent8` its first 8 characters (the contract's
match key); a stop may add extra fields (`orphaned_at`, `result`) after them,
never replacing one. Entries expire after TTL_S; the file is rewritten atomically
(keeping entries younger than TTL_S) once it would pass MAX_BYTES. Written
only where the router's state dir exists; an absent dir is reported, never
created. `active` is the contract's reference reader.

`append_ladder` writes the same line to `<ladder dir>/stops.ndjson` (`LADDER_STOPS`):
the durable measurement record, written with or without a router, never rotated,
and never cleared by `ladder_files` (it matches no side-file suffix); `records`
reads it (and this file) for `router_daily.py`, without the TTL.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

REL = Path("tp-local") / "stopped-agents.jsonl"
TTL_S = 86_400
MAX_BYTES = 65_536
LADDER_STOPS = "stops.ndjson"


def path(env) -> Path:
    """`$TP_LOCAL_STOPPED`, else `($XDG_STATE_HOME or $HOME/.local/state)/tp-local/stopped-agents.jsonl`."""
    if env.get("TP_LOCAL_STOPPED"):
        return Path(env["TP_LOCAL_STOPPED"])
    if env.get("XDG_STATE_HOME"):
        return Path(env["XDG_STATE_HOME"]) / REL
    home = Path(env["HOME"]) if env.get("HOME") else Path.home()
    return home / ".local" / "state" / REL


def _valid(line, now: float) -> dict | None:
    """The entry if the line is a valid (v 1, parseable, young) entry, else None."""
    try:
        entry = json.loads(line)
    except ValueError:
        return None
    if not isinstance(entry, dict) or entry.get("v") != 1:
        return None
    stamp = entry.get("stopped_at")
    if not isinstance(stamp, (int, float)) or isinstance(stamp, bool):
        return None
    return entry if now - stamp < TTL_S else None


def _entry(agent_id: str, attempt_id: str, stopped_at: float, extra=None) -> dict:
    base = {"v": 1, "agent": agent_id, "agent8": (agent_id or "")[:8],
            "attempt": attempt_id, "stopped_at": stopped_at}
    return {**base, **{k: v for k, v in (extra or {}).items() if k not in base}}


def append_ladder(ladder_dir, agent_id: str, *, attempt_id: str, now=None, extra=None) -> str:
    """Append the stop's line to `<ladder_dir>/stops.ndjson`; "written" or "error: …"."""
    now = time.time() if now is None else float(now)
    try:
        with open(Path(ladder_dir) / LADDER_STOPS, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(_entry(agent_id, attempt_id, now, extra),
                                separators=(",", ":")) + "\n")
        return "written"
    except OSError as exc:
        return f"error: {exc}"


def records(path) -> list[dict]:
    """Every valid v-1 line (numeric `stopped_at`) of a stops file, no TTL; `[]` if unreadable."""
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    return [e for e in (_valid(line, float("-inf")) for line in lines) if e]


def append(agent_id: str, *, attempt_id: str, now=None, env=os.environ, extra=None) -> str:
    """One line for the stop (plus `extra` fields); "written", "no-router" (parent dir
    absent), or "error: …"."""
    now = time.time() if now is None else float(now)
    try:
        p = path(env)
        if not p.parent.is_dir():
            return "no-router"
        lines = p.read_text(encoding="utf-8").splitlines() if p.is_file() else []
        if lines and p.stat().st_size > MAX_BYTES:
            kept = [json.dumps(entry, separators=(",", ":"))
                    for line in lines if (entry := _valid(line, now)) is not None]
            body = "".join(line + "\n" for line in kept)
        else:
            body = "".join(line + "\n" for line in lines if line)
        body += json.dumps(_entry(agent_id, attempt_id, now, extra), separators=(",", ":")) + "\n"
        tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
        tmp.write_text(body, encoding="utf-8")
        os.replace(tmp, p)
        return "written"
    except OSError as exc:
        return f"error: {exc}"


def active(path, *, now=None, ttl_s: int = TTL_S) -> set:
    """The live `agent8` set: valid v-1 entries with a `agent8` younger than `ttl_s`."""
    now = time.time() if now is None else float(now)
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return set()
    out = set()
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict) or entry.get("v") != 1:
            continue
        stamp = entry.get("stopped_at")
        if not isinstance(stamp, (int, float)) or isinstance(stamp, bool):
            continue
        if now - stamp < ttl_s:
            agent8 = entry.get("agent8")
            if isinstance(agent8, str) and agent8:
                out.add(agent8)
    return out
