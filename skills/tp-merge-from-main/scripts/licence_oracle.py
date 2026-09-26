"""THE ORACLE for the resolver's per-class licence — a SECOND reading of the rule under test.

Test-only support module (deliberately not named `test_*`), the counterpart of
`test_verify_superset.py`'s `_naive_atoms`: R0 asks whether a mechanical resolution accounted for
every input line, and if the checker under test (`resolve_totality`) were also the answer key, R0
would assert only that the resolver agrees with itself.

**S-J5 — what independence means here, stated exactly, because it has been overclaimed before.**
The previous oracle was NOT independent: its inventory branch was byte-for-byte `INV_ROW`, the
production pattern, and its ID branch reused the very lookaround pair `resolve_totality._renumber_key`
and `resolvers._apply_xref` use. A boundary bug in either pattern was shared by checker and oracle
alike, and R0 passed vacuously. Both branches here are written by a DIFFERENT MECHANISM: a row's ID
is found by splitting the row into its table FIELDS, and a bare ID reference by WALKING the line and
inspecting the characters either side of each token. No regular expression is involved on this side
at all.

What that does NOT claim: the licence's own boundary RULE — "an ID inside an anchor, a link, a path
or code is not a bare reference" — is shared. It has to be; it is the specification, and any
faithful oracle must encode it. What is eliminated is a shared IMPLEMENTATION of it: a mistyped
character class, a lookbehind that silently permits an empty match, a `match` where `fullmatch` was
meant, an alternation whose longest-first ordering was forgotten. Those are exactly the bugs a
retyped pattern cannot catch and these two can.

**S-K2 — and the limit of that, now demonstrated rather than argued.** This module and
`resolve_totality` SHARE A SPECIFICATION: the licence table in that module's docstring. When the
table said "cross-side dedupe" for `design-inventory-row-merge` and both sides applied it to every
key of the hunk instead of to the row and frame keys the sentence describes, the oracle agreed with
the checker — correctly, by its own lights, and both were wrong. **A second mechanism cannot catch
an error in the specification both mechanisms encode.** So this module is worth exactly one thing:
it proves the two implementations of the licence agree. It proves nothing about whether the licence
is right, and no amount of independence in HOW it is written would change that. The check that does
not depend on the licence at all is `resolve_totality.overproduced` — raw multiset containment of
the output in the input, no key, no scope — and it is deliberately kept out of this module so that
it shares nothing with the table.
"""
from __future__ import annotations

from collections import Counter
from string import ascii_uppercase

_ANCHOR_BEFORE = ("#", "/", "[", "`")     # an ID preceded by one of these is an anchor/link/path
_ANCHOR_AFTER = ("#", "/", "`", "-")      # ...or followed by one: `#L4-heading`

# The classes whose licence permits FEWER copies out than in, and the only form that permission
# takes: a duplicate may collapse ACROSS the two sides (a re-run appended the same entry to both;
# both tables carry the same header row), never WITHIN one side (two entries one author wrote are
# two entries). Every other class is held to exact multiplicity — a deduped duplicate is a drop,
# and under the SET containment this replaces it was invisible (S-J3 / S-J4). Membership here says
# the class HAS the licence; `collapsible_keys` says which of the hunk's keys it reaches (S-K2).
MAY_COLLAPSE_A_CROSS_SIDE_DUPLICATE = ("append-only-log", "design-inventory-row-merge")


def mask_bare_ids(line: str, touched) -> str:
    """Mask every BARE occurrence of a touched ID by walking the line, character by character."""
    out, i, n = [], 0, len(line)
    while i < n:
        if not (line[i].isalnum() or line[i] == "_"):
            out.append(line[i])
            i += 1
            continue
        j = i
        while j < n and (line[j].isalnum() or line[j] == "_"):
            j += 1
        token = line[i:j]                          # a MAXIMAL word run, so `L45` is not `L4`
        before = line[i - 1] if i else ""
        after = line[j] if j < n else ""
        bare = before not in _ANCHOR_BEFORE and after not in _ANCHOR_AFTER
        out.append("<id>" if token in touched and bare else token)
        i = j
    return "".join(out)


def row_id_by_field(line: str) -> str | None:
    """A table row's design ID, found by splitting on the column delimiter — no pattern matching.

    A row is `| <id> | ... |`, so its ID is the FIRST field of a line that opens with a delimiter
    and carries at least one more. An ID is one uppercase ASCII letter followed by ASCII digits; a
    first field that is anything else (`| 3 |` from the Current-Focus table, `| --- |`, a header
    cell) is not an ID, and the line is then not a row.
    """
    if not line.startswith("|"):
        return None
    fields = line.split("|")
    if len(fields) < 3:
        return None
    token = fields[1].strip()
    head, digits = token[:1], token[1:]
    if head and head in ascii_uppercase and digits and digits.isascii() and digits.isdigit():
        return token
    return None


def _is_delimiter_cell(cell: str) -> bool:
    """One cell of a delimiter row: a run of dashes, optionally colon-aligned on either end.

    m-L1. This used to accept ANY non-empty cell drawn from `-` and `:`, which made it strictly
    looser than `resolve_totality._is_delimiter_row`'s `^:?-+:?$` — so `| :: |`, `| -:- |` and
    `| : |` were delimiter rows to the oracle and content to the resolver, and the two produced
    DIFFERENT frame sets on the same table. A cross-check whose halves disagree about what they are
    checking is not a cross-check. The STRICTER rule wins: a delimiter cell must contain at least
    one dash, because that is what markdown actually renders as a column rule and what the
    resolver's licence has always meant by "the `| --- |` separator" — widening the oracle would
    have widened the frame, and the frame is the one place a cross-side collapse is licensed.

    Still decided by INSPECTING THE CHARACTERS rather than by importing the resolver's regex: the
    oracle's value is that it reaches the same answer by its own mechanism, so agreement is
    evidence. `test_resolve_licence` asserts the two agree cell-shape by cell-shape.
    """
    body = cell[1:] if cell.startswith(":") else cell
    body = body[:-1] if body.endswith(":") else body
    return bool(body) and set(body) == {"-"}


def is_delimiter_row(line: str) -> bool:
    """A markdown delimiter row (`| --- | --- |`): every cell is a delimiter cell."""
    if not line.startswith("|"):
        return False
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    return bool(cells) and all(_is_delimiter_cell(cell) for cell in cells)


def frame_lines(side) -> set:
    """The table FRAME of `side`: each delimiter row, plus the header row sitting directly on it.

    The other half of the row-merge licence's SCOPE (S-K2). A line is frame because of WHERE it is
    — a header is the pipe line immediately above a delimiter row — so a data row that carries no
    design id is content, not frame, however table-shaped it looks.
    """
    out = set()
    for i, line in enumerate(side):
        if not is_delimiter_row(line):
            continue
        out.add(line)
        prev = side[i - 1] if i else ""
        if prev.startswith("|") and row_id_by_field(prev) is None and not is_delimiter_row(prev):
            out.add(prev)
    return out


def collapsible_keys(hunk, key, label):
    """The keys the class's cross-side licence covers — `None` meaning all of them.

    `append-only-log` collapses across sides for every key only when the two appended tails are
    the same lines in the same order (a re-run); otherwise only the base prefix's keys, which both
    sides repeat and the merge emits once (F5). The row merge collapses only for the `<row Dn>`
    keys and the frame; every other key of the hunk is exact, so a line the two sides merely happen
    to share cannot collapse unreported.
    """
    if label == "append-only-log":
        base = list(hunk.base)
        ours_tail, theirs_tail = list(hunk.ours)[len(base):], list(hunk.theirs)[len(base):]
        if len(ours_tail) == len(theirs_tail) and all(
                a == b for a, b in zip(ours_tail, theirs_tail)):
            return None
        return {key(line) for line in base}
    if label == "design-inventory-row-merge":
        sides = list(hunk.ours) + list(hunk.theirs)
        rows = {key(line) for line in sides if row_id_by_field(line) is not None}
        frame = frame_lines(list(hunk.ours)) | frame_lines(list(hunk.theirs))
        return rows | {key(line) for line in frame}
    return set()


def oracle_key(label: str, renumbered: dict | None):
    """What each mechanical class is ALLOWED to change about a line. The licence, in full:

      * `id-renumber-collision` may rewrite the IDs it renumbered — in the `### L4:` heading and in
        bare prose cross-references — and nothing else on the line. IDs it did NOT renumber, and
        the anchor/link forms it deliberately leaves alone, are compared literally.
      * `design-inventory-row-merge` may emit ONE row per `| D<n> |` id — ours' or theirs'.
      * every other class may change nothing at all: identity.
    """
    if label == "id-renumber-collision":
        touched = set(renumbered or {}) | set((renumbered or {}).values())
        return lambda line: mask_bare_ids(line, touched)
    if label == "design-inventory-row-merge":
        return lambda line: (f"<row {row_id_by_field(line)}>" if row_id_by_field(line) else line)
    return lambda line: line


def lost_lines(hunk, result) -> list[str]:
    """The lines of `ours`/`theirs` that `result` does not account for, per this oracle.

    MULTISET containment: the per-key MAXIMUM where the class's licence covers that key (the
    cross-side collapse, exactly) and the SUM everywhere else (exact multiplicity), minus what the
    output carries. `result` need only carry `.label`, `.renumbered` and `.lines`, so a
    counterfactual resolver can be checked by standing in for a `HunkResult`.
    """
    key = oracle_key(result.label, result.renumbered)
    ours = Counter(key(line) for line in hunk.ours)
    theirs = Counter(key(line) for line in hunk.theirs)
    collapsible = (collapsible_keys(hunk, key, result.label)
                   if result.label in MAY_COLLAPSE_A_CROSS_SIDE_DUPLICATE else set())
    need = Counter()
    for k in set(ours) | set(theirs):
        need[k] = (max(ours[k], theirs[k]) if collapsible is None or k in collapsible
                   else ours[k] + theirs[k])
    return list((need - Counter(key(line) for line in result.lines)).elements())
