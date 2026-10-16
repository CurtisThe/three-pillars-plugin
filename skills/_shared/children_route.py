#!/usr/bin/env python3
"""children_route.py — the route a direct run's children get.

launch-role-precedence task 2.1. `is_direct_run` is the one signal that survives the
launcher's own scrub (`plan.py` deletes `CLAUDE_LAUNCHER_ROLE` and
`CLAUDE_LAUNCHER_FORCE_BACKEND` before re-exporting; `backend.py` sets and owns
`CLAUDE_LAUNCHER_BACKEND` to the effective backend, `direct` for a seat or run). When a
session is a direct run, `effective_env` hands its children `ANTHROPIC_BASE_URL` pointed
at the router, found via `launcher_which.which` and, for a `hybrid` folder, `router_url`
in `<home>/launcher.toml`. Any failure gives the env back unchanged. Stdlib only.

Task 3.16 (impl-audit finding): the children's route applies only when this run's
`child_spawn.py probe` answers `child`. A direct run whose probe answers `in-process` runs its
`local-*` work as an in-process `Agent(...)` with no `ANTHROPIC_BASE_URL`, which would reach
Anthropic's real Haiku; leaving its env unchanged makes the route check say
`unrouted/no-base-url`, so the existing Sonnet floor applies exactly as before Part B.
"""
from __future__ import annotations

import re
from pathlib import Path

import launcher_which

__all__ = ["is_direct_run", "resolve_route", "effective_env", "floor_in_process", "probe_mode",
           "DEFAULT_RESOLVER", "DEFAULT_PROBE"]

_ROUTER_URL_RE = re.compile(r'router_url\s*=\s*"([^"]+)"')

_CACHE: dict = {}
_PROBING = False  # set while the probe runs: a nested `effective_env` (the smoke's own lease key,
                  # route check…) gets its env back unchanged instead of re-entering the probe


def is_direct_run(env: dict) -> bool:
    """True when `env` belongs to a direct session: `CLAUDE_LAUNCHER_BACKEND == "direct"`
    and no `ANTHROPIC_BASE_URL` — the signal that survives the launcher's own scrub."""
    return env.get("CLAUDE_LAUNCHER_BACKEND") == "direct" and "ANTHROPIC_BASE_URL" not in env


def resolve_route(cwd, env: dict) -> str | None:
    """The folder's `claude-which` plan, and for a `hybrid` folder, `router_url` from
    `<home>/launcher.toml`. Any failure returns None; nothing raises."""
    try:
        home = launcher_which.launcher_home(env)
        if home is None:
            return None
        info = launcher_which.which(cwd, env, home=home)
        if not info or info.get("effective") != "hybrid":
            return None
        text = (Path(home) / "launcher.toml").read_text(encoding="utf-8")
        match = _ROUTER_URL_RE.search(text)
        return match.group(1) if match else None
    except Exception:
        return None


def probe_mode(cwd, env: dict) -> str | None:
    """This run's `child_spawn.py probe` answer — `child` or `in-process` — asked through
    `child_spawn.cmd_probe` (cached per run in the run dir; the smoke it may run is cached per
    repo and claude version). None when the probe cannot be asked; nothing raises."""
    try:
        import child_spawn  # lazy: child_spawn imports this module
        return child_spawn.cmd_probe(run=None, root=str(cwd), env=env).get("mode")
    except Exception:
        return None


# The attributes `effective_env` actually calls when no `resolver=` / `probe=` is passed. Kept
# separate from `resolve_route` / `probe_mode` so a fixture (the conftest autouse ones, and the
# 2.2/2.3/3.16 tests) can monkeypatch the behaviour `effective_env` falls back to without
# disturbing the functions themselves, which stay directly testable.
DEFAULT_RESOLVER = resolve_route
DEFAULT_PROBE = probe_mode


def _probe_once(cwd, env: dict, probe) -> str | None:
    """The probe's answer for `cwd`, asked once per process under the re-entrancy guard."""
    global _PROBING
    key = ("probe", str(cwd))
    if key in _CACHE:
        return _CACHE[key]
    _PROBING = True
    try:
        mode = probe(cwd, env)
    finally:
        _PROBING = False
    _CACHE[key] = mode
    return mode


def effective_env(env: dict, cwd, resolver=None, probe=None) -> dict:
    """`env` unchanged unless `is_direct_run(env)` AND this run's child-spawn probe answers
    `child`, in which case a copy with `ANTHROPIC_BASE_URL` set to the resolved router URL —
    unchanged if there is none. An `in-process` (or unknown) probe answer leaves the env as it
    is, so the route check reports `unrouted/no-base-url` and the `local-*` rungs floor to
    Sonnet as before. A call nested inside the probe itself is unchanged too. The probe answer
    and the resolved URL are cached per `cwd`."""
    if not is_direct_run(env) or _PROBING:
        return env
    if _probe_once(cwd, env, probe if probe is not None else DEFAULT_PROBE) != "child":
        return env
    active_resolver = resolver if resolver is not None else DEFAULT_RESOLVER
    cache_key = str(cwd)
    if cache_key in _CACHE:
        url = _CACHE[cache_key]
    else:
        url = active_resolver(cwd, env)
        _CACHE[cache_key] = url
    if not url:
        return env
    new_env = dict(env)
    new_env["ANTHROPIC_BASE_URL"] = url
    return new_env


def floor_in_process(verdict: dict, env: dict) -> dict:
    """`verdict` unchanged unless it is an `in-process` probe answer for a direct run, in which
    case a copy with `"model": "sonnet"` added. A direct session has no Strata route in-process,
    so a `local-*` model would reach Anthropic's real Haiku; a site runs `Agent(...)` with this
    model instead. Pure; anything that goes wrong gives `verdict` back."""
    try:
        if verdict.get("mode") == "in-process" and is_direct_run(env):
            return {**verdict, "model": "sonnet"}
    except Exception:
        pass
    return verdict
