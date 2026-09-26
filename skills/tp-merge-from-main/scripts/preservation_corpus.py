"""The adversarial + generated document corpus the preservation invariants run over.

Test-only support module, deliberately NOT named `test_*` so pytest does not collect it — the same
convention as `conflict_fixtures.py`, which holds the REAL-shape class fixtures. The split of
responsibility between the two: `conflict_fixtures` is ground truth (shapes observed in live
living docs, one per resolver class); this module is the adversary (malformed, nested and
coincidental marker soup, generated in bulk).

`corpus()` returns `[(name, text)]` and is consumed by `test_resolve_invariants.py`. Generation is
SEEDED, so a failing document is reproducible from its `generated:<k>` name.
"""
from __future__ import annotations

import random

from conflict_fixtures import ALL_FIXTURES, COINCIDENTAL_PROSE_THEN_CONFLICT

# A small alphabet that is deliberately marker-HEAVY: the interesting inputs are the ones where
# conflict syntax appears as ordinary content.
LINE_ALPHABET = [
    "<<<<<<< ours", "<<<<<<< see below for an example", "||||||| base", "=======",
    ">>>>>>> theirs", ">>>>>>> end example", "### L4: an entry", "### [tp-plan] a decision",
    "| D12 | a | design | x |", "- **2026-07-04** — a log entry", "*Last updated: 2026-07-04*",
    "ordinary prose that must survive", "", "  wrapped continuation", "## History",
]

CONTENT = [ln for ln in LINE_ALPHABET if ln[:1] not in ("<", "|", "=", ">")]

# Content that merely LOOKS like structure — the filler the generator may place INSIDE a
# well-formed region. Splitting this out is the fix for a real blind spot (m-I1): `CONTENT` drops
# every line starting with `<`, `|`, `=` or `>`, so no generated document could put a
# marker-look-alike (or a table row) inside a region, and the corpus was structurally incapable of
# finding S-I2 — a `======= see example above` line inside `ours` that the parser cut the region
# at, deleting it under a RESOLVED verdict. These are exactly the lines a living doc carries: this
# repo's own SKILL.md quotes conflict syntax, `=======` is a setext underline, `|||||||` is a table
# row of empty cells, and `| D12 | ... |` is the design inventory the row-merge class exists for.
MARKER_LOOKALIKE = [
    "======= see example above", "||||||| a table row of empty cells",
    "<<<<<<< see below for an example", ">>>>>>> end of example",
]
TABLE_LINES = [
    "| D12 | a | design | x |", "| D14 | b | design | y |",
    "| 3 | some-design | next action | — |", "| --- | --- | --- |",
]
# Weighted so ordinary content still dominates: a region whose `ours` happens to hold a
# `>>>>>>>`-prefixed line degenerates to non-region content by the grammar, and if that were the
# common case the corpus would stop containing regions at all (the floors in
# `test_resolve_invariants.py` pin that it does not).
FILLER = CONTENT * 3 + TABLE_LINES + MARKER_LOOKALIKE


def _chunk(rng: random.Random) -> list[str]:
    """One randomly-shaped fragment: raw marker soup, a well-formed 3-way or 2-way region, an
    unterminated open, an orphan close, or a region nested inside another's `ours`. The constructed
    regions are what make the corpus contain real spans; the soup is what makes it adversarial."""
    body = [rng.choice(FILLER) for _ in range(rng.randint(0, 3))]
    other = [rng.choice(FILLER) for _ in range(rng.randint(0, 2))]
    kind = rng.randint(0, 5)
    if kind == 0:                                            # raw soup, markers included
        return [rng.choice(LINE_ALPHABET) for _ in range(rng.randint(1, 6))]
    if kind == 1:                                            # well-formed 3-way
        return ["<<<<<<< ours", *body, "||||||| base", *other, "=======", *other, ">>>>>>> theirs"]
    if kind == 2:                                            # well-formed 2-way (no base section)
        return ["<<<<<<< HEAD", *body, "=======", *other, ">>>>>>> branch"]
    if kind == 3:                                            # unterminated open — prose, not a hunk
        return ["<<<<<<< see below for an example", *body, "=======", *other]
    if kind == 4:                                            # a close with no open
        return [*body, ">>>>>>> end example", *other]
    return ["<<<<<<< outer", *body, "<<<<<<< inner", *other,  # nested open inside `ours`
            "||||||| base", "=======", *other, ">>>>>>> theirs"]


def generated(n: int = 420):
    """Seeded pseudo-random documents assembled from `_chunk`, so a failure is reproducible."""
    rng = random.Random(20260910)
    for k in range(n):
        body: list[str] = []
        for _ in range(rng.randint(1, 4)):
            body += _chunk(rng)
        yield f"generated:{k}", "\n".join(body)


ADVERSARIAL = {
    # Prose that merely illustrates conflict syntax — the S-H1 trigger, and a real shape in this
    # repo's own SKILL.md / decisions.md.
    "coincidental-brackets": (
        "### [tp-plan] a decision\n<<<<<<< see below for an example\nSome Section\n"
        "=======\n>>>>>>> end example\nreal tail that matters\n"),
    # An unterminated open plus an unrelated close far downstream — round 9's cross-entry pairing
    # shape, here as a resolver input.
    "brackets-spanning-entries": (
        "### [tp-plan] d1\n<<<<<<< ours\nsome ours text\n### [tp-plan] d2\nbody two\n"
        "=======\ntail content\n### [tp-plan] d3\nbody three\n>>>>>>> theirs\n"),
    "unterminated-region": (
        "### [tp-plan] a decision\n<<<<<<< ours\nours side content\n=======\n"
        "theirs side content\ntail with no closing marker\n"),
    # `=======` as a setext underline and `|||||||` as an empty-cell table row, with no conflict
    # anywhere — ordinary markdown that must not open or close anything.
    "markers-as-body-content": (
        "Section Title\n=======\nreal content under the rule\n| h | h |\n| --- | --- |\n"
        "|||||||\nreal content after the row\n"),
    "two-way-region-then-real-conflict": COINCIDENTAL_PROSE_THEN_CONFLICT,
    "crlf-and-trailing-blank": "# Doc\r\n\r\nbody\r\n\n\n",
    # S-I2 — a `=======`-prefixed CONTENT line inside a diff3 region's `ours`. Only ONE separator
    # is structural (the one after `|||||||`); cutting at the first prefix-match deleted this line.
    "mid-region-separator-lookalike": (
        "<<<<<<< ours\n### L4: ours\n======= see example above\n||||||| base\n=======\n"
        "### L4: theirs\n>>>>>>> theirs\n"),
    # S-I1 — an inventory row on ours, unkeyed prose on theirs, inside an over-merged region. The
    # row-merge resolver had no key for the prose and dropped it under a RESOLVED verdict.
    "inventory-row-with-unkeyed-theirs": (
        "<<<<<<< stray\n| D12 | ours row |\n=======\n<<<<<<< nested-open text\n"
        "this trailing important sentence must survive\n>>>>>>> theirs\n"),
    # S-I3 — two ADJACENT regions: the second one's `pre_context` is only reachable by looking
    # back PAST the first hunk, and without it a Current-Focus row merges as an inventory row.
    "adjacent-regions-under-current-focus": (
        "## Current Focus\n"
        "<<<<<<< ours\n| 1 | alpha | act | — |\n||||||| base\n=======\n| 2 | beta | act | — |\n"
        ">>>>>>> theirs\n"
        "<<<<<<< ours\n| 3 | gamma | act | — |\n| D12 | d | design | OURS |\n||||||| base\n"
        "=======\n| 4 | delta | act | — |\n| D12 | d | design | THEIRS |\n>>>>>>> theirs\n"),
}


def corpus():
    docs = [(f"fixture:{name}", text) for name, text in ALL_FIXTURES]
    docs += [(f"adversarial:{k}", v) for k, v in sorted(ADVERSARIAL.items())]
    docs += list(generated())
    return docs
