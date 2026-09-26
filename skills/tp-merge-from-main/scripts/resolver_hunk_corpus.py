"""A generated corpus of HUNKS — the adversary for the resolver-totality invariant.

Test-only support module (deliberately not named `test_*`), and the third corpus in this
directory, each aimed at a different observer:

  * `conflict_fixtures`   — ground truth, one real shape per resolver class.
  * `preservation_corpus` — whole DOCUMENTS of marker soup, aimed at the PARSER.
  * this module           — whole HUNKS whose sides are drawn from the resolver classes'
                            vocabularies, aimed at the RESOLVERS.

The distinction matters for non-vacuity. `preservation_corpus`'s documents are random content, so
almost every hunk in them classifies `generic-prose` and DEFERS — a resolver invariant run over it
alone would be checking a handful of fixtures. Here every side is built from the lines a mechanical
class actually recognises (log bullets, decision entries, inventory rows, ID headings), with
foreign lines and marker look-alikes mixed in at a rate that keeps a healthy population on BOTH
sides of the decision: hundreds that resolve (so the invariant has something to check) and hundreds
that defer (so the fall-closed direction is exercised too).

Generation is SEEDED, so a failing hunk is reproducible from its `hunk:<k>` name.
"""
from __future__ import annotations

import random

# Per-class vocabularies — the lines each mechanical resolver is built to recognise.
LOG = ["- **2026-07-04** — ours entry", "- **2026-07-05** — theirs entry",
       "  wrapped rationale line", "", "- **`design-slug`** — Implemented (2026-07-06)."]
DECISION = ["### [tp-plan] a decision", "### [tp-run-full-design/tier-1] pickup",
            "**Question**: which mode?", "**Decided**: Mode B", "**Confidence**: High", ""]
INVENTORY = ["| D12 | a | design | OURS |", "| D12 | a | design | THEIRS |",
             "| D14 | b | design | y |", "| D15 | c | design | z |",
             "| Design | Name | Kind | Status |", "| --- | --- | --- | --- |", ""]
IDS = ["### L4: an entry", "### L5: another entry", "a body line", "see L5 for detail",
       "### D7: a decision heading", ""]
PLAIN = ["ordinary prose that must survive", "  indented continuation", "## A Section",
         "another paragraph of prose"]
# The lines that make a side IMPURE for whichever class claimed it — including the marker
# look-alikes S-I2 is about, which no mechanical class may act on.
FOREIGN = ["*Last updated: 2026-07-04*", "| 3 | some-design | next action | — |",
           "### L9: a stray id heading", "======= see example above",
           "<<<<<<< see below for an example", "||||||| a table row of empty cells",
           ">>>>>>> end of example", "| D99 | sneaky | row | x |"]

VOCAB = {"log": LOG, "decision": DECISION, "inventory": INVENTORY, "ids": IDS, "plain": PLAIN}


def _side(rng: random.Random, bucket: str) -> list[str]:
    lines = [rng.choice(VOCAB[bucket]) for _ in range(rng.randint(1, 4))]
    if rng.random() < 0.35:                      # salt with a foreign / marker-look-alike line
        lines.insert(rng.randrange(len(lines) + 1), rng.choice(FOREIGN))
    return lines


def _block(lines: list[str]) -> str:
    return "\n".join(lines)


def generated_hunks(n: int = 700):
    """Seeded `(name, conflict_text)` pairs, one conflict region each (plus a clean pre-context
    line, so `classify_hunk`'s context-sensitive arms are exercised too)."""
    rng = random.Random(20260912)
    pres = ["## History", "## Current Focus", "### Recent completions", "# Decisions — a-design",
            "## Design Inventory", ""]
    for k in range(n):
        bucket = rng.choice(list(VOCAB))
        ours, theirs = _side(rng, bucket), _side(rng, rng.choice([bucket, rng.choice(list(VOCAB))]))
        shape = rng.randint(0, 3)
        if shape == 0:                            # empty base — the real minimized insertion shape
            base_section = "||||||| base\n"
        elif shape == 1:                          # a base with content — a modification
            base_section = "||||||| base\n" + _block(_side(rng, bucket)) + "\n"
        elif shape == 2:                          # 2-way, no base section at all
            base_section = ""
        else:                                     # append shape: base is a common prefix of both
            shared = _side(rng, bucket)
            ours, theirs = shared + ours, shared + theirs
            base_section = "||||||| base\n" + _block(shared) + "\n"
        pre = rng.choice(pres)
        text = ("<<<<<<< ours\n" + _block(ours) + "\n" + base_section
                + "=======\n" + _block(theirs) + "\n>>>>>>> theirs")
        yield f"hunk:{k}", ((pre + "\n") if pre else "") + text
