#!/usr/bin/env python3
"""THE RESOLVER-SIDE ZERO-DROP RULE, as executable code.

> **A mechanical resolver must never discard a line it does not understand.
> It preserves every input line, or it defers.**

The verifier side of this branch converged on the mirror rule — `atoms()` never subtracts — which
closed six ways the verifier failed to *see* content. This module closes the other direction: the
RESOLVER deleting content and returning RESOLVED. `verify()` cannot backstop that, because a lost
line is only visible to it if the line happens to parse as an atom; plain prose is not an atom of
any kind (known-issue H8). So the rule cannot be a verifier check — it has to hold at the resolver,
for every class, mechanically, whether or not anyone wrote a fixture for the shape.

Three enforcement points, in increasing generality:

1. `CannotPlace` — a resolver that meets a line it cannot represent RAISES rather than inventing a
   fallback. The caller (`resolve.resolve_hunk`) turns that into a DEFER. One signal, one policy,
   decided in one place.
2. `unplaceable()` — the POST-CONDITION, applied to whatever any mechanical resolver returns,
   including resolvers not yet written. A resolver that drops a line without raising still cannot
   ship the result: the hunk defers. This is what makes the rule structural rather than a set of
   patches.
3. `embedded_marker()` — a hunk whose sides OR marker FIELDS are not what a well-formed region
   claims is not valid input for ANY mechanical class (it is the OUTERMOST-wins over-merge of two
   regions, or prose quoting conflict syntax). No mechanical class may claim it.

**What "preserves" means, precisely.** MULTISET containment under a per-class KEY, not equality:
for every line on ours' or theirs' side, the output must carry AS MANY lines of that key as the
input demands. Multiset, not set (S-J3): under set containment a silently DEDUPED duplicate is
invisible, so `log-entry-insertion` and `decision-entry-insertion` — whose licence is *nothing,
verbatim concatenation* — could drop a repeated line and still pass. It is also what makes the
id-renumber key usable (S-J2): that key masks the IDs it rewrote, so two entries differing ONLY in
their ID share a key, and only a COUNT can tell one survivor from two. The BASE side is excluded on
purpose — it is the common ancestor, the version both sides deliberately diverged from; a merge
that re-emitted it would be adding content, not preserving it.

**What each class may legitimately transform** — the whole of the licence, stated once. The
"counts" column is the dedupe licence, stated EXPLICITLY rather than left implicit in a `set()`,
and it now names WHICH KEYS it covers as well as what it permits (S-K2):

| class                        | may rewrite                             | counts                    |
|------------------------------|-----------------------------------------|---------------------------|
| `id-renumber-collision`      | the IDs it renumbered (`L4`->`L5`), in  | exact, every key          |
|                              | the heading and in bare prose xrefs.    |                           |
| `design-inventory-row-merge` | emit ONE row per design id — ours' or   | cross-side on the         |
|                              | theirs', decided against base.          | `<row D<n>>` keys and the |
|                              |                                         | table FRAME; exact on     |
|                              |                                         | every other key           |
| `append-only-log`            | emit the base prefix once; collapse     | cross-side on every key   |
|                              | theirs' tail only when it is byte-      | when the tails are equal; |
|                              | identical to ours' tail (a re-run).     | else cross-side on BASE   |
|                              |                                         | keys only, exact on the   |
|                              |                                         | rest                      |
| `log-entry-insertion`        | emit ONCE the lines both blocks open or | cross-side on the shared  |
|                              | close with (whole shared entries).      | prefix/suffix keys; exact |
|                              |                                         | on every other key        |
| `decision-entry-insertion`   | nothing — verbatim concatenation.       | exact, every key          |
| `keyed-row-insertion`        | nothing — verbatim concatenation.       | exact, every key          |
| `last-updated-preamble`      | two one-line sides become ONE line: the | cross-side on the one     |
|                              | later one, or a union of the two        | `*Last updated:` key      |
|                              | summaries (see below).                  | only                      |
| `low-count-line`             | the two edited count lines become ONE   | cross-side on the one     |
|                              | recomputed `N Low issues \u2192` line (see   | `<low-count>` key         |
|                              | below).                                 |                           |
| `shaped-line-merge`          | per-line merge against BASE: a shaped   | BASE-AWARE: exact, but a  |
|                              | base line a side changed or removed is  | let-go shaped base line   |
|                              | let go; a shared add is placed once.    | and a shared add collapse |

**`last-updated-preamble`** is the one class whose output may be a line NEITHER side wrote: when the
two summaries differ the merge emits `*Last updated: <later date><later summary>; <other summary>*`.
Every `*Last updated:` line keys on ONE constant, so the output must carry at least one such line
(the cross-side `max` of two lines of one key is one); and `overproduced` exempts the result only
when it is exactly one `LAST_UPDATED` line, so a second line or a different invented line is still
reported.

**`low-count-line`** is the second class whose output may be a line NEITHER side wrote: both sides
edited the one `N Low issues \u2192` count line at the end of `known_issues.md`'s Medium section, and
the merge recomputes it as `ours + theirs \u2212 base` (each side added its own Lows to the same base),
keeping ours' text after the arrow verbatim. Every count line keys on ONE constant, so the output
must carry at least one (the cross-side `max` of two lines of one key is one) while every keyed
entry line around it stays at exact multiplicity; and `overproduced` exempts the result only when
exactly ONE output line is a count line, so a second count line or an invented prose line is still
reported. The class predicate refuses anything but that shape — a differing text after the number, a
second count line on a side, a base that is not exactly one count line, or entry blocks that the
entry merge would leave with no blank line before the count line.

**`shaped-line-merge`** is the FIRST BASE-AWARE licence. A side's change to a base line makes the old
line rightly absent from the output, so the count is `(C(ours) & C(theirs) & C(base)) + ((C(ours) -
C(base)) | (C(theirs) - C(base)))`. Only a SHAPED base line (an ID or slug row, never a delimiter row,
or a log bullet, by this module's own predicates) is let go; an unshaped one keeps exact `ours +
theirs`, so `unplaceable` reports it and nothing here raises. The BASE-excluded rule above still holds
for every OTHER class: no other label reads base.

**"Cross-side"** is `max(ours_count, theirs_count)`, and it is the precise statement of the two
collapsing licences (S-J4). `append-only-log` exists to fold a re-run that appended the SAME entry
on both sides — a CROSS-side duplicate. Two entries the same human wrote twice on ONE side are two
entries, and collapsing them is a drop; `max` licenses the first and forbids the second. Round 17
(F5) narrowed its SCOPE: it used to cover every key of the hunk, which let a line both tails merely
happen to share — the `  Approved-by: operator` body line of two DISTINCT changelog entries —
collapse to one copy with nothing reported. It now covers every key only when the two tails are
byte-identical (the re-run, whole); otherwise only the keys of the base prefix, which both sides
carry verbatim and the merge emits once. Every other key is exact.

**Where the row-merge licence applies (S-K2).** `max` used to be applied to every key of an
inventory hunk too, which is strictly more than the sentence above describes. The row merge only
ever asks ours' copy to place theirs' for two things: theirs' row of an id ours also carries, and
the table FRAME both sides repeat (the `| --- |` delimiter row and the header directly above it).
Anything ELSE that happens to appear on both sides — a data row with no design id, a blank, a line
of table-shaped prose — was collapsing to one copy under a RESOLVED verdict with nothing to report
it: `resolve_inventory` placed it by coincidence (it was already in the output) and the hunk-wide
`max` then licensed the count. Those keys are held to EXACT multiplicity now, and `resolve_inventory`
refuses to claim such a line at all rather than placing it by coincidence.

**And the row-merge licence is only sound because the resolver refuses an ambiguous row (S-K1).**
`_row_key` is id-ONLY, so two rows sharing an id share a key and `max` cannot tell one survivor
from two. `resolve_inventory` therefore raises `CannotPlace` when EITHER side carries an id on more
than one row: "theirs' row replaces ours' row of the same id" names no unique row then, and the old
code both DROPPED the row it did not choose and EMITTED theirs' row twice to fill the count. With
that refusal each side carries at most one row per id, so the output carries exactly one — which is
what `max` is being asked to license.

**What checking this twice can and cannot buy — read before trusting `licence_oracle`.**
`licence_oracle` re-reads this licence by a different MECHANISM (field-splitting and character
walking, no regex) so that a mistyped pattern in one is not mistyped identically in the other. It
does NOT and cannot make the check independent of the SPECIFICATION: the licence table above IS the
specification, both modules encode it, and an error in the TABLE is invisible to both. S-K2 was
exactly that failure — checker and oracle applied the same over-broad scope and agreed. So when
this table changes, `licence_oracle` changes with it, and the pair proves consistency of
implementation, never correctness of the licence.

The one check here that shares no specification with the table is `overproduced()`: raw multiset
containment of the output in the input, no key function, no per-class scope. It bounds the output
from ABOVE only — it catches an invented or padded line whatever the licence says, and it can see
no drop at all.

The keys below implement exactly that table and nothing more permissive. They are IDEMPOTENT (a
key applied to an already-transformed output line yields the same key as the input line's), which
is what lets the check compare the two sides with one function.
"""
from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conflict_parse import (  # noqa: E402
    Hunk, MARK_BASE, MARK_CLOSE, MARK_OPEN, MARK_SEP,
)
from keyed_classes import COUNT_LINE, LAST_UPDATED, LOW_COUNT_LABEL  # noqa: E402
from line_shapes import LOG_ENTRY  # noqa: E402

ID_HEADING = re.compile(r"^### ([A-Z])(\d+):")
# `[0-9]`, not `\d` (m-M1) — m-L1's defect moved one question along. m-L1 reconciled the two lanes
# on "is this a delimiter row?"; "does this line carry a design ID?" stayed split, because bare `\d`
# matches every Unicode decimal digit while `licence_oracle.row_id_by_field` requires `isascii() and
# isdigit()`. So `| D１２ | a |` was a data ROW here and a promotable HEADER there: one table, two
# frame sets. ASCII wins — a design ID is ASCII everywhere else in the stack; `\d` was the accident.
# Which way it cuts, since it is NOT m-L1's: a stricter `INV_ROW` makes the frame walk's
# `not INV_ROW.match(prev)` LOOSER, so such a line on a delimiter is now frame — cross-side
# collapsible. (Widening the ORACLE instead makes it a ROW theirs' replaces wholesale — both
# collapse, that one discards more.) `classify.INV_ROW`, `resolve_inventory`'s row-ID oracle, agrees.
INV_ROW = re.compile(r"^\|\s*([A-Z][0-9]+)\s*\|")
SLUG_ROW = re.compile(r"^\|\s*`([a-z0-9][a-z0-9-]*)`")   # | `slug` | ...  (own copy; shaped-line-merge)
DELIM_CELL = re.compile(r"^:?-+:?$")
MARKERS = (MARK_OPEN, MARK_BASE, MARK_SEP, MARK_CLOSE)


class CannotPlace(Exception):
    """A mechanical resolver met an input line it cannot represent in its output.

    Raising is the ONLY correct response — the alternative is each resolver inventing its own
    fallback placement, and "append it somewhere" is how a merge corrupts a document. The caller
    catches this and defers the hunk to a human, unedited.
    """

    def __init__(self, line: str, why: str):
        super().__init__(f"{why}: {line!r}")
        self.line, self.why = line, why


_MARKER_FIELDS = (("open_marker", MARK_OPEN), ("base_marker", MARK_BASE),
                  ("sep_marker", MARK_SEP), ("close_marker", MARK_CLOSE))


def _marker_field_fault(h: Hunk) -> str | None:
    """The first of the hunk's four MARKER FIELDS that is not the marker it claims to be.

    S-J1's lesson: every enforcement layer here read the side LISTS and none ever looked at the
    fields the scan filled in, so a hunk could be cut at a line that merely looked like a marker
    and no layer could tell. Two rules, both about the field's own text:

    * each field must start with ITS OWN marker prefix — a `sep_marker` holding a `|||||||` line
      means the scan mis-assigned the roles, whatever the sides look like;
    * the SEPARATOR must be BARE. git labels the other three (`<<<<<<< ours`, `||||||| base`,
      `>>>>>>> theirs` — the file name or ref) and never the separator: `=======` is emitted alone
      on its line by `git merge-file`, by `git merge`, and by every conflict style. So a
      `sep_marker` carrying a LABEL (`======= see example above`) is a line of CONTENT the scan cut
      the region at, not a separator — the S-I2 shape, caught now at the field rather than only
      when the displaced content happens to land next to another marker.

    Not a totality check by itself; the marker size is configurable (`conflict-marker-size`) and a
    label can be any text, so a `|||||||`-prefixed CONTENT line is indistinguishable from a labelled
    base marker by shape ALONE. That is exactly why the index-stage cross-check in `stage_oracle`
    exists — shape rules are defeasible, the index is not.
    """
    for name, prefix in _MARKER_FIELDS:
        val = getattr(h, name)
        if val is None:
            continue                     # base_marker None == a 2-way region: no section claimed
        if not val.startswith(prefix):
            return val
        if name == "sep_marker" and set(val.strip()) != {"="}:
            return val
    return None


def embedded_marker(h: Hunk) -> str | None:
    """The first conflict marker found INSIDE a hunk's sides — or the first malformed marker
    FIELD (see `_marker_field_fault`) — or None.

    A well-formed `git merge-file --diff3` region never contains another marker in its sides. One
    that does is either the OUTERMOST-wins over-merge (a stray `<<<<<<<` above a genuine region
    makes the scan read one big region whose `ours` contains the real region's markers) or prose
    quoting conflict syntax. Either way the sides are not what they claim to be, so no mechanical
    class may act on them — the merge would be between the wrong two things even if it dropped
    nothing. Base is checked too: a marker there means the same mis-cut.
    """
    for side in (h.ours, h.base, h.theirs):
        for line in side:
            if line.startswith(MARKERS):
                return line
    return _marker_field_fault(h)


def _renumber_key(remap: dict[str, str]):
    """Mask every ID the resolver actually renumbered — both the old and the new spelling — so an
    input line and its renumbered output line share a key.

    The alternation is limited to THIS hunk's remap rather than to `[A-Z]\\d+` in general, so the
    key stays as tight as the licence: an ID the resolver did not touch is still compared
    literally. Lookarounds are the conservative pair `resolvers._apply_xref` uses, so anchors and
    markdown links (`#L4-x`, `[L4](#L4)`) — which the resolver deliberately does NOT rewrite — are
    not masked here either, and a corruption of one would still be reported as a drop.

    **This key is deliberately NOT injective, and the COUNT is what makes it safe** (S-J2).
    `### L4: Bar body` and `### L7: Bar body` share a key whenever both IDs were renumbered, so
    under the old SET containment one survivor accounted for both entries and dropping the other
    was invisible. Inverting the remap on the output line instead — the obvious injective fix —
    was unsound while a remap could CHAIN (`L4->L5`, `L5->L6`): `_apply_xref` maps each reference
    to its DIRECT target in one pass, so an inverse pass rewrites the wrong occurrences. Since
    round 17 `resolve_id_renumber` draws every new ID from above the highest same-letter heading
    in the file's input, so its remaps no longer chain, but this key does not rely on that: it is
    correct for ANY remap.
    Multiset containment restores the missing information without touching the key: no mechanical
    resolver in `resolvers.py` INVENTS a line — every output
    line is an input line, transformed — so dropping one entry strictly lowers the count of its
    key class below the input's, and `unplaceable` reports it. The masking is therefore *lossy
    about which* entry survived and *exact about how many*, which is precisely the licence: the
    class may rewrite an ID, it may not lose an entry.
    """
    ids = sorted(set(remap) | set(remap.values()), key=len, reverse=True)
    if not ids:
        return lambda line: line
    pat = re.compile(rf"(?<![\w#/\[`])(?:{'|'.join(re.escape(i) for i in ids)})(?![\w#/`-])")
    return lambda line: pat.sub("<id>", line)


def _row_key(line: str) -> str:
    """An inventory row keys on its design ID alone — the merge legitimately emits ONE row per id,
    ours' or theirs' (decided against base), which is the class's whole point. Every non-row line
    keys on itself."""
    m = INV_ROW.match(line)
    return f"<row {m.group(1)}>" if m else line


LAST_UPDATED_KEY = "<last-updated>"
LOW_COUNT_KEY = "<low-count>"


def _low_count_key(line: str) -> str:
    """Every `N Low issues \u2192` count line keys on ONE constant: the class emits ONE recomputed line
    for the two it was handed (`ours + theirs \u2212 base`), so a key on the text would see a drop. Any
    other line keys on itself."""
    return LOW_COUNT_KEY if COUNT_LINE.match(line) else line


def _last_updated_key(line: str) -> str:
    """Every `*Last updated:` line keys on ONE constant: the class emits one line for its two
    one-line sides (the later, or a union of both summaries), so a key on the text would see a
    drop. Any other line keys on itself."""
    return LAST_UPDATED_KEY if line.startswith("*Last updated:") else line


def _is_delimiter_row(line: str) -> bool:
    """`| --- | --- |` — a markdown table's delimiter row: every cell is dashes, optionally
    colon-aligned, and nothing else. `|||||||` has no cells and is not one."""
    if not line.startswith("|"):
        return False
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    return bool(cells) and all(DELIM_CELL.match(c) for c in cells)


def table_frame_lines(side: list[str]) -> set[str]:
    """The lines of `side` that are the table's FRAME rather than its content: a delimiter row,
    and the header row directly above one.

    This is the whole of what the row-merge licence means by "both sides carry the same table
    header and `| --- |` separator". It is positional on purpose — the header is identified by
    SITTING ON the delimiter row, not by looking header-ish — so a data row with no design id
    (`| TBD | | | placeholder |`, S-K2) is not frame however table-shaped it is, and is therefore
    held to exact multiplicity like any other content line.
    """
    frame: set[str] = set()
    for i, line in enumerate(side):
        if not _is_delimiter_row(line):
            continue
        frame.add(line)
        prev = side[i - 1] if i else ""
        if prev.startswith("|") and not INV_ROW.match(prev) and not _is_delimiter_row(prev):
            frame.add(prev)
    return frame


def key_for(label: str, renumbered: dict[str, str] | None = None):
    """The per-class key implementing the licence table in the module docstring. Any class not
    named here gets IDENTITY — the strictest key — so a NEW resolver is held to verbatim
    preservation until someone deliberately states its licence.
    """
    if label == "id-renumber-collision":
        return _renumber_key(renumbered or {})
    if label == "design-inventory-row-merge":
        return _row_key
    if label == "last-updated-preamble":
        return _last_updated_key
    if label == LOW_COUNT_LABEL:
        return _low_count_key
    return lambda line: line


# The ONLY four classes licensed to emit FEWER copies of a key than they were handed, and the
# only form that licence takes: `max(ours, theirs)` — a duplicate ACROSS the two sides may
# collapse, a duplicate WITHIN one side may not. Named explicitly rather than left implicit in a
# `set()` comparison, because that implicitness is what hid S-J3 and S-J4. Every other class —
# including any class added later, which is not in this set — is held to exact multiplicity.
CROSS_SIDE_DEDUPE = frozenset(
    {"append-only-log", "design-inventory-row-merge", "last-updated-preamble",
     "log-entry-insertion", LOW_COUNT_LABEL})


def shared_entry_affix(h: Hunk) -> tuple[int, int]:
    """`(k, m)`: ours and theirs both START with the same `k` lines and both END with the same `m`
    lines (`k + m` fits inside the shorter side), each cut at an entry boundary so the affix is
    whole log entries: the line after the prefix is a `LOG_ENTRY` start (or the side's end) on
    BOTH sides, and the suffix's first line is one. A body line two sides share only by
    coincidence (`  Approved-by: operator` under two distinct entries) is never an affix.
    `resolvers.resolve_log_entry_insertion` emits exactly these lines once."""
    ours, theirs = list(h.ours), list(h.theirs)
    limit = min(len(ours), len(theirs))
    k = 0
    while k < limit and ours[k] == theirs[k]:
        k += 1
    while k and not all(i == len(side) or LOG_ENTRY.match(side[i])
                        for side, i in ((ours, k), (theirs, k))):
        k -= 1
    m = 0
    while m < limit - k and ours[-1 - m] == theirs[-1 - m]:
        m += 1
    while m and not LOG_ENTRY.match(ours[-m]):
        m -= 1
    return k, m


def licensed_keys(h: Hunk, key, label: str) -> frozenset[str] | None:
    """The keys of THIS hunk that the class's cross-side-dedupe licence actually covers.

    `None` == every key in the hunk; an empty frozenset == none of them, i.e. exact multiplicity
    throughout. The scope is the `counts` column of the licence table, made executable (S-K2): a
    licence stated for the row and frame keys was being APPLIED to every key of the hunk, so any
    line both sides happened to repeat could collapse unreported.
    """
    if label == "append-only-log":
        n = len(h.base)
        if list(h.ours[n:]) == list(h.theirs[n:]):
            return None        # byte-identical tails: the whole re-run collapses, every key
        return frozenset(key(line) for line in h.base)   # only the prefix both sides repeat
    if label == "design-inventory-row-merge":
        sides = list(h.ours) + list(h.theirs)
        rows = {key(line) for line in sides if INV_ROW.match(line)}
        frame = table_frame_lines(list(h.ours)) | table_frame_lines(list(h.theirs))
        return frozenset(rows | {key(line) for line in frame})
    if label == "last-updated-preamble":
        return frozenset({LAST_UPDATED_KEY})       # the one key, and nothing else
    if label == LOW_COUNT_LABEL:
        return frozenset({LOW_COUNT_KEY})          # the one count line, and nothing else
    if label == "log-entry-insertion":
        k, m = shared_entry_affix(h)          # the whole shared entries, emitted once
        ours = list(h.ours)
        return frozenset(key(line) for line in ours[:k] + ours[len(ours) - m:])
    return frozenset()


def _is_shaped_line(line: str) -> bool:
    """An ID row, a slug row or a log bullet, never a delimiter row: `shaped-line-merge`'s shape set,
    read here independently (this module must not import `shaped_merge`)."""
    return not _is_delimiter_row(line) and bool(
        INV_ROW.match(line) or SLUG_ROW.match(line) or LOG_ENTRY.match(line))


def required_counts(h: Hunk, key, label: str) -> Counter:
    """How many lines of each key the output must carry, per the licence table's `counts` column."""
    ours = Counter(key(line) for line in h.ours)
    theirs = Counter(key(line) for line in h.theirs)
    if label == "shaped-line-merge":
        base = Counter(key(line) for line in h.base)
        counts = (ours & theirs & base) + ((ours - base) | (theirs - base))
        for line in h.base:
            if not _is_shaped_line(line):           # a base line the licence cannot name: exact
                counts[key(line)] = ours[key(line)] + theirs[key(line)]
        return counts
    if label not in CROSS_SIDE_DEDUPE:
        return ours + theirs
    covered = licensed_keys(h, key, label)
    return Counter({k: (max(ours[k], theirs[k]) if covered is None or k in covered
                        else ours[k] + theirs[k])
                    for k in set(ours) | set(theirs)})


def overproduced(h: Hunk, label: str, out_lines: list[str]) -> list[str]:
    """Output lines the INPUT cannot account for — raw multiset containment, one copy per surplus.

    The one check in this module that shares no specification with the licence table: no key
    function, no per-class scope, nothing but "a mechanical resolver moves lines, it does not make
    them up". It is what catches S-K1's second failure — the resolver emitting theirs' row TWICE to
    fill a count `_row_key` licensed — and it would catch it under any scoping of the licence,
    which is exactly the point: a checker and an oracle that share a specification cannot catch an
    error in that specification, so at least one check must not depend on it.

    Bounds the output from ABOVE only. It can see an invented or padded line; it can see no drop at
    all, which is `unplaceable`'s job. `id-renumber-collision` is exempt because it is the only
    class licensed to REWRITE a line's text, so its output lines legitimately are not input lines;
    every other class is a pure rearrangement, base included (`append-only-log` re-emits the base
    prefix, which is a prefix of both sides anyway). `last-updated-preamble` may emit a union line
    neither side wrote, so its result is exempt ONLY when it is exactly one `LAST_UPDATED` line.
    """
    if label == "id-renumber-collision":
        return []
    if label == "last-updated-preamble" and len(out_lines) == 1 and LAST_UPDATED.match(out_lines[0]):
        return []
    src = list(out_lines)
    if label == LOW_COUNT_LABEL:
        counts = [ln for ln in src if COUNT_LINE.match(ln)]
        if len(counts) == 1:
            src.remove(counts[0])     # the one recomputed line; a second is still invention
    surplus = Counter(src) - Counter(list(h.ours) + list(h.base) + list(h.theirs))
    return list(surplus.elements())


def unplaceable(h: Hunk, label: str, out_lines: list[str],
                renumbered: dict[str, str] | None = None) -> list[str]:
    """The POST-CONDITION: the input lines of `h` that `out_lines` does not account for.

    Empty list == the resolution preserved everything it was given. Non-empty == the resolver
    would DROP those lines, and the caller must defer instead of shipping the result.

    MULTISET, not set. A returned line is reported once per MISSING copy: a duplicate that the
    licence does not permit collapsing is a drop like any other, and the previous set containment
    could not see it at all.
    """
    key = key_for(label, renumbered)
    short = required_counts(h, key, label) - Counter(key(line) for line in out_lines)
    if not short:
        return []
    lost = []
    for line in list(h.ours) + list(h.theirs):     # name the actual lines, one per missing copy
        k = key(line)
        if short[k]:
            short[k] -= 1
            lost.append(line)
    return lost
