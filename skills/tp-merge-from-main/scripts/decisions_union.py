#!/usr/bin/env python3
"""The file-level union of two `decisions.md` appends (basesync-three-way-verifier).

Every design's `decisions.md` is append-only. When the merge base is a line-prefix of BOTH sides, the
two sides only ever added text after it, and the right merge is base plus both tails, each kept
verbatim. `union_decisions` returns that text, or None for any other shape (the caller then falls
through to the diff3 path, which defers whatever it cannot merge).

Lines are `text.split("\\n")`, never `splitlines()`: `"\\n".join(parts) == text` round-trips, and
`\\x0c`, `\\x1c`-`\\x1e`, U+0085 and U+2028/9 stay inside their lines. A terminal `''` (the text ended
with `\\n`) is not a line, so `'a\\n'` is a prefix of `'a\\nX\\n'`; a base with no trailing newline keeps
its last line, which must then equal the side's line. The result ends with exactly one `\\n`.

A tail is a HEADING (its first non-blank line is a `### [tag] title` decision entry) or a
CONTINUATION (anything else: more body for the base's last entry). At most one tail may be a
continuation; it goes first and is emitted verbatim, leading blanks kept (`base + S[len(base):]`),
so it is never glued to the base's last table row or list item. Each heading tail loses its leading
blanks and gets one blank line before it, unless the output already ends with one. Byte-equal tails
are emitted once.

Three guards return None (the caller falls through to diff3): any `\\r` in an input (CRLF is not
split on, so it never reaches the line-based union); and, before each heading tail is appended, an
open block in the output so far (an odd run of fence lines, an unclosed `<!--`, or more
`<details>`/`<div>`/`<pre>`/`<table>` openers than closers), which the tail would otherwise land
inside. Stdlib only, and it imports `line_shapes` only.
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from line_shapes import DECISION_ENTRY  # noqa: E402

_FENCE = re.compile(r"^ {0,3}(```|~~~)", re.MULTILINE)
_HTML_TAGS = ("details", "div", "pre", "table")


def _lines(text: str) -> list[str]:
    """`text.split("\\n")` without the terminal `''` that a trailing newline leaves."""
    parts = text.split("\n")
    if parts[-1] == "":
        parts.pop()
    return parts


def _blank(line: str) -> bool:
    """Spaces and tabs only: CommonMark's blank line, not `str.isspace()`."""
    return not line.strip(" \t")


def _is_heading(tail: list[str]) -> bool:
    first = next((line for line in tail if not _blank(line)), None)
    return first is not None and DECISION_ENTRY.match(first) is not None


def _strip_leading_blanks(tail: list[str]) -> list[str]:
    at = 0
    while at < len(tail) and _blank(tail[at]):
        at += 1
    return tail[at:]


def _inside_open_block(text: str) -> bool:
    """True when `text` ends inside an unclosed fence, `<!--` comment or HTML block."""
    marks = [m.group(1) for m in _FENCE.finditer(text)]
    if marks.count("```") % 2 or marks.count("~~~") % 2:
        return True
    comment = text.rfind("<!--")
    if comment != -1 and text.find("-->", comment + 4) == -1:
        return True
    for tag in _HTML_TAGS:                    # per tag: a stray `</pre>` must not close a `<div>`
        opened = len(re.findall(rf"<{tag}(?=[\s>/])", text, re.IGNORECASE))
        closed = len(re.findall(rf"</{tag}\s*>", text, re.IGNORECASE))
        if opened > closed:
            return True
    return False


def union_decisions(base: str, ours: str, theirs: str) -> str | None:
    """Base plus both tails verbatim, or None when the shape is anything else."""
    if "\r" in base or "\r" in ours or "\r" in theirs:
        return None
    base_lines, sides = _lines(base), (_lines(ours), _lines(theirs))
    n = len(base_lines)
    if any(side[:n] != base_lines or len(side) == n for side in sides):
        return None
    tails = [side[n:] for side in sides]
    heading = [_is_heading(tail) for tail in tails]
    if not any(heading):                      # two continuations: no order is known to be right
        return None
    if tails[0] == tails[1]:
        tails, heading = tails[:1], heading[:1]
    out = list(base_lines)
    # `sorted` is stable: the continuation (False) first, then ours' tail before theirs'.
    for tail, is_heading in sorted(zip(tails, heading), key=lambda pair: pair[1]):
        if not is_heading:
            out += tail
            continue
        if _inside_open_block("\n".join(out)):
            return None
        if out and not _blank(out[-1]):
            out.append("")
        out += _strip_leading_blanks(tail)
    return "\n".join(out) + "\n"
