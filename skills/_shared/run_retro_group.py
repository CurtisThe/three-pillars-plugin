#!/usr/bin/env python3
"""run_retro_group.py — bucket friction signals by root cause.

design: design-learn-retro. ``group_signals`` takes the Signals ``run_retro_collect.collect``
returns and groups them by ``key``, the structured mechanism token (``path:…``,
``finalizer:…``, ``escape:…``, ``junit:…``, else ``event:<token>``), never by the kind or the
event type. A Group is ``{key, count, refs, kinds, artifacts, skill, operator_touch, rerun,
rerun_count}``: ``operator_touch`` and ``rerun`` are the OR over the signals, ``rerun_count``
is the number of ``retry``-kind signals in the group, ``kinds`` the sorted set of kinds and
``artifacts`` the sorted names of the files the refs point into. Groups come out in first-seen
key order. Pure: no reads, no writes. Stdlib only.
"""
from __future__ import annotations

import re

RETRY_KIND = "retry"
_ARTIFACT = re.compile(r"(?:^|; )([\w-]+\.[\w.-]*\w)(?::|$)")


def artifact_names(ref: str) -> list[str]:
    """The file names a ref points into: ``a.md: x; b.json: y`` gives ``[a.md, b.json]``."""
    return _ARTIFACT.findall(ref or "")


def _new_group(key: str) -> dict:
    return {"key": key, "count": 0, "refs": [], "kinds": [], "artifacts": [], "skill": "",
            "operator_touch": False, "rerun": False, "rerun_count": 0}


def _add(group: dict, signal: dict) -> None:
    group["count"] += 1
    if signal.get("ref"):
        group["refs"].append(signal["ref"])
    kind = signal.get("kind")
    if kind and kind not in group["kinds"]:
        group["kinds"].append(kind)
    for name in artifact_names(signal.get("ref", "")):
        if name not in group["artifacts"]:
            group["artifacts"].append(name)
    group["skill"] = group["skill"] or signal.get("skill") or ""
    group["operator_touch"] = group["operator_touch"] or bool(signal.get("operator_touch"))
    group["rerun"] = group["rerun"] or bool(signal.get("rerun"))
    group["rerun_count"] += kind == RETRY_KIND


def group_signals(signals) -> list[dict]:
    """The Groups of ``signals``, one per distinct ``key``, in first-seen order."""
    groups: dict[str, dict] = {}
    for signal in signals or []:
        key = signal.get("key")
        if not key:
            continue
        _add(groups.setdefault(key, _new_group(key)), signal)
    for group in groups.values():
        group["kinds"].sort()
        group["artifacts"].sort()
    return list(groups.values())
