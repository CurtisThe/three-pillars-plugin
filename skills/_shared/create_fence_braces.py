"""create_fence_braces.py — simple shell brace expansion for the create fence (run-scratch-in-fence B2).

`expand_braces(word)` returns the literal words a shell would make from `word`, or
None when it cannot say (the caller then treats the target as unprovable, which the
hook allows and the leftover check reports). Read: comma lists (`{a,b}`, nested,
empty items), numeric ranges (`{1..3}`, descending, zero padded when an end has a
leading zero) and any product of them, up to `LIMIT` (64) words. Not read: a lone
`{x}`, `{}`, an unmatched brace, a letter range, a stepped range, anything over the
limit. `${NAME}` is a variable and is left untouched. Pure string work; nothing runs.
"""
from __future__ import annotations

import re

LIMIT = 64
_RANGE = re.compile(r"(-?\d+)\.\.(-?\d+)")


def _close(word, start):
    """Index of the `}` matching the `{` at `start`, or -1."""
    depth = 0
    for i in range(start, len(word)):
        if word[i] == "{":
            depth += 1
        elif word[i] == "}":
            depth -= 1
            if depth == 0:
                return i
    return -1


def _first_brace(word):
    """Index of the first `{` that is not the opening of `${`, or -1."""
    i = 0
    while i < len(word):
        if word[i] == "{":
            if i and word[i - 1] == "$":
                end = _close(word, i)
                if end < 0:
                    return i
                i = end
            else:
                return i
        i += 1
    return -1


def _items(body):
    """Top-level comma split of a brace body."""
    out, depth, cur = [], 0, []
    for ch in body:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        if ch == "," and depth == 0:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    out.append("".join(cur))
    return out


def _numeric(body):
    m = _RANGE.fullmatch(body)
    if not m:
        return None
    lo, hi = m.group(1), m.group(2)
    a, b = int(lo), int(hi)
    if abs(b - a) >= LIMIT:
        return None
    width = max(len(lo), len(hi)) if any(
        len(x.lstrip("-")) > 1 and x.lstrip("-").startswith("0") for x in (lo, hi)) else 0
    step = 1 if b >= a else -1
    return [str(n).zfill(width) for n in range(a, b + step, step)]


def expand_braces(word):
    """The literal words `word` expands to, or None when it cannot be read."""
    start = _first_brace(word)
    if start < 0:
        return [word]
    end = _close(word, start)
    if end < 0:
        return None
    body = word[start + 1:end]
    alts = _items(body)
    if len(alts) < 2:
        alts = _numeric(body)
    if not alts:
        return None
    out = []
    for alt in alts:
        more = expand_braces(word[:start] + alt + word[end + 1:])
        if more is None or len(out) + len(more) > LIMIT:
            return None
        out.extend(more)
    return out
