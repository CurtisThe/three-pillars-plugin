#!/usr/bin/env python3
"""Two insert-only living-doc classes: `keyed-heading-insertion` and `last-updated-preamble`.

Both are predicates over one `conflict_parse.Hunk` plus a merge that returns the region's lines.
Neither reads or emits a base line, and neither drops one: a keep-both merge is a permutation of
ours' and theirs' lines, and the preamble merge replaces exactly one line on each side with one.

**`keyed-heading-insertion`** (`is_keyed_heading_insertion`, `merge_keyed_heading_lines`). Both
sides inserted whole entries at one point, each headed by a KEYED heading (`KEYED_HEADING`):
`### M48: …`, a placeholder `### M-new-<slug>: …`, a resolved `### M27 (RESOLVED 2026-09-30): …`,
or an archive slug `` ### `slug` (2026-09-29) ``. Soundness is the same as the other keep-both
classes (an EMPTY base: neither side removed a line), plus the four refusals that keep every line
under the entry it was written under:

* the region is 3-way (a 2-way region records no base, so it cannot show the base was empty);
* each side STARTS at a keyed heading and holds no other heading (any `#`-heading at any
  indentation or inside a list item, a setext underline), no carriage return inside a line, and
  nothing `line_shapes.keep_both_refusal` refuses (a fence, an HTML block, a block quote, display
  math, a link definition), so no line of it can swallow or re-parent the other side's entries;
* the keys are DISTINCT across both sides and within each: one key on both sides is a collision
  (the gated `id-renumber-collision` class), never a keep-both;
* the first non-blank line after the region is a level 1-3 ATX heading or EOF: it follows THEIRS'
  last entry in the merge although it followed OURS' on ours' side.

The merge keeps ours' lines then theirs' unchanged, except that when every key is a numbered ID
(`[HML][0-9]+`) the whole entries are sorted by (letter, number), a side's leading blank lines
staying with its first entry. A key that is a placeholder or a slug has no order, so nothing moves.

**`last-updated-preamble`** (`is_last_updated_preamble`, `merge_last_updated_lines`). Ours and
theirs are each exactly one `*Last updated: YYYY-MM-DD …*` line and base is empty or one such line.
The merge is the later-dated line (ours on a tie) when the text after the date is the same, and
otherwise the later date and summary followed by the other side's summary.

`extra_label` and `extra_confident` are what `classify` calls; `extra_confident` also re-verifies
`shaped-line-merge`. This module imports `line_shapes`, `conflict_parse` and one leaf, `shaped_merge`
(which imports only those two), never `classify` (which imports it) or `resolvers`. Stdlib only.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conflict_parse import Hunk  # noqa: E402
from line_shapes import (  # noqa: E402
    ENTRY_SECTION_END, FOREIGN_ATX, SETEXT_UNDERLINE, keep_both_refusal,
)
import shaped_merge  # noqa: E402

# `### M48: t`, `### M-new-<slug>: t`, `### M27 (RESOLVED 2026-09-30): t` (group 1, the key) or
# `` ### `slug` (2026-09-29) `` (group 2). Spelled with `[ \t]`, never `\s`: a Unicode space after
# the hashes is paragraph text to CommonMark, not a heading.
KEYED_HEADING = re.compile(
    r"^### (?:([HML](?:[0-9]+|-new-[a-z0-9]+(?:-[a-z0-9]+)*))(?:[ \t]+\([^)\n]*\))?:"
    r"|`([a-z0-9][a-z0-9-]*)`[ \t]+\([0-9]{4}-[0-9]{2}-[0-9]{2}\))")
LAST_UPDATED = re.compile(r"^\*Last updated:[ \t]+([0-9]{4}-[0-9]{2}-[0-9]{2})(.*)\*[ \t]*$")
NUMBERED_KEY = re.compile(r"[HML][0-9]+")


def _heading_at(side: list[str], i: int) -> bool:
    """Restated from `classify._heading_at` (this module must not import `classify`): `side[i]`
    makes a heading, an ATX heading indented 0-3 spaces or a setext underline directly below a
    line that is not blank (spaces, tabs and a CRLF `\\r` only; NBSP is text to CommonMark)."""
    if FOREIGN_ATX.match(side[i]):
        return True
    return i > 0 and bool(side[i - 1].strip(" \t\r")) and bool(SETEXT_UNDERLINE.match(side[i]))


def _ends_at_boundary(h: Hunk, *starts: re.Pattern) -> bool:
    """Restated from `classify._ends_at_boundary`: the first non-blank line after the region
    (`Hunk.post_context`) matches one of `starts`, or the region ends the file. An unknown line
    (`None`: another region follows directly, or a hand-built hunk) is refused."""
    post = h.post_context
    return post is not None and (not post or any(rx.match(post) for rx in starts))


def _key(m: re.Match) -> str:
    """The identity of a keyed heading: its ID, or its backtick-quoted slug."""
    return m.group(1) or f"`{m.group(2)}`"


def _side_keys(side: list[str]) -> list[str] | None:
    """The keys of `side`'s keyed headings in order, or None when `side` is not whole keyed entries:
    its first non-blank line is not a keyed heading, some line is refused by `keep_both_refusal`,
    or a heading other than a keyed one appears inside it."""
    content = [ln for ln in side if ln.strip()]
    if not content or not KEYED_HEADING.match(content[0]):
        return None
    if keep_both_refusal(side, KEYED_HEADING) is not None:
        return None
    keys = []
    for i, line in enumerate(side):
        m = KEYED_HEADING.match(line)
        if m:
            keys.append(_key(m))
        elif _heading_at(side, i):
            return None
    return keys


def is_keyed_heading_insertion(h: Hunk) -> bool:
    """Both sides inserted whole keyed entries at one point with distinct keys, nothing else (see
    the module docstring for why each refusal is needed)."""
    if h.base or h.base_marker is None:
        return False
    if not _ends_at_boundary(h, ENTRY_SECTION_END):
        return False
    ours, theirs = _side_keys(h.ours), _side_keys(h.theirs)
    if ours is None or theirs is None:
        return False
    keys = ours + theirs
    return len(set(keys)) == len(keys)


def _entries(side: list[str]) -> list[tuple[str, list[str]]]:
    """`side` split into (key, lines) entries, each running from a keyed heading to the line before
    the next one. Lines before the first heading (a side's leading blank lines) join the first
    entry. Empty when the side holds no keyed heading."""
    entries: list[tuple[str, list[str]]] = []
    lead: list[str] = []
    for line in side:
        m = KEYED_HEADING.match(line)
        if m:
            entries.append((_key(m), lead + [line]))
            lead = []
        elif entries:
            entries[-1][1].append(line)
        else:
            lead.append(line)
    return entries


def merge_keyed_heading_lines(h: Hunk) -> list[str]:
    """Ours' lines then theirs', unchanged; with every key a numbered ID, the whole entries sorted by
    (letter, number) instead. Always a permutation of `h.ours + h.theirs`."""
    kept = list(h.ours) + list(h.theirs)
    entries = _entries(h.ours) + _entries(h.theirs)
    if not entries or not all(NUMBERED_KEY.fullmatch(key) for key, _ in entries):
        return kept
    entries.sort(key=lambda e: (e[0][0], int(e[0][1:])))
    return [line for _, lines in entries for line in lines]


def _last_updated(lines: list[str]) -> re.Match | None:
    """The `LAST_UPDATED` match of `lines` when it is exactly one such line, else None."""
    return LAST_UPDATED.match(lines[0]) if len(lines) == 1 else None


def is_last_updated_preamble(h: Hunk) -> bool:
    """Ours and theirs are each exactly one `LAST_UPDATED` line, and base (3-way region only) is
    empty or exactly one `*Last updated:` line."""
    if h.base_marker is None or len(h.base) > 1:
        return False
    if h.base and not h.base[0].startswith("*Last updated:"):
        return False
    return _last_updated(h.ours) is not None and _last_updated(h.theirs) is not None


def merge_last_updated_lines(h: Hunk) -> list[str]:
    """One line: the later-dated side's (ours on a tie), verbatim when both sides have the same text
    after the date. Otherwise `*Last updated: <later date><later rest>; <other rest>*`, the other
    side's rest stripped of spaces and leading `—`/`-`, and left out when nothing remains of it.
    A hunk that is not the exact shape keeps both sides' lines."""
    ours, theirs = _last_updated(h.ours), _last_updated(h.theirs)
    if ours is None or theirs is None:
        return list(h.ours) + list(h.theirs)
    later, other = (theirs, ours) if theirs.group(1) > ours.group(1) else (ours, theirs)
    tail = other.group(2).strip(" \t").lstrip("—-").strip(" \t")
    if later.group(2) == other.group(2) or not tail:
        return [later.string]
    return [f"*Last updated: {later.group(1)}{later.group(2)}; {tail}*"]


def extra_label(h: Hunk) -> str | None:
    """The class of `h` when it is one of the two classes of this module, else None."""
    if is_last_updated_preamble(h):
        return "last-updated-preamble"
    if is_keyed_heading_insertion(h):
        return "keyed-heading-insertion"
    return None


def extra_confident(h: Hunk) -> bool | None:
    """Re-verify the predicate for `h.label` (fail closed); None for any other label."""
    if h.label == "last-updated-preamble":
        return is_last_updated_preamble(h)
    if h.label == "keyed-heading-insertion":
        return is_keyed_heading_insertion(h)
    if h.label == "shaped-line-merge":
        return shaped_merge.is_shaped_line_merge(h)
    return None
