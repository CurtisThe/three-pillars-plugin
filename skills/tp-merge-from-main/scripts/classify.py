#!/usr/bin/env python3
"""Structural classifier for living-doc merge conflicts.

Parses a `git merge-file --diff3` conflict block into clean segments and conflict hunks, then
labels each hunk by *structure alone* (regex on line shape) — no prose understanding, no LLM.
Validated by the worktree-merge-conflict-flow spike: 0 misclassifications across 12 real-fixture
hunks, and crucially 0 semantic-misclassified-as-mechanical (the only dangerous error).

Hunk classes (see three-pillars-docs/tp-designs/worktree-merge-conflict-flow/demos/taxonomy.md):
    id-renumber-collision          both sides introduce `### L<n>:` / `### D<n>:` headings
    design-inventory-row-merge     conflict over `| D<n> | ... |` / `| S<n> | ... |` table rows
    current-focus-reprioritization conflict over Current-Focus priority rows `| <int> | <design> |`
    preamble                       conflict touches a `*Last updated: ...*` line
    append-only-log                both sides only append distinct trailing lines (no deletions)
    generic-prose                  anything else (default — defer to a human)

Only the MECHANICAL classes are eligible for auto-resolution; SEMANTIC classes must defer.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field

MECHANICAL = frozenset({"id-renumber-collision", "design-inventory-row-merge", "append-only-log"})
SEMANTIC = frozenset({"preamble", "current-focus-reprioritization", "generic-prose"})
# GATED: mechanical by structure, but NOT auto-resolved yet — the spike captured no isolated
# ground-truth fixture for these, so they are deferred to a human until one lands.
GATED = frozenset({"append-only-log"})
# The classes the resolver may actually auto-apply: mechanical AND not gated.
AUTO_RESOLVE = MECHANICAL - GATED

ID_HEADING = re.compile(r"^### ([A-Z])(\d+):")   # ### L4:  ### D12:
INV_ROW = re.compile(r"^\|\s*([A-Z]\d+)\s*\|")    # | D12 | ...
FOCUS_ROW = re.compile(r"^\|\s*(\d+)\s*\|\s*\S")   # | 3 | design | ...  (priority table)
PREAMBLE = re.compile(r"^\*Last updated:")


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
        pf = classify_file(Path(path).read_text())
        hunks = [s for s in pf.segments if isinstance(s, Hunk)]
        print(f"\n{path}  ({len(hunks)} hunk(s))")
        for n, h in enumerate(hunks, 1):
            kind = "MECH" if h.label in MECHANICAL else "SEM "
            print(f"  hunk {n}: [{kind}] {h.label}")
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
