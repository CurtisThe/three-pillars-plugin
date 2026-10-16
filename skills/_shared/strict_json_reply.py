"""The strict one-object reply contract for the finalizer and review-angle replies.

A reply is exactly one JSON object: bare, or inside ONE fence (3+ backticks or tildes, an
optional ``json`` tag, the closer the same run as the opener). Anything else is not a reply:
prose before or after or on the opener line, a second object or fence, a malformed, partial or
too-deeply nested object, a repeated key at any depth, or a JSON value that is not an object
(a list, a string, a number). Nothing is searched for inside the text, so backticks inside a
JSON string (a quoted code fence in a reproducer) cannot cut the reply short.

First written for the finalizer reply (PR #188 round-4 ruling "Strict fix"); the review-angle
reply (`review_merge.parse_codereview_result`) uses the same contract (known issue M27).
Other envelopes (`parse_tier_return`, `classifier_judge`, the certifier) still take the last
fenced json block; they are not covered here.
"""
from __future__ import annotations

import json
import re

ONE_FENCE = re.compile(r"(?P<fence>`{3,}(?!`)|~{3,}(?!~))(?i:json)?[ \t]*\r?\n(?P<body>.*)"
                       r"\n[ \t]*(?P=fence)[ \t]*", re.DOTALL)


def unique_keys(pairs):
    """An object hook: a repeated key (a second ``outcome``, say) is malformed, not last-wins."""
    keys = [k for k, _ in pairs]
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate key in the reply envelope")
    return dict(pairs)


def one_object(text) -> dict | None:
    """The reply's one JSON object under the strict contract, else ``None``.

    A non-str input (a misbehaving caller) is ``None`` too, never an exception. A leading
    byte-order mark is not prose: every reader gets the same answer whatever its decoding.
    """
    if not isinstance(text, str):
        return None
    body = text.lstrip("\ufeff").strip()
    match = ONE_FENCE.fullmatch(body)
    if match:
        body = match.group("body")
    try:
        data = json.loads(body, object_pairs_hook=unique_keys)
    except (ValueError, RecursionError):
        return None
    return data if isinstance(data, dict) else None
