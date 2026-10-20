#!/usr/bin/env python3
"""The line shapes a keep-both merge may emit (round 22, T1), and the entry and heading shapes the
classifier reads (moved here from `classify` in round 23; `classify` re-exports them).

Three classes merge by keeping both sides verbatim, ours' lines then theirs':
`log-entry-insertion`, `decision-entry-insertion`, and `append-only-log` (ours' tail then theirs'
after the shared base). No byte is lost, so the verifier, the stage oracle and both certifiers
accept the result. What can still change is how the merge RENDERS, at the one adjacency the merge
creates and neither side had: ours' last line followed by theirs' first line. Each class predicate
makes theirs' first non-blank line an entry start (a `- **…** —` bullet or a `### [tag]` heading;
an `append-only-log` tail may instead be whitespace only, and then holds nothing that could be
swallowed and is not held to this module), and a heading or a list item ends a paragraph, a table
and a block quote. It does NOT end an HTML
block (which runs until a blank line, or until its end condition such as `-->` or `</pre>`) or a
fenced code block (which runs until its closing fence). So when ours' block ended inside one of
those, theirs' entry rendered as literal text inside it: `</details>` as ours' last line, directly
followed by theirs' bullet, swallowed the bullet into ours' HTML block, and every check passed.
And a heading anywhere on ours' side puts theirs' entries in that heading's section.

`keep_both_refusal` holds each side to a small allowlist instead of chasing constructs one by one.
Every line must be one of:

1. **the class's entry start** (`LOG_ENTRY` / `DECISION_ENTRY`);
2. **plain** (a blank line is plain). Read its text past ALL leading whitespace (`str.lstrip()`,
   so a list continuation and a 4-space line are held to the same test as an unindented one),
   then past each list marker (`- `, `* `, `+ `, `1. `, `1) `, a tab after the marker too,
   repeated). No step of that reading, starting with the whitespace-stripped text itself, may be
   **heading-shaped** (round 23): `#` to `######` then a space, a tab or nothing (`ATX_SHAPE`, an
   ATX heading), or only `-` or only `=` then spaces or tabs (`SETEXT_SHAPE`, a setext underline).
   This refuses a heading at ANY indentation, because CommonMark counts a list item's indentation
   from its content column, so `    ## Archive` under `- **…** — ours` is an h2 inside ours' list
   item. **One exemption**, for the setext shape only: it is admitted when the line directly above
   it ON THE SAME SIDE is blank (spaces, tabs, a CRLF `\\r`; `_blank`). A setext underline must
   directly follow a paragraph line, and a blank line closes every paragraph at every nesting
   level, so the line is a thematic break, an empty list item, indented code or paragraph text,
   never a heading that could put theirs' entry in its section. The side's first
   line has nothing known above it and is refused. (Checked with markdown-it over 22176 variants:
   blank lines at any indentation and inside nested list items, underlines indented 0-8 columns or
   by tabs, behind list markers, with and without a line after it and a blank before theirs'
   entry. None made a heading, and theirs' entry rendered in the same block path as on its own
   side and as with a plain word in that line's place.) And the text left after the last list
   marker does not begin with a token that opens a block:
   * `<` — an HTML block;
   * three or more `` ` `` or `~` — a fenced code block;
   * `>` — a block quote (refused although a heading or list item ends one: no keep-both hunk in
     this repository's merge history carries one, so it costs nothing to leave out);
   * `$$` — GitHub's display-math delimiter;
   and it is not **definition-like**: holding `]:` when its text begins with `[`, or holding `]:`
   with no unescaped `[` before its FIRST `]:` (the end of a label begun on an earlier line). A
   link reference or footnote definition applies to the WHOLE document, so one on ours' side
   would retarget or create links in theirs' entries.

The heading and block-opener tests in 2 read a line only at its START (past its indentation and
list markers); only the definition test looks further along it. So an unclosed inline raw HTML
element later in a line (`**Decided**: wrap long evidence in <details> blocks`, an unclosed `<s>`,
`<b>` or `<a href>`) is admitted, and is an accepted residual: on GitHub's renderer it can
visually wrap the lines after it, theirs' following entry included (it already renders oddly on
ours' own side). It is not refused because a mid-line `<placeholder>` in ordinary text is common.

And on EVERY line, blank or not, a carriage return may appear only once, as the last character,
where it is dropped before the tests above. CommonMark ends a line at a bare `\\r`, but the parse
splits on `\\n` only, so `body\\r## Won't Fix` would hide a heading from every check above, and
`row\\r\\r` a blank line (`has_stray_cr`, which `table_run` applies to the inventory class too).

**The cost.** The allowlist refuses by a line's first token, not by parsing the block: a balanced
fence or a one-line `<!-- … -->` comment inside an inserted entry, a `> ` operator reply, a
`<wt>/…` path at a line's start, or a `---` rule under a non-blank line defers the whole FILE to a
human although none of them can swallow the other side's entry. Measured over the 1814 decision
entries in this repository's `decisions.md` files (round 23, with the setext exemption): 27 (1.5%)
carry such a line, each a fence, an HTML line or a block quote; without the exemption 68 more, all
a `---` separator directly below a blank line, deferred. No log entry in the living docs carries
one.

`classify._line_is_foreign` refuses headings too, as it did before this module, but only indented
0-3 spaces (`_heading_at`); for these three classes `ATX_SHAPE` and `SETEXT_SHAPE` are the wider
test. A table line (`|`) is admitted: a GFM table ends at the first line that starts another block, which theirs'
entry start always is, and refusing `|` would have deferred 2 of the 8 `decision-entry-insertion`
hunks the real-merge replay resolves (one merge's decision entry, which the replay runs in both
side orders, carries a results table). A pipe-less table row begins with ordinary text and is
admitted for the same reason. Stdlib only.
"""
from __future__ import annotations

import re
from typing import Iterator

# ---- entry and heading shapes (classify's; here since round 23) ----------------------------------
# Every START of an entry or a heading is spelled with `[ \t]`, never `\s` (round 23): Python's `\s`
# is Unicode, and a line like `-<NBSP>**2026-02-11** — …` or `###<NBSP>[tag] t` is paragraph text to
# CommonMark (a lazy continuation of the entry above it), not a list item or a heading.
#
# A log entry is a bold-lead bullet — the REAL append-only-log shape in the living docs. Two forms:
#   dated      `- **2026-07-05** — …`   (architecture.md `## History`, roadmap `## Roadmap History`)
#   name-keyed `- **`design-slug`** — …` (product_roadmap.md `### Recent completions`)
# The name-keyed arm is a kebab design-slug (`[a-z0-9][a-z0-9-]*`), which EXCLUDES file-path
# description bullets like `- **`scripts/foo.py`** — …` (those carry `/` / `.`, deferring to a human).
#   plain-date `- 2026-10-16 — …`       (a History / archive bullet with no bold lead)
LOG_ENTRY = re.compile(
    r"^-[ \t]+(?:\*\*(?:`[a-z0-9][a-z0-9-]*`|\d{4}-\d{2}-\d{2})\*\*|\d{4}-\d{2}-\d{2})[ \t]+—")
# A column-0 ATX heading. Used where a heading is ACCEPTED (`classify._ends_at_boundary`: the line
# after a log region may be one), so it stays narrow: an INDENTED `  ## x` after a list item can be
# that item's own content, and accepting it would let the line move between entries.
ATX_HEADING = re.compile(r"^#{1,6}[ \t]")
# Where a heading is REFUSED by `classify._heading_at` (every purity predicate, the gated
# `id-renumber-collision` one included), the test is the CommonMark one for a line that is not
# inside a list item, widened rather than narrowed (round 20): an ATX heading indented 0-3 spaces,
# including an empty `#`, and a setext underline (`---` / `===`) directly under a non-blank line.
# Column-0 ATX alone let `  ## Won't Fix` or `Won't Fix\n---` pass as body. A refusal may use `\s`.
FOREIGN_ATX = re.compile(r"^ {0,3}#{1,6}(?:\s|$)")
SETEXT_UNDERLINE = re.compile(r"^ {0,3}(?:-+|=+)\s*$")
# A heading that ENDS a `###`-level entry (an `### L<n>:` or a `### [tag]` entry): an ATX heading of
# level 1-3. A `####` heading is a sub-section of the entry above it, so it ends nothing.
ENTRY_SECTION_END = re.compile(r"^#{1,3}[ \t]")
# A decision-log entry heading — the `### [{skill-name}] <title>` shape `auto-mode.md` prescribes
# for `three-pillars-docs/tp-designs/*/decisions.md`. Written independently of `verify.py`'s own
# DECISION_ENTRY regex: the resolver and the verifier are deliberately separate observers, so a
# too-narrow regex here cannot become a common-mode failure there.
DECISION_ENTRY = re.compile(r"^### \[[^\]]+\][ \t]+\S")

# ---- the keep-both allowlist --------------------------------------------------------------------
LEADING_SPACE = re.compile(r"\s*")     # what `str.lstrip()` strips: every `str.isspace()` character
LIST_MARKER = re.compile(r"(?:[-+*]|[0-9]{1,9}[.)])(?:[ \t]+|$)")
ATX_SHAPE = re.compile(r"#{1,6}(?:[ \t]|$)")
SETEXT_SHAPE = re.compile(r"(?:-+|=+)[ \t]*$")
BLOCK_OPENERS = (("<", "an HTML block"), ("```", "a fenced code block"),
                 ("~~~", "a fenced code block"), (">", "a block quote"),
                 ("$$", "a display-math block"))
UNESCAPED_BRACKET = re.compile(r"(?<!\\)\[")


def has_stray_cr(line: str) -> bool:
    """`line` holds a carriage return anywhere but as its single last character."""
    return "\r" in (line[:-1] if line.endswith("\r") else line)


def _readings(line: str) -> Iterator[int]:
    """The offsets in `line` past its indentation, then past each list marker in turn: every place
    a block inside it could begin, yielded one at a time. The last one is where a block opener is
    looked for. Offsets, not slices (round 24): keeping the text after every marker held O(n²)
    characters for a line of n markers, about 3 GB for a 120 KB `- - - … x` line, and slicing that
    text at each marker without keeping it would still copy O(n²) characters. Each step here scans
    only the marker and the whitespace after it."""
    at = LEADING_SPACE.match(line).end()
    yield at
    while (m := LIST_MARKER.match(line, at)) is not None:
        at = LEADING_SPACE.match(line, m.end()).end()
        yield at


def _blank(above: str | None) -> bool:
    """`above` is a line of the same side (not None) that CommonMark reads as blank: spaces, tabs
    and a CRLF line ending's `\\r` only. NBSP and other Unicode spaces are text to CommonMark."""
    return above is not None and not has_stray_cr(above) and not above.strip(" \t\r")


def _definition_like(line: str, start: int) -> bool:
    """`line` holds `]:`, and its text from `start` (the last reading) begins with `[` or no
    unescaped `[` comes before its first `]:`."""
    at = line.find("]:")
    if at < 0:
        return False
    return line.startswith("[", start) or UNESCAPED_BRACKET.search(line, 0, at) is None


def line_refusal(line: str, entry: re.Pattern, above: str | None = None) -> str | None:
    """Why `line` is none of the admitted shapes, or None. `above` is the line directly above it on
    the SAME side, None when `line` is the side's first line (what is above it is not known)."""
    if has_stray_cr(line):
        return "holds a carriage return inside the line, which ends a line to CommonMark"
    if entry.match(line):
        return None
    body = line[:-1] if line.endswith("\r") else line
    underline_admitted = _blank(above)
    # Each reading is tested as it is produced, and the first heading-shaped one refuses. That is
    # the refusal testing every reading for ATX before any for setext gives: a setext-shaped reading
    # is `-` or `=` characters then spaces or tabs, so a reading after it, if any, is empty.
    for at in _readings(body):
        if ATX_SHAPE.match(body, at):
            return ("is heading-shaped at some indentation or inside a list item (an ATX heading), "
                    "so theirs' entry could render in its section")
        if not underline_admitted and SETEXT_SHAPE.match(body, at):
            return ("is heading-shaped at some indentation or inside a list item (a setext "
                    "underline not directly below a blank line of its side), so theirs' entry "
                    "could render in its section")
    for token, what in BLOCK_OPENERS:
        if body.startswith(token, at):
            return f"opens {what} ({token!r}), which theirs' entry could render inside"
    if _definition_like(body, at):
        return "looks like a link reference or footnote definition, which applies document-wide"
    return None


def keep_both_refusal(side: list[str], entry: re.Pattern) -> str | None:
    """Why `side` may not be emitted next to the other side's lines, or None: the first line that
    holds a carriage return inside it, or is neither an `entry` start nor plain (see the module
    docstring)."""
    for i, line in enumerate(side):
        why = line_refusal(line, entry, side[i - 1] if i else None)
        if why is not None:
            return f"{line!r} {why}"
    return None


def focus_context(pre_context: str) -> bool:
    """`pre_context` names a Current-Focus / priority section: the table-type disambiguator."""
    return any(k in pre_context for k in ("Current Focus", "Priority", "Next Action"))
