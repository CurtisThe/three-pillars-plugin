#!/usr/bin/env python3
"""launcher_env.py — scrubbing one window's launcher env before a child inherits it.

main-thread-direct-backend task 1.1 (design §S1). The launcher plans a route per folder and
records what it chose: `CLAUDE_LAUNCHER_FORCE_BACKEND` (the backend it forced), `CLAUDE_LAUNCHER_ROLE`
and `CLAUDE_LAUNCHER_OWNED` — the names of every var it injected. A process started inside that
window would otherwise carry the parent's route instead of planning its own from its own folder,
so `child_spawn_ops.child_env` applies `strip_launcher_keys` — the launcher's own step-0 scrub —
before launching a child. The one exception is a forced `strata` backend, which `backend.py`'s
`_run_strata` exports deliberately so a Strata window's children stay local. The scrub assumes
PATH `claude` is the launcher whenever `CLAUDE_LAUNCHER_OWNED` is set, since only the launcher
sets it. Stdlib only.
"""
from __future__ import annotations

__all__ = ["LAUNCHER_KEYS", "FORCE_BACKEND_ENV", "OWNED_ENV", "STRATA", "owned_keys",
           "strip_launcher_keys"]

LAUNCHER_KEYS = ("CLAUDE_LAUNCHER_FORCE_BACKEND", "CLAUDE_LAUNCHER_ROLE", "CLAUDE_LAUNCHER_OWNED")
FORCE_BACKEND_ENV = "CLAUDE_LAUNCHER_FORCE_BACKEND"
OWNED_ENV = "CLAUDE_LAUNCHER_OWNED"
STRATA = "strata"
_SEPARATORS = ",: \t\n\r"  # the launcher writes the list, so any of these may divide it


def owned_keys(env: dict) -> set[str]:
    """The var names `CLAUDE_LAUNCHER_OWNED` records, split on commas, colons and whitespace.

    Empty fields are dropped and a name the env lacks is no error: the list is the launcher's
    record of what it set, not a claim that each key is still in the env.
    """
    raw = str(env.get(OWNED_ENV, ""))
    for sep in _SEPARATORS:
        raw = raw.replace(sep, " ")
    return {name for name in raw.split() if name}


def strip_launcher_keys(env: dict) -> dict:
    """A copy of `env` without the launcher's own keys and without any name it owns.

    Never mutates its input. `CLAUDE_LAUNCHER_FORCE_BACKEND` is the one key kept, and only when
    its value is exactly `strata`.
    """
    drop = set(LAUNCHER_KEYS) | owned_keys(env)
    if str(env.get(FORCE_BACKEND_ENV, "")) == STRATA:
        drop.discard(FORCE_BACKEND_ENV)
    return {k: v for k, v in env.items() if k not in drop}
