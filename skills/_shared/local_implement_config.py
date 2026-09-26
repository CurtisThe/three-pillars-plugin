#!/usr/bin/env python3
"""local_implement_config.py — read the `local_implement` block and gate `--local`.

design: local-implement-and-review

`load(root)` reads `.three-pillars/config.json`, validates the `local_implement`
block (the same shape as `repo-config.schema.json`, checked here with the stdlib
so the helper has no third-party dependency) and merges it over `DEFAULTS`.
`permission_error(cfg, mode)` returns the one refusal line naming every missing
key, or None when `--local` is permitted for that mode.

CLI::

    python3 skills/_shared/local_implement_config.py --check {interactive|full_design} [--root .]

exits 0 when permitted (prints nothing) and 1 with the refusal line otherwise. A
malformed config fails closed: exit 1 with one `--local refused:` line naming it.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

CONFIG_REL = ".three-pillars/config.json"
DEFAULTS = {"enabled": False, "model": "haiku", "fallback_model": "sonnet",
            "full_design": False, "escalate": True, "max_retries": 2, "max_files": 3}
MODES = ("interactive", "full_design")
# The keys each mode needs set to true, in the order they are named.
_REQUIRED = {"interactive": ("enabled",), "full_design": ("enabled", "full_design")}


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


_CHECKS = {
    "enabled": (lambda v: isinstance(v, bool), "a boolean"),
    "full_design": (lambda v: isinstance(v, bool), "a boolean"),
    "escalate": (lambda v: isinstance(v, bool), "a boolean"),
    "model": (lambda v: isinstance(v, str) and v != "", "a non-empty string"),
    "fallback_model": (lambda v: isinstance(v, str) and v != "", "a non-empty string"),
    "max_retries": (lambda v: _is_int(v) and v >= 0, "an integer >= 0"),
    "max_files": (lambda v: _is_int(v) and v >= 1, "an integer >= 1"),
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


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", required=True, choices=MODES)
    parser.add_argument("--root", default=".")
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
