"""explainer/explain_config.py — the top-level `explainer` repo-config block.

Public API:
    CONFIG_KEY          "explainer"
    CONFIG_REL          ".three-pillars/config.json"
    DEFAULTS            {"enabled": True, "publish_artifact": True, "drafter_override": {}}
    OVERRIDE_KINDS      the kinds a drafter override may pin ("pr-brief", "human-escalation")
    OVERRIDE_ENGINES    the engines an override may name ("opus",)
    load(root) -> dict

`load` reads `<root>/.three-pillars/config.json` and merges its `explainer` block
over DEFAULTS with drop-and-warn: each bad entry is dropped with one line on
stderr and its default stays. Bad entries are an unknown key, a non-bool
`enabled` / `publish_artifact`, a non-object `drafter_override`, and an override
whose kind is not in OVERRIDE_KINDS or whose value is not in OVERRIDE_ENGINES.
A non-object block warns once and gives the defaults. A missing file or a
config without the block gives the defaults silently; an unreadable or
non-object config warns once and reads as missing (repo-config.md §Fail-open).
`load` never raises on config content. The schema node is
`repo-config.schema.json` → `properties.explainer`.

`enabled: false` is the off switch: the call sites skip the explainer and the
PR flow is today's. `publish_artifact: false` keeps the local HTML only.

Stdlib only. Flat-import package — no __init__.py.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SHARED_DIR = _HERE.parent
for _p in (_SHARED_DIR, _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

CONFIG_KEY = "explainer"
CONFIG_REL = ".three-pillars/config.json"
DEFAULTS = {"enabled": True, "publish_artifact": True, "drafter_override": {}}
OVERRIDE_KINDS = ("pr-brief", "human-escalation")
OVERRIDE_ENGINES = ("opus",)
_SWITCHES = ("enabled", "publish_artifact")


def _warn(message: str) -> None:
    print(f"config: {message}", file=sys.stderr)


def _defaults() -> dict:
    """A fresh copy of DEFAULTS (the override map is never shared)."""
    return {**DEFAULTS, "drafter_override": {}}


def _read_config(root) -> dict | None:
    """The parsed config object, or None (missing file, or unreadable with a warning)."""
    path = Path(root) / CONFIG_REL
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        _warn(f"{CONFIG_REL} unreadable ({exc}); {CONFIG_KEY} uses its defaults")
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        _warn(f"{CONFIG_REL} is not valid JSON ({exc}); {CONFIG_KEY} uses its defaults")
        return None
    if not isinstance(data, dict):
        _warn(f"{CONFIG_REL} is not a JSON object; {CONFIG_KEY} uses its defaults")
        return None
    return data


def _overrides(value) -> dict:
    """The kept `drafter_override` entries; one warning per dropped entry."""
    if not isinstance(value, dict):
        _warn(f"dropped {CONFIG_KEY}.drafter_override ({value!r}) — must be an object")
        return {}
    kept: dict = {}
    for kind, engine in value.items():
        if kind not in OVERRIDE_KINDS:
            _warn(f"dropped {CONFIG_KEY}.drafter_override.{kind} ({engine!r}) — legal "
                  f"kinds: {' or '.join(OVERRIDE_KINDS)}")
        elif engine not in OVERRIDE_ENGINES:
            _warn(f"dropped {CONFIG_KEY}.drafter_override.{kind} ({engine!r}) — legal "
                  f"values: {' or '.join(OVERRIDE_ENGINES)}")
        else:
            kept[kind] = engine
    return kept


def load(root) -> dict:
    """The `explainer` block of `<root>`'s config merged over DEFAULTS (drop-and-warn)."""
    merged = _defaults()
    data = _read_config(root)
    if data is None or CONFIG_KEY not in data:
        return merged
    block = data[CONFIG_KEY]
    if not isinstance(block, dict):
        _warn(f"dropped {CONFIG_KEY} ({block!r}) — must be an object; using defaults")
        return merged
    for key, value in block.items():
        if key in _SWITCHES:
            if isinstance(value, bool):
                merged[key] = value
            else:
                _warn(f"dropped {CONFIG_KEY}.{key} ({value!r}) — must be true or false")
        elif key == "drafter_override":
            merged[key] = _overrides(value)
        else:
            _warn(f"dropped {CONFIG_KEY}.{key} ({value!r}) — legal keys: "
                  f"{', '.join(DEFAULTS)}")
    return merged
