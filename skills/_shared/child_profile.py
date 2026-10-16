#!/usr/bin/env python3
"""child_profile.py — the profile rule for a spawned child session, in one module.

design: child-spawn-profile-inherit

A child `claude -p` spawned by the local dispatcher inherits the orchestrator's Claude
profile: `pin` puts `CLAUDE_LAUNCHER_FORCE_PROFILE=<name>` into the child env when the
parent's `CLAUDE_CONFIG_DIR` is a profile dir (a dir directly under `.claude-profiles`),
and is a no-op otherwise. `candidate_dirs` is every dir a transcript scan should poll for a
child id — the primary config dir first, then its sibling profiles — and `polled_note`
renders that list for the log line; `note_found` records once, per (id, dir) pair, when a
child's transcript turned up somewhere other than the primary dir. Stdlib only; every scan
is fail-open — a missing or unlistable dir returns a value, never raises.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Mapping, Optional, Sequence

__all__ = ["FORCE_PROFILE_ENV", "PROFILES_DIRNAME", "profile_name", "pin",
           "config_dir", "candidate_dirs", "note_found", "polled_note"]

FORCE_PROFILE_ENV = "CLAUDE_LAUNCHER_FORCE_PROFILE"
PROFILES_DIRNAME = ".claude-profiles"

# (key, found-dir) pairs already reported, so `note_found` stays one line per pair.
_noted: set = set()


def config_dir(env: Optional[Mapping[str, str]] = None) -> Path:
    """The Claude config dir: `$CLAUDE_CONFIG_DIR` when set, else `~/.claude`."""
    env = os.environ if env is None else env
    return Path(env.get("CLAUDE_CONFIG_DIR") or (Path.home() / ".claude"))


def profile_name(path: object) -> Optional[str]:
    """The profile name when `path` is a dir directly under `.claude-profiles`, else None."""
    if not path:
        return None
    try:
        d = Path(str(path))
    except TypeError:
        return None
    if d.parent.name == PROFILES_DIRNAME and d.name and d.name != PROFILES_DIRNAME:
        return d.name
    return None


def pin(parent_env: Mapping[str, str], child_env: Mapping[str, str]) -> dict:
    """`child_env` plus the profile pin derived from the parent's config dir; inputs untouched."""
    out = dict(child_env)
    name = profile_name(parent_env.get("CLAUDE_CONFIG_DIR"))
    if name:
        out[FORCE_PROFILE_ENV] = name
    return out


def candidate_dirs(cfg: object) -> list:
    """Dirs to poll for a child's transcripts: `cfg` first, then sibling profiles, sorted."""
    primary = Path(str(cfg)) if cfg else config_dir()
    dirs = [primary]
    parent = primary.parent
    if parent.name != PROFILES_DIRNAME:
        return dirs
    try:
        siblings = sorted(p for p in parent.iterdir() if p.is_dir() and p != primary)
    except OSError:
        return dirs
    return dirs + siblings


def note_found(key: str, found: object, cfg: object) -> None:
    """Log once per (key, found) that a child's transcript was under `found`, not `cfg`."""
    found_dir, primary = Path(str(found)), Path(str(cfg))
    if found_dir == primary:
        return
    pair = (str(key), str(found_dir))
    if pair in _noted:
        return
    _noted.add(pair)
    print(f"[child-profile] {key} found under {found_dir}, not {primary}",
          file=sys.stderr)


def polled_note(cfg: Optional[object] = None) -> str:
    """` (polled <dirs>)` — every dir a scan of a child id would look in."""
    dirs: Sequence[Path] = candidate_dirs(cfg if cfg else config_dir())
    return " (polled " + ", ".join(str(d) for d in dirs) + ")"
