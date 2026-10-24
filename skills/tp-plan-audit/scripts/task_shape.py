"""task_shape.py — text-only task shape checks (Red clauses, entry points, env)."""
from __future__ import annotations

import re
import sys
from pathlib import Path

_SHARED = str(Path(__file__).resolve().parents[2] / "_shared")
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)
_SCRIPTS = str(Path(__file__).resolve().parent)
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import sizing_limits  # noqa: E402
import task_oracle  # noqa: E402

_SPAN = re.compile(r"`[^`]*`")
_BULLET = re.compile(r"^\s*(?:[-*]|\d+[.)])\s+\S", re.M)
_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z(])")
_MARK = re.compile(r"\([a-z]\)")


def red_clauses(text: str) -> int:
    """Count the clauses of a Red field (backticked spans removed first)."""
    text = _SPAN.sub("", text or "")
    bullets = _BULLET.findall(text)
    if bullets:
        return len(bullets)
    semi = len([s for s in text.split(";") if s.strip()])
    sents = len([s for s in _SENT.split(text.strip()) if s.strip()])
    return max(semi, sents, len(_MARK.findall(text)))


def shape_findings(fields: dict, helpers) -> list[str]:
    """Messages for Red clause count, entry points and env-without-helper."""
    out: list[str] = []
    red = fields.get("Red") or ""
    n = red_clauses(red)
    if n > sizing_limits.MAX_RED_CLAUSES:
        out.append(f"red has {n} > {sizing_limits.MAX_RED_CLAUSES} clauses; "
                   "split into two tasks")
    ep = task_oracle.parse_entry_point(fields.get("Entry point"))
    if len(ep["items"]) > sizing_limits.MAX_ENTRY_POINTS:
        out.append(f"task lists {len(ep['items'])} > "
                   f"{sizing_limits.MAX_ENTRY_POINTS} entry points; "
                   "split into two tasks")
    if sizing_limits.ENV_PATTERN.search(red) and not any(
            h in red for h in helpers):
        out.append("red builds a real environment without a test helper; "
                   "name your repo's test helper "
                   "(list it in `plan_audit.test_helpers`)")
    return out
