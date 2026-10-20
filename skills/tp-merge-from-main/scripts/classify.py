#!/usr/bin/env python3
"""Structural classifier for living-doc merge conflicts.

Parses a `git merge-file --diff3` conflict block into clean segments and conflict hunks, then
labels each hunk by *structure alone* (regex on line shape) — no prose understanding, no LLM.
Validated by the worktree-merge-conflict-flow spike: 0 misclassifications across 12 real-fixture
hunks, and crucially 0 semantic-misclassified-as-mechanical (the only dangerous error).

Hunk classes (see three-pillars-docs/completed-tp-designs/worktree-merge-conflict-flow/demos/taxonomy.md):
    id-renumber-collision          both sides INSERT whole `### L<n>:` entries (EMPTY base, each
                                   side starting at an ID heading, no other section heading), all
                                   of one letter, and at least one ID is new on BOTH sides.
                                   GATED since round 20: labelled, never auto-resolved (see GATED)
    design-inventory-row-merge     conflict over `| D<n> | ... |` / `| S<n> | ... |` table rows
    current-focus-reprioritization conflict over Current-Focus priority rows `| <int> | <design> |`
    preamble                       conflict touches a `*Last updated: ...*` line
    append-only-log                both sides extend a shared base line; two differing tails must
                                   each be whole log entries
    log-entry-insertion            both sides concurrently insert bold-lead-bullet log entries —
                                   dated `- **YYYY-MM-DD** —` or name-keyed `- **`slug`** —`
                                   (empty-base pure insertion — the real newest-first-log shape)
    keyed-heading-insertion        both sides insert whole keyed entries (`### M48:`, `### M-new-x:`,
                                   `### M27 (RESOLVED …):`, `` ### `slug` (date) ``), distinct keys
    keyed-row-insertion            both sides append `| slug | … |` table rows, keys found nowhere else
    decision-entry-insertion       both sides concurrently insert decision-log entries —
                                   `### [{skill-name}] <title>` plus its body (empty-base pure
                                   insertion; the shape every `/tp-run-full-design` fold produces
                                   by construction, and a guaranteed hand-resolve before this)
    generic-prose                  anything else (default — defer to a human)

The four keep-both classes (all but the inventory row merge) also require, whenever the merge
would emit both sides' lines, the first non-blank line after the region to START an entry or the
region to end the file (`_ends_at_boundary`). The three auto-resolvable ones hold each side's
inserted lines (for `append-only-log`, each differing tail that is not whitespace only) to
`line_shapes.keep_both_refusal` (round 22): an entry start, or plain text that is not
heading-shaped at any indentation or past list markers (round 23; an underline shape directly below
a blank line of its side is admitted) and opens no HTML block, code fence, block quote, math block
or link definition; no carriage return inside a line. The
inventory row merge instead requires both sides' lines to stay rows of one table (`table_run`): no
blank line, line of pipes only or inner carriage return, no frame but one both sides open with, and
no appended row directly above a delimiter row or a line with a carriage return inside it.

Only `AUTO_RESOLVE` classes (MECHANICAL minus GATED) are ever auto-resolved; a GATED or a SEMANTIC
hunk defers to a human.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
# The parser lives in its own module (round 11) — a `Hunk` is what `classify` labels, not what it
# builds. Re-exported here so every existing `from classify import Hunk, parse_conflict` still
# resolves; `conflict_parse` is the single source of truth for the marker constants and the scan.
from conflict_parse import (  # noqa: E402,F401
    Hunk, MARK_BASE, MARK_CLOSE, MARK_OPEN, MARK_SEP, ParsedFile, _pre_context, _scan_region,
    parse_conflict,
)
# The entry and heading shapes live in `line_shapes` since round 23 (re-exported here).
from line_shapes import (  # noqa: E402,F401
    ATX_HEADING, DECISION_ENTRY, ENTRY_SECTION_END, FOREIGN_ATX, LOG_ENTRY, SETEXT_UNDERLINE,
    focus_context, keep_both_refusal,
)
from table_run import table_run_refusal  # noqa: E402
import keyed_classes, keyed_rows  # noqa: E401,E402
import shaped_merge  # noqa: E402

MECHANICAL = frozenset(
    {"id-renumber-collision", "design-inventory-row-merge", "append-only-log",
     "log-entry-insertion", "decision-entry-insertion", "keyed-heading-insertion",
     "last-updated-preamble", "keyed-row-insertion", "shaped-line-merge", "low-count-line"}
)
SEMANTIC = frozenset({"preamble", "current-focus-reprioritization", "generic-prose"})
# GATED: mechanical-by-structure classes that are labelled but NEVER auto-applied. `resolve.
# resolve_hunk` defers a gated hunk verbatim (code `gated`) before any other check, and every path
# that turns a hunk into bytes goes through it: the merge driver and the certifier's condition 5
# (both via `auto_safe_resolution.resolve_conflict_bytes*` -> `resolve.resolve_file`), the carry
# lane's clean-merge comparison (`living_doc_carry._mechanical_resolution`, the same byte path),
# and `stage_oracle`, which cross-checks only the hunks `resolve_hunk` RESOLVED.
#
# `id-renumber-collision` is gated since round 20 (its merge is unsound in principle). Disjoint keyed
# entries (`### M48:` / `### M49:`) are `keyed-heading-insertion` now (keep-both, no renumber), so
# only a SAME-ID collision reaches this class:
#   * its reference and ID scope is the one conflicted FILE (`Hunk.context`). Living-doc IDs are
#     cited from the OTHER living docs — a `product_roadmap.md` bullet `Filed **L67** (...)`, an ID
#     already spent in `known_issues.md`, `known_issues_low.md` or
#     `known_issues_resolved.md` — which it cannot see: it can pick a "free" ID
#     another doc already uses, and it leaves every cross-doc citation of the old number pointing at
#     the other side's entry;
#   * it renumbers THEIRS, and on a base-sync (`merge_driver.merge_back`) theirs is the BASE
#     branch: the entry that has already landed, whose number every reference on the base means;
#   * review rounds 17, 18, 19 and 20 each found a reachable silent alteration in it, and across
#     the 265 real merge commits in this repository's history it resolved exactly ONE region.
# Un-gating it needs all three of: ID and reference scope across every living doc rather than one
# file, renumbering the DESIGN side's entry rather than the base side's, and a ground-truth fixture
# taken from a real merge. The label, `resolvers.resolve_id_renumber` and its licence are kept
# (gated, not deleted): reports still name the class, and the refusals pinned so far are not lost.
GATED = frozenset({"id-renumber-collision"})
# The classes the resolver may actually auto-apply: mechanical AND not gated.
AUTO_RESOLVE = MECHANICAL - GATED

ID_HEADING = re.compile(r"^### ([A-Z])(\d+):")   # ### L4:  ### D12:
# `[0-9]`, not `\d` (m-M1): kept byte-identical to `resolve_totality.INV_ROW`, because THIS pattern
# is the row-ID oracle `resolve.resolve_inventory` merges rows by and that one is the oracle the
# totality checker scores the result with. A Unicode digit admitted here and refused there would
# split the two lanes the same way it split the checker from `licence_oracle`.
INV_ROW = re.compile(r"^\|\s*([A-Z][0-9]+)\s*\|")    # | D12 | ...
FOCUS_ROW = re.compile(r"^\|\s*(\d+)\s*\|\s*\S")   # | 3 | design | ...  (priority table)
SLUG_ROW = re.compile(r"^\|\s*`([a-z0-9][a-z0-9-]*)`")   # | `slug` | ...  (own copy; see `verify_atoms`)
PREAMBLE = re.compile(r"^\*Last updated:")


def _any(lines: list[str], rx: re.Pattern) -> bool:
    return any(rx.match(line) for line in lines)


def _heading_at(side: list[str], i: int) -> bool:
    """`side[i]` makes a markdown heading: an ATX heading indented 0-3 spaces (`FOREIGN_ATX`), or a
    setext underline directly below a non-blank line of the same side. The underline rule is
    deliberately wider than CommonMark's (which needs a PARAGRAPH line above, so `---` under a
    heading or a list item is a thematic break): it is used only to refuse.

    "Blank" is CommonMark's: spaces and tabs only (plus the `\r` of a CRLF line ending, which rides
    on the line because the parse splits on `\n`). `str.strip()` also strips NBSP and every other
    Unicode space, so an NBSP-only line read as blank, and a `---` under it passed as a thematic
    break; to CommonMark that line continues the paragraph above, and the `---` makes it a setext
    heading (round 21)."""
    if FOREIGN_ATX.match(side[i]):
        return True
    return i > 0 and bool(side[i - 1].strip(" \t\r")) and bool(SETEXT_UNDERLINE.match(side[i]))


def _line_is_foreign(side: list[str], i: int) -> bool:
    """`side[i]` signals a structure OTHER than a new log bullet or its wrapped continuation — a
    section heading indented 0-3 spaces, ATX or setext (`_heading_at`), an ID heading, an
    inventory/focus row, or a preamble line. Its presence inside an insertion block means the change
    is not cleanly "new log entries", so we fall closed. NOT every heading: one nested in a list
    item sits 4 or more columns in (`    ## Archive` under a bullet is an h2 inside that item), which
    `_heading_at` does not see; the keep-both classes refuse it with `line_shapes.ATX_SHAPE` and
    `SETEXT_SHAPE` (round 23), which read a line at any indentation and past its list markers."""
    line = side[i]
    return bool(
        _heading_at(side, i) or ID_HEADING.match(line) or INV_ROW.match(line)
        or FOCUS_ROW.match(line) or PREAMBLE.match(line)
    )


def _is_log_insertion_block(side: list[str]) -> bool:
    """`side` is ONE OR MORE cleanly-inserted log entries, each possibly WRAPPED over blank +
    plain continuation lines (a bullet followed by an indented body paragraph is the real
    `## History` / `### Recent completions` shape — see the git-minimized fixtures). Fail-closed
    rule: the block must START with a log bullet, carry >=1 log bullet, and contain NO foreign
    structural line. Blank and plain continuation lines are allowed (so a wrapped entry still
    qualifies); requiring every line to be a bullet would re-inert the class on wrapped entries.
    Every line must also be a shape `line_shapes.keep_both_refusal` admits (round 22): a line
    opening an HTML block or a code fence would render theirs' following entry inside it, and a
    heading nested in a list item (round 23) would put it in that heading's section."""
    content = [ln for ln in side if ln.strip()]
    if not content or not LOG_ENTRY.match(content[0]):
        return False                          # empty, or does not START with a log bullet
    if not any(LOG_ENTRY.match(ln) for ln in content):
        return False                          # carries no log bullet (the start-check implies this)
    if any(_line_is_foreign(side, i) for i in range(len(side))):
        return False                          # a heading/row/preamble/id line => not clean new entries
    return keep_both_refusal(side, LOG_ENTRY) is None   # every line an admitted shape (round 22)


def _is_decision_insertion_block(side: list[str]) -> bool:
    """`side` is ONE OR MORE cleanly-inserted decision-log entries, each a `### [tag] title`
    heading plus its `**Question**/**Decided**/**Reasoning**/**Confidence**` body.

    Mirrors `_is_log_insertion_block`'s fail-closed rule — must START with a decision-entry
    heading, carry >=1, contain no foreign structural line — with ONE deliberate difference: a
    decision entry IS an ATX heading, so the log predicate's blanket heading rejection cannot be
    reused verbatim. "Foreign" here is `_line_is_foreign` for every line that is NOT itself a
    `DECISION_ENTRY` match. Every other heading (a `## Section`, an `### L4:` ID heading, an
    indented `  ## x`, a setext underline — including one directly under a decision heading) is
    still foreign and still falls closed. Every line must also be a shape
    `line_shapes.keep_both_refusal` admits, with `DECISION_ENTRY` as the entry start (round 22).
    """
    content = [ln for ln in side if ln.strip()]
    if not content or not DECISION_ENTRY.match(content[0]):
        return False                          # empty, or does not START with a decision entry
    if not any(DECISION_ENTRY.match(ln) for ln in content):
        return False                          # carries no decision entry (start-check implies this)
    for i, ln in enumerate(side):
        if DECISION_ENTRY.match(ln):
            continue                          # the class's own heading is never foreign to it
        if _line_is_foreign(side, i):
            return False                      # heading/row/preamble/id line => not clean new entries
    return keep_both_refusal(side, DECISION_ENTRY) is None   # every line an admitted shape


def _is_inventory_block(side: list[str]) -> bool:
    """Every non-blank line of `side` is a table line and nothing else — the purity predicate the
    inventory arm was missing (known-issue H8, and the classifier half of S-I1). That the lines are
    ONE table (no blank line, no frame but one both sides open with) is `table_run_refusal`'s half,
    which `_is_inventory_row_merge` asks too (round 21, S1).

    `resolve_inventory` merges by design-ID key: it re-emits ours' block with same-ID rows swapped
    to theirs' and appends theirs-only rows. That is a total, zero-drop operation ONLY over table
    lines; any other line on theirs' side has no key, hence no place in the output, and the old
    resolver simply discarded it. So the class is restricted to what it can actually represent:
    every non-blank line must be a table line (`|`-leading), and nothing may look like a competing
    structure — a `| <int> |` Current-Focus priority row is a DIFFERENT table, an ID heading /
    section heading / preamble line belongs to another class, and a `|||||||` is a conflict marker
    that merely happens to start with a pipe. Mirrors `_is_log_insertion_block` /
    `_is_decision_insertion_block`, which have had this shape all along. (A heading in any form is
    refused here already, by the `|`-leading requirement.)
    """
    for ln in side:
        if not ln.strip():
            continue                              # a blank is refused by `table_run_refusal`
        if ln.startswith(MARK_BASE) or not ln.startswith("|"):
            return False                          # a marker, or not a table line at all
        if FOCUS_ROW.match(ln) or PREAMBLE.match(ln) or ID_HEADING.match(ln) or ATX_HEADING.match(ln):
            return False                          # a competing structure's line
    return True


def _heading_ids(lines: list[str]) -> list[str]:
    return [m.group(1) + m.group(2) for m in map(ID_HEADING.match, lines) if m]


def _ends_at_boundary(h: Hunk, *starts: re.Pattern) -> bool:
    """The first non-blank line after the region (`Hunk.post_context`) starts a new entry — it
    matches one of `starts` — or there is none (EOF). Round 19.

    Each class that calls this emits ours' block and then theirs', so that line follows THEIRS'
    last entry in the merge although on ours' side it followed OURS'. When it CONTINUES an entry (both
    sides inserted their entries in the middle of an existing one, so each side made the rest of it
    part of its own new entry), the merge silently moves it from ours' entry to theirs'. An unknown
    line (`None`: another region follows directly, or the hunk was built by hand without one) is
    refused as well.
    """
    post = h.post_context
    return post is not None and (not post or any(rx.match(post) for rx in starts))


def _is_id_entry_block(side: list[str]) -> bool:
    """`side` is ONE OR MORE whole ID-headed entries and nothing else (round 19, P1): its first
    non-blank line is an `### <Letter><n>:` heading, and no line makes a heading other than an ID
    heading (`_heading_at`: indented ATX and setext forms too, round 20). Leading and trailing blank
    lines are allowed — diff3 routinely puts the separator blank inside the region — and so is any
    other body line.

    Why each half is needed, given that the merge emits ours' block and then theirs':
    * a side that does not START at a heading has lines belonging to the entry ABOVE the region
      (`Workaround: rerun the job.` under base's L4); after the merge they sit under ours' last new
      entry instead. An identical such line on both sides is re-parented AND duplicated.
    * a section heading inside a side (`## Won't Fix`) opens a section that swallows everything
      emitted after it — on ours' side, theirs' whole block.
    """
    content = [ln for ln in side if ln.strip()]
    if not content or not ID_HEADING.match(content[0]):
        return False
    return not any(_heading_at(side, i) and not ID_HEADING.match(ln) for i, ln in enumerate(side))


def _is_id_renumber_collision(h: Hunk) -> bool:
    """A GENUINE ID collision: both sides inserted WHOLE ID-headed entries at one point, nothing
    else, and at least one ID is new on both. Five refusals, each a shape the renumber would
    otherwise mis-merge (F4, round 18 R2, round 19 P1):

    * **The base must be EMPTY, and present.** The merge emits ours' lines then theirs' and never
      reads base. An empty base is NECESSARY for that to be sound — neither side changed or
      deleted a base line — but NOT SUFFICIENT: it says nothing about which entry each line
      belongs to, which the next two arms decide. A diff3 region's base is exactly the base lines
      the two sides' overlapping changes cover, and two pure insertions at one point cover none,
      so real `git merge-file --diff3` writes an empty base for them — the same signal both
      insertion classes use. Any base line at all means a side
      changed or deleted it: a retitled `### L62:` (F4a — renumbering it invents an entry and
      orphans the original's body), a `Status: open` both sides rewrote differently (R2 — both
      rewrites were glued into the merged entries), a line one side edited and the other deleted,
      or base's last line lacking a newline (merge-file keeps it in the region). A blank base line
      is refused too: a blank one side deleted would be resurrected, and one both sides kept
      would be emitted twice. A 2-way region (no `|||||||` section, `base_marker is None`)
      records no base at all, so it cannot show the base was empty and is refused as well.
    * **Each side is whole entries** (`_is_id_entry_block`): it starts at an ID heading and opens
      no other section, so no line of it is re-parented under an entry of the OTHER side.
    * **The region ends at a section boundary.** Whatever follows the region follows THEIRS' last
      entry in the merge, although on ours' side it followed OURS' last entry; a body line there
      (both sides inserted their heading mid-entry, so both made base's next line part of their new
      entry) moves from ours' entry to theirs'. So the first non-blank line after the region must be
      a level-1..3 ATX heading or EOF (`Hunk.post_context`); another region there refuses too.
    * **One letter only.** A renumber never moves an entry across letters (`L41` is not `M23`).
    * **A real collision.** Two different new IDs (`L63` vs `L64`, or `M22` vs `L41`) do not
      collide, so there is nothing to renumber and this class must not claim the hunk.
    """
    if h.base or h.base_marker is None:
        return False
    if not (_is_id_entry_block(h.ours) and _is_id_entry_block(h.theirs)):
        return False
    if not _ends_at_boundary(h, ENTRY_SECTION_END):
        return False
    ours, theirs = _heading_ids(h.ours), _heading_ids(h.theirs)
    if len({i[0] for i in ours + theirs}) != 1:
        return False
    return bool(set(ours) & set(theirs))


def _is_inventory_row_merge(h: Hunk) -> bool:
    """At least one design-ID row is in play, both sides are pure inventory-table blocks, and both
    sides' lines stay in ONE table: no blank line, and no frame except one both open with (round
    21, S1: `table_run.table_run_refusal`, which says why)."""
    if not _any(h.ours + h.theirs, INV_ROW):
        return False
    if not (_is_inventory_block(h.ours) and _is_inventory_block(h.theirs)):
        return False
    return table_run_refusal(h) is None


def _is_append_only_log(h: Hunk) -> bool:
    """Base is a NON-EMPTY common prefix of both sides, and what the resolver would emit after it —
    ours' tail, then theirs' — keeps every line under the entry it was written under (round 19, P2).

    Real git produces this shape when base's last line has no final newline: that line is both
    sides' shared prefix inside the region. When the tails are byte-identical (emitted once) or one
    of them is empty (say, that side only added the missing final newline), the merged region is
    exactly one side's region, so no line moves and nothing more is asked. Otherwise theirs' tail
    lands after ours', and each tail must be blank lines only or `_is_log_insertion_block`:
    starting AT a log entry, so a continuation line (`  (alpha later reverted in PR #9)`, which
    continued base's last entry) cannot end up under ours' last new entry, and carrying no section
    heading that would swallow the other side's entries. The line after the region, which follows
    theirs' tail in the merge but followed ours' on ours' side, must be a log entry, a section
    heading, or EOF (`Hunk.post_context`).
    """
    n = len(h.base)
    if not n or h.ours[:n] != h.base or h.theirs[:n] != h.base:
        return False
    ours_tail, theirs_tail = h.ours[n:], h.theirs[n:]
    if not ours_tail or not theirs_tail or ours_tail == theirs_tail:
        return True
    for tail in (ours_tail, theirs_tail):
        if any(ln.strip() for ln in tail) and not _is_log_insertion_block(tail):
            return False
    return _ends_at_boundary(h, LOG_ENTRY, ATX_HEADING)


def _is_decision_entry_insertion(h: Hunk) -> bool:
    """Both sides concurrently inserted one or more decision-log entries, deleting nothing.

    Same soundness argument as `_is_log_entry_insertion`: the EMPTY base is the load-bearing
    signal that neither side removed a line (a pure concurrent add), so keep-both concatenation
    can drop nothing; the block-purity check is the separate restriction limiting keep-both to
    the decisions-log append pattern. The line after the region must end an entry too (round 19):
    see `_ends_at_boundary`."""
    if h.base:                       # non-empty base => a modification/deletion, not a pure insert
        return False
    if not h.ours or not h.theirs:   # both sides must contribute an insertion
        return False
    if not _ends_at_boundary(h, ENTRY_SECTION_END):
        return False
    return _is_decision_insertion_block(h.ours) and _is_decision_insertion_block(h.theirs)


def _is_log_entry_insertion(h: Hunk) -> bool:
    """Both sides concurrently inserted ONE OR MORE bold-lead-bullet log entries, deleting nothing.

    Empty base is the load-bearing SOUNDNESS signal: `git merge-file --diff3` minimizes a
    newest-first-log insertion to an empty-base conflict (the shared header + prior entry factor OUT
    as common prefix/suffix), and an empty base means NEITHER side removed a line — a pure concurrent
    add, so keep-both concatenation can drop nothing. The bullet-block check is a SEPARATE restriction
    whose only job is to limit keep-both to the append-only-log pattern: each side must be cleanly
    "new log entries" (`_is_log_insertion_block`), so arbitrary concurrent prose edits still DEFER to
    a human. A wrapped entry (bullet + continuation body) still qualifies; a deletion (non-empty
    base), a non-log insertion, or any foreign structure falls CLOSED. Both sides must contribute an
    insertion, and the line after the region must not continue an entry (`_ends_at_boundary`)."""
    if h.base:                       # non-empty base => a modification/deletion, not a pure insert
        return False
    if not h.ours or not h.theirs:   # both sides must contribute an insertion
        return False
    if not _ends_at_boundary(h, LOG_ENTRY, ATX_HEADING):
        return False
    return _is_log_insertion_block(h.ours) and _is_log_insertion_block(h.theirs)


def classify_hunk(h: Hunk, focus_ctx: bool | None = None) -> str:
    """The class of `h`. `focus_ctx` is `focus_context(h.pre_context)`, computed here when None;
    `classify_file` passes it in so a context line shared by many regions is searched once."""
    sides = h.ours + h.theirs
    extra = keyed_classes.extra_label(h) or keyed_rows.extra_label(h)   # the insert-only classes
    if extra is not None:
        return extra
    if _any(h.ours, PREAMBLE) or _any(h.theirs, PREAMBLE):
        return "preamble"
    if focus_ctx is None:
        focus_ctx = focus_context(h.pre_context)
    if _any(sides, FOCUS_ROW) and not _any(sides, INV_ROW):
        return "current-focus-reprioritization"
    if focus_ctx and _any(sides, FOCUS_ROW):
        return "current-focus-reprioritization"
    # Inventory rows, and NOTHING BUT inventory-table lines on either side. The bare
    # `_any(sides, INV_ROW)` this replaces had no purity gate at all — one row anywhere claimed
    # the whole hunk for a MECHANICAL class whose resolver keeps rows and discarded the rest
    # (known-issue H8). A mixed hunk now falls through to a semantic class and DEFERS. A slug-keyed
    # row is no inventory row: `resolve_inventory` keys by design ID and cannot place it.
    if _is_inventory_row_merge(h) and not _any(sides, SLUG_ROW):
        return "design-inventory-row-merge"
    if _is_id_renumber_collision(h):
        return "id-renumber-collision"
    if _is_append_only_log(h):
        return "append-only-log"
    # Concurrent log-entry insertion — the REAL base-sync shape for newest-first ADR logs like
    # architecture.md's `## History`. `git merge-file --diff3` MINIMIZES the conflict, factoring
    # the shared `## History` header (common prefix) AND the prior entry (common suffix) OUT of the
    # hunk, so the base between the two divergent insertion blocks is EMPTY, and this empty-base
    # predicate is the workhorse for live base-syncs. The append-prefix arm above IS reachable on
    # real git output too, though: when base's LAST line has no trailing newline, both sides'
    # newline-terminated copy of it differs from base's, so merge-file keeps that line in the hunk
    # as a shared prefix (`three-pillars-docs/vision.md` has no trailing newline today). See
    # `resolvers.resolve_append_log` for what that class may and may not collapse.
    if _is_log_entry_insertion(h):
        return "log-entry-insertion"
    # Concurrent decision-log entry insertion — the shape EVERY `/tp-run-full-design` fold
    # produces by construction (the orchestrator appends on `tp/{slug}`, workers append on
    # `candidate/{slug}/single`), which was a guaranteed hand-resolve before this class existed.
    # Mutually exclusive with the arm above: one block starts with `- **`, the other with `### [`.
    if _is_decision_entry_insertion(h):
        return "decision-entry-insertion"
    if shaped_merge.is_shaped_line_merge(h):
        return "shaped-line-merge"
    return "generic-prose"


def is_confident(h: Hunk) -> bool:
    """Confidence gate for the `mechanical ∧ classifier-confident ∧ verifier-passes` contract.

    A mechanically-labelled hunk is *confident* only when its structure is internally consistent
    with its class — i.e. it carries no signal belonging to a DIFFERENT class. A hunk that mixes,
    say, inventory rows with an ID heading or a preamble line is ambiguous; we downgrade it to a
    deferral rather than risk auto-resolving a mixed structure. Semantic hunks are always deferred
    regardless, so confidence only constrains the mechanical classes.
    """
    if h.label not in MECHANICAL:
        return True
    keyed = (keyed_rows if h.label == keyed_rows.LABEL else keyed_classes).extra_confident(h)
    if keyed is not None:
        return keyed
    sides = h.ours + h.theirs
    has_heading = _any(sides, ID_HEADING)
    has_inv = _any(sides, INV_ROW)
    has_focus = _any(sides, FOCUS_ROW) and not has_inv
    has_preamble = _any(sides, PREAMBLE)
    if has_preamble:
        return False                       # a mechanical hunk must not also carry a preamble edit
    if h.label == "id-renumber-collision":
        return (has_heading and not has_inv and not has_focus
                and _is_id_renumber_collision(h))   # re-verify the strict predicate (fail-closed)
    if h.label == "design-inventory-row-merge":
        # Re-verify the strict purity predicate (fail-closed), as both insertion arms do. The old
        # `has_inv and not has_heading and not has_focus` tested only for COMPETING CLASS SIGNALS
        # — and `has_focus` is dead here by construction (it is `... and not has_inv`) — so a hunk
        # mixing rows with arbitrary prose stayed "confident" and auto-resolved (H8).
        return _is_inventory_row_merge(h) and not has_heading
    if h.label == "append-only-log":
        return not (has_heading or has_inv or has_focus) and _is_append_only_log(h)
    if h.label == "log-entry-insertion":
        return _is_log_entry_insertion(h)   # re-verify the strict purity predicate (fail-closed)
    if h.label == "decision-entry-insertion":
        return _is_decision_entry_insertion(h)   # same fail-closed re-verification
    return True


def classify_file(text: str, labels: tuple[str, str, str] | None = None) -> ParsedFile:
    """Parse (`conflict_parse.parse_conflict`, labelled when `labels` is given) and label hunks.

    The focus search runs once per distinct `pre_context` OBJECT (round 26). The parse gives every
    region the same line object until a clean non-blank line replaces it, so the regions of a file
    separated by blank lines only share one; searching it per region cost regions x its length
    (a 1 MB file: about a minute per `merge_back`). Keyed by `id`, which is stable here because
    every such object is held by a hunk in `pf` for the whole loop."""
    pf = parse_conflict(text, labels=labels)
    focus: dict[int, bool] = {}
    for seg in pf.segments:
        if isinstance(seg, Hunk):
            key = id(seg.pre_context)
            if key not in focus:
                focus[key] = focus_context(seg.pre_context)
            seg.label = classify_hunk(seg, focus[key])
    return pf


def _main(argv: list[str]) -> int:
    for path in argv:
        pf = classify_file(Path(path).read_text(encoding="utf-8"))
        hunks = [s for s in pf.segments if isinstance(s, Hunk)]
        print(f"\n{path}  ({len(hunks)} hunk(s))")
        for n, h in enumerate(hunks, 1):
            kind = "MECH" if h.label in MECHANICAL else "SEM "
            print(f"  hunk {n}: [{kind}] {h.label}")
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
