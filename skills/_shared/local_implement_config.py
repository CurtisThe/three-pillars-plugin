#!/usr/bin/env python3
"""local_implement_config.py — read the `local_implement` block and gate `--local`.

design: local-implement-and-review

`load(root)` reads `.three-pillars/config.json`, validates the `local_implement`
block (the same shape as `repo-config.schema.json`, checked here with the stdlib
so the helper has no third-party dependency) and merges it over `DEFAULTS`.
`permission_error(cfg, mode)` returns the one refusal line naming every missing
key, or None when `--local` is permitted for that mode.
`runaway_ceiling_error(mode, capability)` (design: run-throughput) adds the
capability gate: the runaway ceiling must be proven available (`background
spawn` then `done detection`, both exactly true) for the mode's section,
else `--local` is refused even when the config permits it.

CLI::

    python3 skills/_shared/local_implement_config.py --check {interactive|full_design} [--root .] [--capability PATH]

exits 0 when permitted (prints nothing) and 1 with the refusal line otherwise. A
malformed config fails closed: exit 1 with one `--local refused:` line naming it.
A missing/unreadable capability file, or gated fields that are not true, also
refuses (fail closed).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

CONFIG_REL = ".three-pillars/config.json"
DEFAULTS = {"enabled": False, "model": "haiku", "fallback_model": "sonnet",
            "full_design": False, "escalate": True, "max_retries": 2, "max_files": 3,
            "attempt_wall_clock_s": 1200, "registry_files": []}
MODES = ("interactive", "full_design")
# The keys each mode needs set to true, in the order they are named.
_REQUIRED = {"interactive": ("enabled",), "full_design": ("enabled", "full_design")}
# The committed all-null capability file (runaway-check §Capability gate).
CAPABILITY_PATH = Path(__file__).resolve().parent / "runaway_capability.json"
# Capability section checked per mode, and the gated fields in check order.
_CAPABILITY_SECTION = {"interactive": "main", "full_design": "nested"}
_GATED = ("background_spawn_ok", "done_detected")


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


# The client-timeout env keys a `client_timeouts.values` record may hold (any subset).
_TIMEOUT_KEYS = ("CLAUDE_BYTE_STREAM_IDLE_TIMEOUT_MS", "CLAUDE_STREAM_IDLE_TIMEOUT_MS",
                 "API_TIMEOUT_MS", "CLAUDE_ASYNC_AGENT_STALL_TIMEOUT_MS")


def _client_timeouts_ok(v) -> bool:
    """`{applied_at: str|None, declined: bool, values: {<subset of keys>: int >= 1}}`."""
    if not isinstance(v, dict) or set(v) != {"applied_at", "declined", "values"}:
        return False
    vals = v["values"]
    return (v["applied_at"] is None or isinstance(v["applied_at"], str)) \
        and isinstance(v["declined"], bool) and isinstance(vals, dict) \
        and all(k in _TIMEOUT_KEYS and _is_int(x) and x >= 1 for k, x in vals.items())


_CHECKS = {
    "enabled": (lambda v: isinstance(v, bool), "a boolean"),
    "full_design": (lambda v: isinstance(v, bool), "a boolean"),
    "escalate": (lambda v: isinstance(v, bool), "a boolean"),
    "model": (lambda v: isinstance(v, str) and v != "", "a non-empty string"),
    "fallback_model": (lambda v: isinstance(v, str) and v != "", "a non-empty string"),
    "max_retries": (lambda v: _is_int(v) and v >= 0, "an integer >= 0"),
    "max_files": (lambda v: _is_int(v) and v >= 1, "an integer >= 1"),
    "attempt_wall_clock_s": (lambda v: _is_int(v) and v >= 60, "an integer >= 60"),
    "registry_files": (lambda v: isinstance(v, list) and all(isinstance(p, str) and p for p in v),
                       "an array of non-empty repo-relative path strings"),
    "default_run_flag": (lambda v: v in ("on", "off"), '"on" or "off"'),
    "client_timeouts": (_client_timeouts_ok,
                        "an object {applied_at: string|null, declined: bool, values: "
                        "{CLAUDE_*_TIMEOUT_MS / API_TIMEOUT_MS keys: int >= 1}}"),
}


def _validate(block) -> None:
    if not isinstance(block, dict):
        raise ValueError("local_implement must be an object")
    for key, value in block.items():
        if key not in _CHECKS:
            raise ValueError(f"local_implement has unknown key {key!r}")
        ok, want = _CHECKS[key]
        if not ok(value):
            raise ValueError(f"local_implement.{key} must be {want}, got {value!r}")


def load(root) -> dict | None:
    """The `local_implement` block merged over `DEFAULTS`, or None when absent.

    A missing config file or a config without the block is None (feature off).
    Unparseable JSON, a non-object config or block, an unknown key or a wrongly
    typed value raises `ValueError` — never a silent default.
    """
    path = Path(root) / CONFIG_REL
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ValueError(f"{CONFIG_REL} unreadable: {exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{CONFIG_REL} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{CONFIG_REL} must be a JSON object")
    if "local_implement" not in data:
        return None
    block = data["local_implement"]
    _validate(block)
    return {**DEFAULTS, **block}


def permission_error(cfg, mode: str) -> str | None:
    """One line naming each missing key, or None when `--local` is permitted.

    `interactive` needs `enabled`; `full_design` needs both `enabled` and
    `full_design`. `cfg` None (block absent) is read as `DEFAULTS`.
    """
    if mode not in _REQUIRED:
        raise ValueError(f"unknown mode {mode!r}; expected one of {MODES}")
    merged = {**DEFAULTS, **(cfg or {})}
    missing = [k for k in _REQUIRED[mode] if merged.get(k) is not True]
    if not missing:
        return None
    keys = " and ".join(f"local_implement.{k}=true" for k in missing)
    return f"--local refused: set {keys} in {CONFIG_REL}"


def load_capability(path) -> dict | None:
    """The parsed capability object at `path`, or None when unavailable.

    A missing/unreadable file, invalid JSON, or a non-object root yields None
    (fail closed). `None` fields inside a returned object mean `false`.
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
        data = json.loads(text)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def runaway_ceiling_error(mode: str, capability: dict | None) -> str | None:
    """The runaway-ceiling refusal line for `mode`, or None when the ceiling holds.

    `interactive` checks section `main`; `full_design` checks section `nested`.
    `background_spawn_ok` is checked first, then `done_detected`; each must be
    exactly `True` (null/false/missing refuses). A missing capability object
    or a missing/non-object section refuses with the background-spawn line.
    `taskstop_ok` and `router_stats_agent_match` are never checked.
    """
    if mode not in _CAPABILITY_SECTION:
        raise ValueError(f"unknown mode {mode!r}; expected one of {MODES}")
    section = _CAPABILITY_SECTION[mode]
    block = capability.get(section) if isinstance(capability, dict) else None
    if not isinstance(block, dict):
        return f"--local refused: runaway ceiling unavailable (background spawn, {section})"
    for key, label in zip(_GATED, ("background spawn", "done detection")):
        if block.get(key) is not True:
            return f"--local refused: runaway ceiling unavailable ({label}, {section})"
    return None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", required=True, choices=MODES)
    parser.add_argument("--root", default=".")
    parser.add_argument("--capability", default=str(CAPABILITY_PATH))
    args = parser.parse_args(argv)
    try:
        cfg = load(args.root)
    except ValueError as exc:
        print(f"--local refused: {exc}")
        return 1
    line = permission_error(cfg, args.check)
    if line:
        print(line)
        return 1
    line = runaway_ceiling_error(args.check, load_capability(args.capability))
    if line:
        print(line)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
