"""Shared real-format conflict fixtures — the ONE copy, imported by the resolver tests and by the
cross-module coverage test (`test_verify_classify_coverage.py`).

Test-only support module. It is deliberately NOT named `test_*`, so pytest does not collect it.

`ALL_FIXTURES` is a list of `(name, conflict_text)` that must cover **every** member of
`classify.AUTO_RESOLVE`, plus a deferring prose control and the fixture of the GATED
`id-renumber-collision` (which defers). Both the reverse coverage assertion and
`test_corpus_covers_all_auto_resolve_classes` depend on that completeness: a future sixth
mechanical class cannot land without a fixture here.

Every fixture is a real shape, not an invented one:
  * the log shapes are the live `## History` / `### Recent completions` forms;
  * the decisions shapes are modelled on real files in this repo — including the nested-atom
    fixture, which follows `three-pillars-docs/completed-tp-designs/basesync-prepend-log/
    decisions.md:124`, where a decision entry's Reasoning body opens with a `LOG`-shaped changelog
    bullet. That is measured, not hypothetical: 3 of 11,702 entry-body lines across this repo's
    102 real `decisions.md` files already match `LOG`.
"""


def diff3(ours: str, base: str, theirs: str, pre: str = "") -> str:
    """A `git merge-file --diff3` conflict block with a NON-empty in-hunk base."""
    block = ("<<<<<<< ours\n" + ours + "\n||||||| base\n" + base + "\n=======\n"
             + theirs + "\n>>>>>>> theirs")
    return (pre + "\n" + block) if pre else block


def diff3_empty_base(ours: str, theirs: str, pre: str = "") -> str:
    """The EMPTY-base shape real `git merge-file --diff3` minimizes a concurrent insertion to —
    no line at all between `||||||| base` and `=======`.

    NOT interchangeable with `diff3(ours, "", theirs)`, which emits one blank line there and so
    yields a base of `[""]`. Empty base is the load-bearing soundness signal for both insertion
    classes (it proves neither side deleted anything), so the distinction is load-bearing.
    """
    block = ("<<<<<<< ours\n" + ours + "\n||||||| base\n=======\n" + theirs + "\n>>>>>>> theirs")
    return (pre + "\n" + block) if pre else block


LIVING_DOC_KIND = "living-doc"  # the FileOutcome.kind of a living-doc outcome


# ---- log-entry-insertion (the two live log shapes) -------------------------------------------

NAME_KEYED_LOG = diff3_empty_base(
    "- **`design-a`** — Implemented (2026-07-04).",
    "- **`design-b`** — Done — archived (2026-07-05).",
    pre="### Recent completions",
)

WRAPPED_DATED_LOG = diff3_empty_base(
    "- **2026-07-04** — decision OURS\n\n  rationale ours line",
    "- **2026-07-05** — decision THEIRS\n\n  rationale theirs line",
    pre="## History",
)

# Tightness control — an insertion that is NOT clean log bullets. Labelled `generic-prose`, so it
# is outside AUTO_RESOLVE and the forward coverage assertion skips it by construction.
NONLOG_PROSE_DEFER = diff3_empty_base(
    "- **2026-07-04** — real entry",
    "an arbitrary concurrent prose paragraph, not a log entry",
    pre="## History",
)

# ---- id-renumber-collision -------------------------------------------------------------------

# The EMPTY base two pure insertions at one point produce: since round 18 (R2) that is the only
# shape the class admits, so `diff3(ours, "", theirs)` — a base of one blank line — no longer is.
# The class is GATED since round 20 (`classify.GATED`): this fixture classifies as the class and
# DEFERS with code `gated`; it is kept so the classifier and the dormant resolver stay pinned.
ID_RENUMBER = "### L3: prior\n" + diff3_empty_base(
    "### L4: ours unique",
    "### L4: theirs a\n### L5: theirs b\n### L6: theirs c",
)

# ---- design-inventory-row-merge --------------------------------------------------------------

# A THREE-WAY row merge (round 17, F3): theirs edited `D12`, which ours left as base, and each side
# added a row. The previous fixture had an empty base and DIFFERENT `D12` rows on both sides — "both
# added D12 differently", which the base-aware resolver correctly refuses; the old resolver
# resolved it by discarding ours' row.
INVENTORY_ROW_MERGE = diff3(
    "| D12 | a | design | x |\n| D15 | c | design | x |",
    "| D12 | a | design | x |",
    "| D12 | a | design | THEIRS |\n| D14 | b | design | y |",
)

# ---- append-only-log -------------------------------------------------------------------------
#
# A synthetic in-hunk-base append (real git minimization factors the base OUT, so this shape only
# arises from non-minimized input — but the CLASS is live and must carry a fixture). The tails are
# real dated `## History` bullets rather than placeholder text, because the forward coverage
# assertion requires every mechanical hunk to yield at least one atom.

_APPEND_BASE = "- **2026-07-01** — seed entry"
APPEND_ONLY_LOG = diff3(
    _APPEND_BASE + "\n- **2026-07-04** — ours tail",
    _APPEND_BASE,
    _APPEND_BASE + "\n- **2026-07-05** — theirs tail",
    pre="## History",
)

# ---- decision-entry-insertion (three decisions.md shapes) ------------------------------------


def _entry(tag: str, title: str, *body: str) -> str:
    return f"### [{tag}] {title}\n" + "\n".join(body)


# (a) the OBSERVED 50/52-entry shape — the wrapped `**Question**/**Decided**/**Reasoning**/
#     **Confidence**` body, and both the plain and slash-bearing skill-tag forms.
DECISIONS_OBSERVED = diff3_empty_base(
    _entry("tp-promote", "cockpit-ready-signal — batched confirm",
           "**Question**: promote the seed as-is?",
           "**Decided**: yes — light weight class, one phase",
           "**Reasoning**: the seed already scoped the fix narrower than the defect,",
           "  and widening it here would re-open the trigger-condition debate",
           "**Confidence**: High"),
    _entry("tp-run-full-design/tier-1", "pickup — Mode B, weight-class light",
           "**Question**: which tier-1 mode?",
           "**Decided**: Mode B",
           "**Reasoning**: design.md already exists and is audit-clean",
           "**Confidence**: High"),
    pre="# Decisions — zero-drop-verifier-unverifiable",
)

# (b) the COLLISION regression pin — same tag AND same title on both sides, different bodies.
#     Modelled on the real `worktree-fleet` log, which carries `### [orchestrator/plan-audit] clip`
#     twice. Under a title-only or `(tag, title)` signature these fold into ONE atom and a drop of
#     one verifies clean; under the whole-block signature they are two distinct atoms.
DECISIONS_COLLISION = diff3_empty_base(
    _entry("orchestrator/plan-audit", "clip",
           "**Decided**: kept finding 1 — the consumer inventory must be exhaustive",
           "**Confidence**: High"),
    _entry("orchestrator/plan-audit", "clip",
           "**Decided**: kept finding 2 — the coverage test needs a reverse arm",
           "**Confidence**: Medium"),
    pre="# Decisions — worktree-fleet",
)

# (c) the NESTED-ATOM fixture — a decision entry whose Reasoning body opens with a `LOG`-shaped
#     changelog bullet. Follows the REAL entry at `three-pillars-docs/completed-tp-designs/
#     basesync-prepend-log/decisions.md:124`. Its purpose is to pin the intended double-capture:
#     the body bullet yields a standalone `log` atom ALONGSIDE the enclosing `decision-entry`
#     atom, the two keys do not collide, and dropping either is reported.
DECISIONS_NESTED = diff3_empty_base(
    _entry("REDESIGN AS-BUILT 2026-07-06", "shipped + dogfood-gated — the PLAN executed",
           "**Reasoning**: landed on the design branch:",
           "- **`fde5bdc1`** — classify.py: log-entry-insertion now fires on an empty base",
           "- **`6bd988d0`** — real-format fixtures rewritten to the bold-lead-bullet forms",
           "**Confidence**: High"),
    _entry("tp-design-learn", "living-doc entries trimmed",
           "**Decided**: drop the overclaiming entries and re-run learn+complete",
           "**Confidence**: Medium"),
    pre="# Decisions — basesync-prepend-log",
)


# ---- keyed-heading-insertion ------------------------------------------------------------------

# The live `known_issues.md` shape: both sides filed an issue entry at one point, ours a numbered
# `### M48:` and theirs a placeholder `### M-new-reset:` (so no sort applies and ours comes first),
# and the next line is the following level-3 heading the class requires after the region.
KEYED_HEADING = diff3_empty_base(
    "### M48: ours issue\nbody ours\n",
    "### M-new-reset: theirs issue\nbody theirs\n",
    pre="## Medium\n",
) + "\n### L1: next entry\nbody\n"


# ---- last-updated-preamble -------------------------------------------------------------------

# The live preamble shape: both branches bumped the one-line `*Last updated:*` date under the title,
# date only, each from the base's older date, with a blank line and a section heading after it.
LAST_UPDATED_PREAMBLE = diff3(
    "*Last updated: 2026-06-02*", "*Last updated: 2026-06-01*", "*Last updated: 2026-06-03*",
    pre="# Roadmap",
) + "\n\n## Current State\n"


# ---- keyed-row-insertion ----------------------------------------------------------------------

# The `product_roadmap_archive.md` shape once each branch moves its own Design Inventory row before
# merging (design-complete-final-doc-state, Behavior 6): both append one slug-keyed row to the end
# of one archive table, an empty-base region that ends the file.
KEYED_ROW_INSERTION = diff3_empty_base(
    "| b-design | What for b. | Done (completion PR) |",
    "| `a-design` | What for a. | Done — PR #12 |",
    pre="### Active\n\n| Design | What | Status |\n|---|---|---|\n| prior | A prior row. | Done — PR #9 |",
) + "\n"


# ---- shaped-line-merge --------------------------------------------------------------------------

# The #219 shape: a slug-keyed table whose row theirs moved on (`Planned` -> `Done`) while each side
# appended a row of its own. The table header and delimiter sit above the region as clean context,
# so the hunk holds rows only; the merge is theirs' edited row, theirs' new row, then ours'.
_SLUG_ROW = "| `ci-settle-statuscontext` | settle the status context | Planned |"
SHAPED_LINE_MERGE = diff3(
    _SLUG_ROW + "\n| `ours-new` | ours row | Planned |",
    _SLUG_ROW,
    _SLUG_ROW.replace("Planned", "Done") + "\n| `theirs-new` | theirs row | Planned |",
    pre="| Slug | Note | Status |\n| --- | --- | --- |",
)


# ---- S-H1: coincidental conflict-syntax prose ahead of a genuine region ----------------------
#
# NOT a member of `ALL_FIXTURES` — it is not a class fixture but a malformed-input repro, shared
# by `test_resolve_preservation.py` (the drop itself) and `test_resolve_invariants.py` (the
# preservation invariants). One copy, because two copies drift.
#
# The first region has NO `|||||||`, so the old scan — which terminated `ours` only on `|||||||` —
# ran on past its own `=======` and `>>>>>>>`, swallowed the genuine conflict below it, and
# PERMANENTLY DROPPED the opening prose line under a RESOLVED verdict.
PROSE_OPEN = "<<<<<<< see below for an example"
COINCIDENTAL_PROSE_THEN_CONFLICT = "\n".join([
    PROSE_OPEN,
    "some illustrative text",
    "=======",
    ">>>>>>> end example",
    "unrelated clean line",
    "<<<<<<< ours.txt",
    "### L4: ours",
    "||||||| base.txt",
    "=======",
    "### L4: theirs",
    ">>>>>>> theirs.txt",
])


# ---- low-count-line ----------------------------------------------------------------------------

# The live `known_issues.md` shape (replay 306): both sides edit the one `N Low issues →` count
# line that ends the Medium section, and theirs also inserts two keyed entries above it. The
# `### M77:` heading is this fixture's verify atom.
_COUNT_REST = ("Low issues → [known_issues_low.md](known_issues_low.md) (one line each; promote "
               "a Low to Medium by moving its entry back into this doc in the same commit).")
LOW_COUNT_LINE = diff3(
    "215 " + _COUNT_REST,
    "213 " + _COUNT_REST,
    "### M77: M77 title\n- M77 body\n\n### M78: M78 title\n- M78 body\n\n222 " + _COUNT_REST,
    pre="### M76: x\n- body\n",
) + "\n\n## History\n"


ALL_FIXTURES = [
    ("name-keyed-log", NAME_KEYED_LOG),
    ("wrapped-dated-log", WRAPPED_DATED_LOG),
    ("nonlog-prose-defer", NONLOG_PROSE_DEFER),
    ("id-renumber", ID_RENUMBER),
    ("inventory-row-merge", INVENTORY_ROW_MERGE),
    ("append-only-log", APPEND_ONLY_LOG),
    ("decisions-observed", DECISIONS_OBSERVED),
    ("decisions-collision", DECISIONS_COLLISION),
    ("decisions-nested", DECISIONS_NESTED),
    ("keyed-heading-insertion", KEYED_HEADING),
    ("last-updated-preamble", LAST_UPDATED_PREAMBLE),
    ("keyed-row-insertion", KEYED_ROW_INSERTION),
    ("shaped-line-merge", SHAPED_LINE_MERGE),
    ("low-count-line", LOW_COUNT_LINE),
]
