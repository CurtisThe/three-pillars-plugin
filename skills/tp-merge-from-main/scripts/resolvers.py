#!/usr/bin/env python3
"""The five MECHANICAL resolvers — one function per mechanical class, plus `HunkResult`.

`resolve_id_renumber` is DORMANT: its class is in `classify.GATED` (round 20), so
`resolve.resolve_hunk` defers every `id-renumber-collision` hunk before reaching it (outside
`force=True`, the unsafe counterfactual no merge path uses). It is kept, and tested, for whoever
un-gates the class; see `classify.GATED` for what that would take.

Split out of `resolve.py` (round 17) by responsibility: `resolve.py` decides WHETHER a hunk may be
resolved mechanically (the gates, the totality post-conditions, deferral); this module decides
HOW each class merges once it may. `resolve` re-exports every public name here, so
`from resolve import resolve_inventory, HunkResult, MECH_RESOLVERS` keeps working unchanged.

A resolver that meets input it cannot merge without guessing RAISES `CannotPlace`; the caller
(`resolve.resolve_hunk`) turns that into a verbatim deferral. Every result is then checked against
its own input by `resolve_totality` before it ships, so a resolver's docstring is a statement of
intent that the post-conditions enforce, not the enforcement itself.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from classify import (  # noqa: E402
    Hunk, ID_HEADING, INV_ROW, _is_append_only_log, _is_id_renumber_collision,
    _is_inventory_row_merge,
)
from resolve_totality import CannotPlace, table_frame_lines  # noqa: E402
from table_run import appended_rows_refusal, table_run_refusal  # noqa: E402

RESOLVED, DEFER = "RESOLVED", "DEFER"


@dataclass
class HunkResult:
    label: str
    status: str            # RESOLVED | DEFER
    lines: list[str]
    reason: str = ""
    renumbered: dict = field(default_factory=dict)   # {old_id: new_id} for audit
    code: str = ""         # one of resolve.DEFER_CODES when status == DEFER; "" when RESOLVED


# ---- entry parsing + ID rewriting ----------------------------------------------------------

def split_entries(lines: list[str]) -> list[tuple[str | None, list[str]]]:
    """Split a block into (id, block-lines) by `### L<n>:` headings. Pre-heading lines get id=None."""
    out: list[tuple[str | None, list[str]]] = []
    cur_id, cur = None, []
    for line in lines:
        m = ID_HEADING.match(line)
        if m:
            if cur:
                out.append((cur_id, cur))
            cur_id, cur = m.group(1) + m.group(2), [line]
        else:
            cur.append(line)
    if cur:
        out.append((cur_id, cur))
    return out


def _trim_trailing_blanks(block: list[str]) -> list[str]:
    end = len(block)
    while end and not block[end - 1].strip():
        end -= 1
    return block[:end]


def _retag(block: list[str], letter: str, new_n: int) -> list[str]:
    out, done = [], False
    for line in block:
        if ID_HEADING.match(line) and not done:
            out.append(ID_HEADING.sub(rf"### {letter}{new_n}:", line, count=1))
            done = True
        else:
            out.append(line)
    return out


def _xref_pattern(ids) -> re.Pattern:
    """A BARE prose reference to any of `ids` — the only form `_apply_xref` rewrites.

    An anchor/link/path/code ID is always prefixed by `# / [ \\``, so the lookbehind excludes those
    (plus word chars); the lookahead excludes word chars, `-`, `/`, `#`, `\\`` (a trailing
    hyphen-anchor or path). So `see L5`, `(L5)` and `L5.` match and `#L5-x` / `[L5](#L5)` do not.
    """
    alt = "|".join(re.escape(k) for k in sorted(ids, key=len, reverse=True))
    return re.compile(rf"(?<![\w#/\[`])(?:{alt})(?![\w#/`-])")


def _any_occurrence(ident: str) -> re.Pattern:
    """EVERY occurrence of `ident` as a token, whatever surrounds it — bare, anchor, link or path,
    in EITHER case. Deliberately broader than `_xref_pattern`: it is used to REFUSE, so it errs
    towards seeing. Case-insensitive because a GitHub heading anchor is lowercased — `### L5: retry
    flake` is linked as `#l5-retry-flake` — and a case-sensitive scan missed such a link, which then
    dangled at the other side's entry (round 18)."""
    return re.compile(rf"(?<![A-Za-z0-9_]){re.escape(ident)}(?![0-9])", re.IGNORECASE)


def _apply_xref(lines: list[str], remap: dict[str, str]) -> list[str]:
    """Rewrite *bare prose* `L<old>` cross-references to their renumbered IDs, in ONE atomic pass.

    Single-pass: one alternation over the old keys, each match looked up in `remap`, so every
    reference maps to its DIRECT target exactly once. (`resolve_id_renumber` draws every new ID
    from above the highest same-letter heading in the file's input, so within one region its
    remaps cannot chain; the single pass is kept because it is correct for any remap.)
    """
    if not remap:
        return lines
    pat = _xref_pattern(remap)
    return [pat.sub(lambda m: remap[m.group(0)], line) for line in lines]


# ---- mechanical resolvers --------------------------------------------------------------------

def resolve_id_renumber(h: Hunk) -> HunkResult:
    """Keep ours' entries verbatim, then theirs'; renumber each theirs entry whose ID COLLIDES with
    one of ours' new IDs to a fresh number, rewriting theirs' bare references to it. Zero-drop.

    GATED since round 20, so no merge path calls it: every reference and ID check below reads ONE
    file, while living-doc IDs are cited and spent across several docs, and on a base-sync theirs
    is the base branch, whose entry has already landed. `classify.GATED` has the full reasoning.

    The classifier (`classify._is_id_renumber_collision`) admits only an EMPTY base, two sides that
    are each whole ID-headed entries and nothing else, a section boundary (or EOF) after the region,
    headings of one letter and at least one colliding ID; this resolver re-checks that same
    predicate, so a hand-built hunk cannot skip it. Every other rule below is a refusal
    (`CannotPlace`) for a case where a renumber would have to GUESS:

    * **An ID repeated on one side.** `remap` is keyed by the old ID, so a repeat cannot be
      represented; `_apply_xref` would point both entries' references at one new number.
    * **A theirs entry byte-identical to an ours entry** (trailing blank lines aside). It is the
      same entry added on both branches, and renumbering it keeps one entry twice under two IDs
      (`### L67: X` and a verbatim `### L69: X`); which ID it should keep is the human's call.
    * **An ID that is already a heading elsewhere in the file** (`h.context`). The file then has
      that entry twice before any renumber, and no rewrite can say which one a reference means.
    * **A reference to a renumbered ID that the rewrite cannot reach**: any occurrence, in either
      case, OUTSIDE this region (it could mean ours' entry or theirs'), or an anchor/link/path or
      lower-case form inside theirs' side (`[L4](#l4-x)` — left literal, it would silently point
      at ours' entry).
    * **A chosen new ID the file already mentions.** New numbers start above the highest
      same-letter heading in this file's INPUT — the clean text plus every region's three sides
      (F4b: the in-hunk maximum reused an ID a clean region already carried) — and a chosen ID
      that occurs as any token of that input is refused rather than skipped past.

    What this function cannot see is the OTHER regions' output: it reads their input sides, so two
    renumbering regions of one file can each draw the same "free" number (R1: two `### L69:`).
    `resolve.resolve_file` therefore refuses every renumber in a file where more than one region
    renumbers, and checks the assembled output for a duplicated renumbered heading as a backstop.

    Only colliding IDs move (F4c); theirs' other IDs are new and unique already. Theirs' entries
    are therefore not guaranteed to be numbered monotonically in document order, and the result
    says exactly which IDs moved in `renumbered`.
    """
    ours_e, theirs_e = split_entries(h.ours), split_entries(h.theirs)
    for side, entries in (("ours", ours_e), ("theirs", theirs_e)):
        ids = [i for i, _b in entries if i]
        dup = next((i for i in ids if ids.count(i) > 1), None)
        if dup is not None:
            raise CannotPlace(next(b[0] for i, b in entries if i == dup),
                              f"{side} carries the ID {dup} twice, so the renumber map is not a "
                              f"function of the old ID and the rewrite cannot be stated")
    ours_ids = [i for i, _b in ours_e if i]
    theirs_ids = [i for i, _b in theirs_e if i]
    letters = {i[0] for i in ours_ids + theirs_ids}
    colliding = [i for i in theirs_ids if i in set(ours_ids)]
    if not _is_id_renumber_collision(h):
        raise CannotPlace(h.theirs[0] if h.theirs else "",
                          "not a same-letter collision between two sets of whole new entries (see "
                          "classify._is_id_renumber_collision)")
    ours_blocks = {tuple(_trim_trailing_blanks(b)) for i, b in ours_e if i}
    twin = next((b for i, b in theirs_e if i and tuple(_trim_trailing_blanks(b)) in ours_blocks),
                None)
    if twin is not None:
        raise CannotPlace(twin[0], "theirs adds an entry byte-identical to one of ours'; "
                                   "renumbering it would keep the same entry twice under two IDs")
    letter = letters.pop()
    elsewhere = {m.group(1) + m.group(2) for m in map(ID_HEADING.match, h.context) if m}
    for i in ours_ids + theirs_ids:
        if i in elsewhere:
            raise CannotPlace(i, f"{i} is already a heading elsewhere in the file")
    for old in colliding:
        outside = next((ln for ln in h.context if _any_occurrence(old).search(ln)), None)
        if outside is not None:
            raise CannotPlace(outside, f"{old} is referenced outside the conflict region, where "
                                       f"the rewrite cannot tell ours' {old} from theirs'")
        bare = _xref_pattern([old])
        for ln in h.theirs:
            if len(_any_occurrence(old).findall(ln)) != len(bare.findall(ln)):
                raise CannotPlace(ln, f"theirs refers to {old} in an anchor/link/path form the "
                                      f"rewrite does not reach")
    doc = [*h.context, *h.ours, *h.base, *h.theirs]
    used = [int(m.group(2)) for m in map(ID_HEADING.match, doc) if m and m.group(1) == letter]
    remap: dict[str, str] = {}
    nxt = max(used) + 1
    for old in colliding:
        new = f"{letter}{nxt}"
        hit = next((ln for ln in doc if _any_occurrence(new).search(ln)), None)
        if hit is not None:
            raise CannotPlace(hit, f"the next free ID {new} is already mentioned in the file")
        remap[old] = new
        nxt += 1

    merged: list[str] = [line for _id, block in ours_e for line in block]
    for _id, block in theirs_e:
        block = _apply_xref(block, remap)
        if _id in remap:
            block = _retag(block, letter, int(remap[_id][1:]))   # no-op confirmation of the xref
        merged += block
    return HunkResult("id-renumber-collision", RESOLVED, merged, renumbered=remap)


def _rows(side: list[str], name: str) -> dict[str, str]:
    """`{design id: row}` for one side, refusing a side that carries an id on more than one row —
    "the row of an id" names no unique row then (S-K1)."""
    out: dict[str, str] = {}
    for line in side:
        m = INV_ROW.match(line)
        if m is None:
            continue
        if m.group(1) in out:
            raise CannotPlace(line, f"{name} carries the design ID {m.group(1)} on more than one "
                                    f"row, so there is no single row for theirs' row to replace")
        out[m.group(1)] = line
    return out


def resolve_inventory(h: Hunk) -> HunkResult:
    """A THREE-WAY row merge keyed by design ID: each row is decided against BASE.

    What it is NOT: zero-drop at the line level. When theirs changed a row ours left as base, the
    output carries theirs' row in place of ours' — ours' copy of that line is not emitted. What
    makes that sound is that the line it replaces is BASE content ours never touched, so nothing
    ours authored is lost; the verdict is per row, and exactly these outcomes resolve:

    | ours vs base | theirs vs base      | output row                          |
    |--------------|---------------------|-------------------------------------|
    | unchanged    | unchanged / changed | theirs' (== base when unchanged)    |
    | changed      | unchanged           | ours'                               |
    | changed      | changed identically | theirs' (== ours')                  |
    | added        | absent              | ours'                               |
    | absent       | added               | theirs', appended after ours' block |
    | added        | added identically   | ours' (== theirs'), once            |
    | deleted      | deleted             | none — both sides agree             |

    Everything else REFUSES (F3): both sides changed a row differently, both added the same id
    with different rows, or ONE side deleted a row the other kept (keeping it resurrects a
    deletion; dropping it discards the other side's row). The previous resolver never read
    `h.base` and always preferred theirs, so it reverted an ours-only edit whenever theirs' row was
    still base, and re-added a row ours had deleted.

    Non-row lines: ours' block is emitted in full, in order (an opening header and `| --- |`, and
    any non-ID row); a theirs non-row line is placeable only as the table FRAME ours already
    carries, and a non-blank base non-row line one side deleted and the other kept refuses for the
    same reason a row does.

    **Where an appended row lands** (round 21, S1). Row swaps keep ours' positions, but an appended
    row gets a new neighbour, and a row's TABLE is where it sits: a blank line ends a table, and a
    delimiter row makes the line above it a header. This resolver re-checks the class predicate
    (`classify._is_inventory_row_merge`), whose `table_run.table_run_refusal` refuses a blank line,
    a line of pipes only or a carriage return inside a line on either side, a delimiter row anywhere
    but in a frame opening its side, and two sides that do not open with the same frame; and it
    refuses to append when the line directly after the region is unknown, a delimiter row, or holds
    a carriage return inside it (`table_run.appended_rows_refusal`). Before that, a row
    theirs added was appended after ours' new blank line (outside the table) or under ours' new
    second table's header, and every downstream check passed, because no line was missing.
    """
    ours, base, theirs = _rows(h.ours, "ours"), _rows(h.base, "base"), _rows(h.theirs, "theirs")

    def decide(k: str) -> str | None:
        o, b, t = ours.get(k), base.get(k), theirs.get(k)
        if b is None:
            if o is not None and t is not None and o != t:
                raise CannotPlace(t, f"both sides added design ID {k} with different rows")
            return o if o is not None else t
        if o is None or t is None:
            if o is None and t is None:
                return None
            raise CannotPlace(o or t, f"one side deleted the row of design ID {k} and the other "
                                      f"kept it")
        if o == b or o == t:
            return t
        if t == b:
            return o
        raise CannotPlace(t, f"both sides changed the row of design ID {k} differently")

    if not _is_inventory_row_merge(h):
        raise CannotPlace(h.theirs[0] if h.theirs else "",
                          table_run_refusal(h) or "not rows of one inventory table on every side "
                                                  "(see classify._is_inventory_row_merge)")
    o_set, t_set = set(h.ours), set(h.theirs)          # membership only: linear, not base x sides
    for line in h.base:
        if line.strip() and INV_ROW.match(line) is None and (line in o_set) != (line in t_set):
            raise CannotPlace(line, "one side deleted a non-row table line the other kept")
    out_lines: list[str] = []
    for line in h.ours:
        m = INV_ROW.match(line)
        out_lines.append(decide(m.group(1)) if m else line)
    appended = [theirs[k] for k in theirs if k not in ours and decide(k) is not None]
    if appended and appended_rows_refusal(h) is not None:
        raise CannotPlace(appended[-1], appended_rows_refusal(h))
    out_lines += appended
    placed, frame = set(out_lines), table_frame_lines(list(h.ours))
    for line in h.theirs:                                 # totality check, at the resolver
        if INV_ROW.match(line) is None and not (line in frame and line in placed):
            raise CannotPlace(line, "inventory merge places a design-ID row or the table frame "
                                    "(header + `| --- |`), and this line is neither")
    return HunkResult("design-inventory-row-merge", RESOLVED, out_lines)


def resolve_append_log(h: Hunk) -> HunkResult:
    """base is a common prefix of both sides; keep the base once, then ours' tail, then theirs'.

    **Only where every line keeps its entry** (round 19, P2): the resolver re-checks
    `classify._is_append_only_log`, which a hand-built hunk could otherwise skip. Two differing
    tails must each start AT a log entry, open no section, and be followed by an entry boundary —
    otherwise theirs' leading continuation line (or the line after the region) would be emitted
    under ours' last appended entry.

    **Collapses only a WHOLE tail.** When both tails are byte-identical — a re-run that appended
    the same lines on both branches — one copy is kept. Otherwise nothing is collapsed, and if the
    two tails share any NON-BLANK line the hunk REFUSES: this resolver cannot tell whether that
    line is one entry both sides appended or a line that belongs to two distinct entries (F5: two
    new changelog entries each ending `  Approved-by: operator` — the old per-line cross-side
    dedupe kept one copy and theirs' entry lost its body under a RESOLVED verdict). Shared blank
    lines are separators, not content, and are kept on both sides verbatim.
    """
    if not _is_append_only_log(h):
        raise CannotPlace(h.theirs[len(h.base)] if len(h.theirs) > len(h.base) else "",
                          "not an append of whole log entries after a shared base (see "
                          "classify._is_append_only_log)")
    n = len(h.base)
    ours_tail, theirs_tail = list(h.ours[n:]), list(h.theirs[n:])
    if ours_tail == theirs_tail:
        return HunkResult("append-only-log", RESOLVED, h.base + ours_tail)
    shared = {ln for ln in ours_tail if ln.strip()} & {ln for ln in theirs_tail if ln.strip()}
    if shared:
        raise CannotPlace(sorted(shared)[0], "both tails carry this line, and a line-level "
                                             "collapse cannot tell one entry from two")
    return HunkResult("append-only-log", RESOLVED, h.base + ours_tail + theirs_tail)


def resolve_log_entry_insertion(h: Hunk) -> HunkResult:
    """Both sides concurrently inserted dated log entries at the same location — classification
    guarantees an EMPTY base (no deletions). Keep BOTH insertion blocks VERBATIM, ours' then
    theirs' (deterministic; the cert re-runs this and byte-compares).

    Deliberately NO line-dedup: two DISTINCT dated entries can legitimately share a body line, and
    dropping it would CORRUPT an entry (a zero-drop violation). Verbatim concatenation keeps every
    line; the only degenerate case — both sides added the byte-identical entry — yields a visible
    duplicate, the fail-SAFE direction, since nothing is ever lost. `h.base` is empty by
    construction, so there is no shared tail to re-attach."""
    return HunkResult("log-entry-insertion", RESOLVED, list(h.ours) + list(h.theirs))


def resolve_decision_entry_insertion(h: Hunk) -> HunkResult:
    """Both sides concurrently appended decision-log entries — classification guarantees an EMPTY
    base (no deletions). Keep BOTH insertion blocks VERBATIM, ours' then theirs' (deterministic;
    the cert re-runs this and byte-compares).

    Same shape and same reasoning as `resolve_log_entry_insertion`, including the deliberate
    absence of any dedupe. Design §Open Questions decided keep-both: the verifier cannot
    distinguish a re-run's duplicate entry from two genuinely identical decisions, and duplication
    is the fail-SAFE direction — a visible duplicate costs a reader a moment, a drop costs the
    audit trail an entry. No renumber, no reorder: decision entries carry no ID to renumber, and
    a union merge must not permute what the human wrote."""
    return HunkResult("decision-entry-insertion", RESOLVED, list(h.ours) + list(h.theirs))


MECH_RESOLVERS = {
    "id-renumber-collision": resolve_id_renumber,
    "design-inventory-row-merge": resolve_inventory,
    "append-only-log": resolve_append_log,
    "log-entry-insertion": resolve_log_entry_insertion,
    "decision-entry-insertion": resolve_decision_entry_insertion,
}

