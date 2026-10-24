#!/usr/bin/env python3
"""run_retro_filter.py — apply the RRSI bar to grouped friction signals.

design: design-learn-retro. ``apply_rrsi(groups, known_items)`` takes the Groups
``run_retro_group.group_signals`` returns and the known items (``{id, kind, retro_key, text}``
dicts the CLI builds from open seeds; this module reads no Notion) and returns
``{drafts, observations, evidence_adds}``. The three RRSI tests, in order:

1. reusable mechanism: the group key is not ``event:<token>``;
2. it recurred (``count >= MIN_RECURRENCE``), cost an operator touch, or cost more than one
   re-run (``rerun_count >= MIN_RERUNS``);
3. no known item covers it: a covering item turns the group into an ``evidence_adds`` line
   naming that seed instead of a draft.

Anything failing 1 or 2 is an observation. A draft is built from the group's structured fields
only (key, normalised token, artifact names, refs); no entry body text is copied. Stdlib only.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_SHARED = str(Path(__file__).resolve().parent)
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

from run_retro_collect import normalised_token  # noqa: E402 — the one token normaliser

MIN_RECURRENCE = 2
MIN_RERUNS = 2
EVENT_PREFIX = "event:"
BUG_KINDS = frozenset(("block", "retry", "ci_fail", "escape", "stop"))
SLUG_PREFIX = "retro-"


def _fold(text) -> str:
    """Lower-case with ``_`` and spaces as ``-``: the same fold ``normalised_token`` applies."""
    return normalised_token(EVENT_PREFIX + (text or ""))


def _token_in(token: str, text) -> bool:
    """True when the full ``token`` occurs in ``text`` with a non-word edge or boundary each side."""
    if not token:
        return False
    return re.search(rf"(?<!\w){re.escape(token)}(?!\w)", _fold(text)) is not None


def matches(group: dict, item: dict) -> bool:
    """``retro_key`` equality, else the group's normalised token hyphen-bounded in ``item.text``."""
    retro_key = item.get("retro_key")
    if retro_key and retro_key == group["key"]:
        return True
    return _token_in(normalised_token(group["key"]), item.get("text"))


def _near_miss(token: str, item: dict) -> bool:
    """A non-matching item that shares the token's first segment or holds it inside a word."""
    folded = _fold(item.get("text"))
    if not token or not folded:
        return False
    return token in folded or token.split("-")[0] in re.split(r"\W+", folded)


def _covering(group: dict, known: list):
    """The known item covering ``group``: an exact ``retro_key`` first, else a token match."""
    for item in known:
        if item.get("retro_key") and item["retro_key"] == group["key"]:
            return item
    return next((item for item in known if matches(group, item)), None)


def _draft(group: dict, known: list) -> dict:
    token = normalised_token(group["key"])
    return {
        "retro_key": group["key"],
        "proposed_slug": SLUG_PREFIX + (token or "unnamed"),
        "skill": group["skill"],
        "type": "Bug" if BUG_KINDS & set(group["kinds"]) else "Idea",
        "shapes": list(dict.fromkeys([group["key"], token, *group["artifacts"]])),
        "evidence": list(group["refs"]),
        "count": group["count"],
        "operator_touch": group["operator_touch"],
        "rerun": group["rerun"],
        "candidates": [item["id"] for item in known if _near_miss(token, item)],
    }


def _observation(group: dict, reason: str) -> dict:
    return {"retro_key": group["key"], "count": group["count"], "kinds": list(group["kinds"]),
            "evidence": list(group["refs"]), "reason": reason}


def _evidence_add(group: dict, item: dict) -> dict:
    return {"seed": item["id"], "kind": item.get("kind"), "retro_key": group["key"],
            "evidence": list(group["refs"]), "count": group["count"]}


def _cleared_bar(group: dict) -> bool:
    return (group["count"] >= MIN_RECURRENCE or group["operator_touch"]
            or group["rerun_count"] >= MIN_RERUNS)


def apply_rrsi(groups, known_items) -> dict:
    """``{drafts, observations, evidence_adds}``: each group lands in exactly one bucket."""
    known = list(known_items or [])
    out = {"drafts": [], "observations": [], "evidence_adds": []}
    for group in groups or []:
        if group["key"].startswith(EVENT_PREFIX):
            out["observations"].append(_observation(group, "event-only"))
        elif not _cleared_bar(group):
            out["observations"].append(_observation(group, "below-bar"))
        elif (item := _covering(group, known)) is not None:
            out["evidence_adds"].append(_evidence_add(group, item))
        else:
            out["drafts"].append(_draft(group, known))
    return out
