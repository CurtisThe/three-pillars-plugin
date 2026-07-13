#!/usr/bin/env python3
"""Structural classifier for living-doc merge conflicts.

Parses a `git merge-file --diff3` conflict block into clean segments and conflict hunks, then
labels each hunk by *structure alone* (regex on line shape) — no prose understanding, no LLM.
Validated by the worktree-merge-conflict-flow spike: 0 misclassifications across 12 real-fixture
hunks, and crucially 0 semantic-misclassified-as-mechanical (the only dangerous error).

Hunk classes (see three-pillars-docs/completed-tp-designs/worktree-merge-conflict-flow/demos/taxonomy.md):
    id-renumber-collision          both sides introduce `### L<n>:` / `### D<n>:` headings
    design-inventory-row-merge     conflict over `| D<n> | ... |` / `| S<n> | ... |` table rows
    current-focus-reprioritization conflict over Current-Focus priority rows `| <int> | <design> |`
    preamble                       conflict touches a `*Last updated: ...*` line
    append-only-log                both sides only append distinct trailing lines (no deletions)
    log-entry-insertion            both sides concurrently insert bold-lead-bullet log entries —
                                   dated `- **YYYY-MM-DD** —` or name-keyed `- **`slug`** —`
                                   (empty-base pure insertion — the real newest-first-log shape)
    generic-prose                  anything else (default — defer to a human)

Only the MECHANICAL classes are eligible for auto-resolution; SEMANTIC classes must defer.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field

MECHANICAL = frozenset(
    {"id-renumber-collision", "design-inventory-row-merge", "append-only-log", "log-entry-insertion"}
)
SEMANTIC = frozenset({"preamble", "current-focus-reprioritization", "generic-prose"})
# GATED: mechanical-by-structure classes withheld from auto-resolution pending a ground-truth
# fixture proving a byte-safe keep-both round-trip. Emptied by the basesync-prepend-log design,
# which LANDS those fixtures for both log classes (append + prepend) — so both now auto-resolve.
# Kept as an (empty) frozenset so the gating lever stays available for any future class that needs
# a fixture before it can be trusted.
GATED = frozenset()
# The classes the resolver may actually auto-apply: mechanical AND not gated.
AUTO_RESOLVE = MECHANICAL - GATED

ID_HEADING = re.compile(r"^### ([A-Z])(\d+):")   # ### L4:  ### D12:
INV_ROW = re.compile(r"^\|\s*([A-Z]\d+)\s*\|")    # | D12 | ...
FOCUS_ROW = re.compile(r"^\|\s*(\d+)\s*\|\s*\S")   # | 3 | design | ...  (priority table)
PREAMBLE = re.compile(r"^\*Last updated:")
# A log entry is a bold-lead bullet — the REAL append-only-log shape in the living docs. Two forms:
#   dated      `- **2026-07-05** — …`   (architecture.md `## History`, roadmap `## Roadmap History`)
#   name-keyed `- **`design-slug`** — …` (product_roadmap.md `### Recent completions`)
# The name-keyed arm is a kebab design-slug (`[a-z0-9][a-z0-9-]*`), which EXCLUDES file-path
# description bullets like `- **`scripts/foo.py`** — …` (those carry `/` / `.`, deferring to a human).
LOG_ENTRY = re.compile(r"^-\s+\*\*(?:`[a-z0-9][a-z0-9-]*`|\d{4}-\d{2}-\d{2})\*\*\s+—")
ATX_HEADING = re.compile(r"^#{1,6}\s")   # any markdown section heading — foreign to a log-bullet block


@dataclass
class Hunk:
    ours: list[str]
    base: list[str]
    theirs: list[str]
    label: str = ""
    pre_context: str = ""   # the clean line immediately before the hunk (disambiguates table type)


@dataclass
class ParsedFile:
    segments: list = field(default_factory=list)   # entries are `str` (clean) or `Hunk`


def parse_conflict(text: str) -> ParsedFile:
    """Split `git merge-file --diff3` output into clean strings and Hunk objects."""
    pf = ParsedFile()
    lines = text.splitlines()
    i, clean = 0, []
    while i < len(lines):
        if lines[i].startswith("<<<<<<<"):
            if clean:
                pf.segments.append("\n".join(clean))
                clean = []
            ours, base, theirs = [], [], []
            i += 1
            while i < len(lines) and not lines[i].startswith("|||||||"):
                ours.append(lines[i]); i += 1
            i += 1
            while i < len(lines) and not lines[i].startswith("======="):
                base.append(lines[i]); i += 1
            i += 1
            while i < len(lines) and not lines[i].startswith(">>>>>>>"):
                theirs.append(lines[i]); i += 1
            i += 1
            pre = ""
            if pf.segments and isinstance(pf.segments[-1], str):
                tail = pf.segments[-1].splitlines()
                pre = tail[-1] if tail else ""
            pf.segments.append(Hunk(ours=ours, base=base, theirs=theirs, pre_context=pre))
        else:
            clean.append(lines[i]); i += 1
    if clean:
        pf.segments.append("\n".join(clean))
    return pf


def _any(lines: list[str], rx: re.Pattern) -> bool:
    return any(rx.match(line) for line in lines)


def _line_is_foreign(line: str) -> bool:
    """A line signalling a structure OTHER than a new log bullet or its wrapped continuation — a
    section heading, an ID heading, an inventory/focus row, or a preamble line. Its presence inside
    an insertion block means the change is not cleanly "new log entries", so we fall closed."""
    return bool(
        ATX_HEADING.match(line) or ID_HEADING.match(line) or INV_ROW.match(line)
        or FOCUS_ROW.match(line) or PREAMBLE.match(line)
    )


def _is_log_insertion_block(side: list[str]) -> bool:
    """`side` is ONE OR MORE cleanly-inserted log entries, each possibly WRAPPED over blank +
    plain continuation lines (a bullet followed by an indented body paragraph is the real
    `## History` / `### Recent completions` shape — see the git-minimized fixtures). Fail-closed
    rule: the block must START with a log bullet, carry >=1 log bullet, and contain NO foreign
    structural line. Blank and plain continuation lines are allowed (so a wrapped entry still
    qualifies); requiring every line to be a bullet would re-inert the class on wrapped entries."""
    content = [ln for ln in side if ln.strip()]
    if not content or not LOG_ENTRY.match(content[0]):
        return False                          # empty, or does not START with a log bullet
    if not any(LOG_ENTRY.match(ln) for ln in content):
        return False                          # carries no log bullet (the start-check implies this)
    if any(_line_is_foreign(ln) for ln in side):
        return False                          # a heading/row/preamble/id line => not clean new entries
    return True


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
    insertion."""
    if h.base:                       # non-empty base => a modification/deletion, not a pure insert
        return False
    if not h.ours or not h.theirs:   # both sides must contribute an insertion
        return False
    return _is_log_insertion_block(h.ours) and _is_log_insertion_block(h.theirs)


def classify_hunk(h: Hunk) -> str:
    sides = h.ours + h.theirs
    if _any(h.ours, PREAMBLE) or _any(h.theirs, PREAMBLE):
        return "preamble"
    focus_ctx = any(k in h.pre_context for k in ("Current Focus", "Priority", "Next Action"))
    if _any(sides, FOCUS_ROW) and not _any(sides, INV_ROW):
        return "current-focus-reprioritization"
    if focus_ctx and _any(sides, FOCUS_ROW):
        return "current-focus-reprioritization"
    if _any(sides, INV_ROW):
        return "design-inventory-row-merge"
    if _any(h.ours, ID_HEADING) and _any(h.theirs, ID_HEADING):
        return "id-renumber-collision"
    if h.base and h.ours[: len(h.base)] == h.base and h.theirs[: len(h.base)] == h.base:
        return "append-only-log"
    # Concurrent log-entry insertion — the REAL base-sync shape for newest-first ADR logs like
    # architecture.md's `## History`. `git merge-file --diff3` MINIMIZES the conflict, factoring
    # the shared `## History` header (common prefix) AND the prior entry (common suffix) OUT of the
    # hunk, so the base between the two divergent insertion blocks is EMPTY. (The append prefix
    # check above only fires on synthetic non-minimized hunks — real git output never keeps the
    # base in-hunk, so this empty-base predicate is the workhorse for live base-syncs.)
    if _is_log_entry_insertion(h):
        return "log-entry-insertion"
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
    sides = h.ours + h.theirs
    has_heading = _any(sides, ID_HEADING)
    has_inv = _any(sides, INV_ROW)
    has_focus = _any(sides, FOCUS_ROW) and not has_inv
    has_preamble = _any(sides, PREAMBLE)
    if has_preamble:
        return False                       # a mechanical hunk must not also carry a preamble edit
    if h.label == "id-renumber-collision":
        return has_heading and not has_inv and not has_focus
    if h.label == "design-inventory-row-merge":
        return has_inv and not has_heading and not has_focus
    if h.label == "append-only-log":
        return not (has_heading or has_inv or has_focus)
    if h.label == "log-entry-insertion":
        return _is_log_entry_insertion(h)   # re-verify the strict purity predicate (fail-closed)
    return True


def classify_file(text: str) -> ParsedFile:
    pf = parse_conflict(text)
    for seg in pf.segments:
        if isinstance(seg, Hunk):
            seg.label = classify_hunk(seg)
    return pf


def _main(argv: list[str]) -> int:
    from pathlib import Path
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
