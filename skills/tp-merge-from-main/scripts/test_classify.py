"""Unit tests for the structural conflict classifier."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from classify import (  # noqa: E402
    AUTO_RESOLVE,
    MECHANICAL,
    SEMANTIC,
    Hunk,
    classify_file,
    is_confident,
    parse_conflict,
)
from resolve import DEFER, RESOLVED, resolve_file  # noqa: E402


def _diff3(ours, base, theirs, pre=""):
    block = "<<<<<<< ours\n" + ours + "\n||||||| base\n" + base + "\n=======\n" + theirs + "\n>>>>>>> theirs"
    return (pre + "\n" + block) if pre else block


def labels(text):
    pf = classify_file(text)
    return [s.label for s in pf.segments if isinstance(s, Hunk)]


def test_preamble():
    # a date-only triple is the mechanical `last-updated-preamble` now (`keyed_classes`)...
    t = _diff3("*Last updated: 2026-05-17*", "*Last updated: 2026-05-15*", "*Last updated: 2026-05-16*")
    assert labels(t) == ["last-updated-preamble"]
    assert "last-updated-preamble" in MECHANICAL
    # ...a richer region (an extra prose line on one side) is still the semantic `preamble`
    t = _diff3("*Last updated: 2026-05-17*\nA second prose line.", "*Last updated: 2026-05-15*",
               "*Last updated: 2026-05-16*")
    assert labels(t) == ["preamble"]
    assert "preamble" in SEMANTIC


def test_id_renumber_collision():
    t = _diff3_empty_base("### L4: ours entry\nbody",
                          "### L4: theirs entry\nbody2\n### L5: another")
    assert labels(t) == ["id-renumber-collision"]
    assert "id-renumber-collision" in MECHANICAL


def test_design_inventory_row():
    t = _diff3("| D12 | foo | design | x |", "", "| D12 | foo | design | y |\n| D14 | bar | design | z |")
    assert labels(t) == ["design-inventory-row-merge"]


def test_current_focus_is_semantic():
    pre = "## Current Focus\n\n| Priority | Design | Next Action | Blocked By |"
    t = _diff3("| 3 | foo | act | — |", "", "| 3 | foo | other-act | — |", pre=pre)
    out = labels(t)
    assert out == ["current-focus-reprioritization"]
    assert "current-focus-reprioritization" in SEMANTIC


def test_generic_prose_defaults_semantic():
    t = _diff3("Some prose here.", "Base prose.", "Other prose here.")
    assert labels(t) == ["generic-prose"]


def test_append_only_log():
    # Round 19 (P2): two differing tails must each be whole log entries. The plain `ours tail` /
    # `theirs tail` this used to classify is exactly the shape that re-parents theirs' first line
    # under ours' last one, so it is `generic-prose` now; the one-sided tail still classifies.
    base = "- **2026-07-01** — a\n- **2026-07-02** — b"
    t = _diff3(base + "\n- **2026-07-03** — ours", base, base + "\n- **2026-07-04** — theirs")
    assert labels(t) == ["append-only-log"]
    assert labels(_diff3("line a\nline b\nours tail", "line a\nline b",
                         "line a\nline b\ntheirs tail")) == ["generic-prose"]
    assert labels(_diff3("line a\nours tail", "line a", "line a")) == ["append-only-log"]


def _diff3_empty_base(ours, theirs, pre=""):
    # Real git-minimized concurrent-insertion shape: EMPTY base (no line between the base markers).
    # NOT the same as `_diff3(ours, "", theirs)`, which emits one blank line there and so yields a
    # base of `[""]` — non-empty, and therefore NOT a pure insertion to either insertion class.
    block = "<<<<<<< ours\n" + ours + "\n||||||| base\n=======\n" + theirs + "\n>>>>>>> theirs"
    return (pre + "\n" + block) if pre else block


def test_log_entry_insertion_dated_bullet_real_empty_base_shape():
    # The REAL git-minimized shape: empty base, both sides insert a dated bold-lead-bullet entry
    # (architecture.md `## History` form) — what `git merge-file --diff3` actually produces.
    t = _diff3_empty_base("- **2026-07-04** — decision OURS", "- **2026-07-05** — decision THEIRS",
                          pre="## History")
    assert labels(t) == ["log-entry-insertion"]
    assert "log-entry-insertion" in MECHANICAL


def test_log_entry_insertion_name_keyed_bullet():
    # product_roadmap.md `### Recent completions` form: name-keyed `- **`slug`** — …` bullets.
    t = _diff3_empty_base("- **`design-a`** — Implemented (2026-07-04).",
                          "- **`design-b`** — Done — archived (2026-07-05).",
                          pre="### Recent completions")
    assert labels(t) == ["log-entry-insertion"]


def test_log_entry_insertion_wrapped_multiline_entry():
    # An entry that WRAPS across a blank + indented continuation body must STILL classify as a log
    # insertion (the correctness point: continuation lines are allowed — not every line is a bullet).
    ours = "- **2026-07-04** — decision OURS\n\n  rat ours"
    theirs = "- **2026-07-05** — decision THEIRS\n\n  rat theirs"
    t = _diff3_empty_base(ours, theirs, pre="## History")
    assert labels(t) == ["log-entry-insertion"]


def test_log_entry_insertion_defers_on_nonlog_prose():
    # Tightness: a side whose insertion is arbitrary prose (not a log bullet) is NOT a clean log
    # insertion -> defer to a human. The bullet-block restriction still limits keep-both.
    t = _diff3_empty_base("- **2026-07-04** — real entry", "just some concurrent prose paragraph",
                          pre="## History")
    assert labels(t) == ["generic-prose"]


def test_log_entry_insertion_defers_on_file_path_bullet():
    # Tightness: file-path description bullets (Canon-reframe style) look bold-lead but are NOT log
    # entries — the kebab-slug arm excludes `/`/`.`, so they defer to a human.
    t = _diff3_empty_base("- **`scripts/foo.py`** — a build helper",
                          "- **`scripts/bar.py`** — another helper")
    assert labels(t) == ["generic-prose"]


# ---- Fix B: decision-entry-insertion (`three-pillars-docs/tp-designs/*/decisions.md`) -------

_D_OURS = ("### [tp-plan] weight class kept at light\n"
           "**Question**: escalate to full?\n"
           "**Decided**: no — one phase\n"
           "**Reasoning**: the seed scoped it narrowly\n"
           "**Confidence**: High")
_D_THEIRS = ("### [tp-plan-audit] council round 1\n"
             "**Question**: which findings bind?\n"
             "**Decided**: 1 and 3\n"
             "**Reasoning**: 2 was already covered\n"
             "**Confidence**: Medium")


def test_decision_entry_insertion_classified():
    t = _diff3_empty_base(_D_OURS, _D_THEIRS)
    assert labels(t) == ["decision-entry-insertion"]
    assert "decision-entry-insertion" in MECHANICAL
    assert "decision-entry-insertion" in AUTO_RESOLVE     # not GATED
    pf = classify_file(t)
    hunk = [s for s in pf.segments if isinstance(s, Hunk)][0]
    assert is_confident(hunk) is True


def test_decision_entry_insertion_purity_fail_closed():
    """A decision entry mixed with foreign structure never reaches `decision-entry-insertion`.

    The expected LABEL is pinned per foreign line rather than asserted disjunctively. The
    disjunction `label != "decision-entry-insertion" or not is_confident(hunk)` hid the fact that
    the three cases did NOT behave alike: an inventory row used to be CLAIMED by a different
    mechanical class, which auto-resolved and dropped theirs' decision entry (known-issue H8).
    Naming the label per case is what made that visible. Round 12 gave the inventory arm its own
    purity predicate, so all three now fall closed to a semantic class — and the per-case pinning
    stays, because it is what would show a future arm re-claiming one of them.
    """
    expected = {
        # foreign line                        -> (label, is this hunk auto-resolved?)
        "| D12 | some-design | shipped |": ("generic-prose", False),
        "### L4: an issue heading": ("generic-prose", False),
        "*Last updated: 2026-05-01*": ("preamble", False),
    }
    for foreign, (label, auto_resolves) in expected.items():
        t = _diff3_empty_base(_D_OURS + "\n" + foreign, _D_THEIRS)
        pf = classify_file(t)
        hunk = [s for s in pf.segments if isinstance(s, Hunk)][0]
        assert hunk.label == label, (foreign, hunk.label)
        # The property this test is actually FOR: the mixed hunk is never this class.
        assert hunk.label != "decision-entry-insertion", foreign
        assert (hunk.label in MECHANICAL and is_confident(hunk)) is auto_resolves, foreign


def test_decision_entry_mixed_with_inventory_row_now_falls_closed():
    """Known-issue H8, closed at its root — the inventory arm's missing purity gate.

    `classify_hunk` tested `INV_ROW` before every later arm with NO purity check, so a hunk
    carrying one inventory row alongside decision entries was labelled
    `design-inventory-row-merge`, was confident, and RESOLVED — merging the rows and DISCARDING
    theirs' decision entry. The drop was caught only downstream, and only because a decision entry
    happens to be an atom the verifier can see; the same hunk with plain prose on theirs' side was
    lost silently under a RESOLVED verdict.

    Now `_is_inventory_row_merge` requires BOTH sides to be pure inventory-table blocks, so the
    mixed hunk falls through to `generic-prose` and defers with every line intact. Pinned here so
    the precedence bug cannot come back.
    """
    t = _diff3_empty_base(_D_OURS + "\n| D12 | some-design | shipped |", _D_THEIRS)
    pf = classify_file(t)
    hunk = [s for s in pf.segments if isinstance(s, Hunk)][0]
    assert hunk.label == "generic-prose"
    assert hunk.label not in MECHANICAL
    status, lines, _results = resolve_file(t)
    assert status == DEFER
    merged = "\n".join(lines)
    assert "weight class kept at light" in merged        # ours' entry survives
    assert "council round 1" in merged                   # theirs' entry survives — the H8 drop
    assert merged == t, "a deferral must hand the region back byte-for-byte"


def test_decision_entry_insertion_purity_fail_closed_other_shapes():
    """The three non-purity shapes, each pinned to its EXACT label and to "not auto-resolving".

    `label != "decision-entry-insertion"` alone is too weak — it would pass just as happily if a
    future change misrouted one of these into a DIFFERENT `MECHANICAL`/`AUTO_RESOLVE` class that
    drops content (exactly what the inventory-row case above actually does). Falling closed means
    landing on a SEMANTIC class and deferring, so that is what gets asserted. The sibling test
    directly above was strengthened for this same reason.
    """
    cases = {
        # A non-empty base is a modification, not a pure insertion.
        "non-empty base": _diff3(_D_OURS, "### [tp-plan] a prior entry\n**Decided**: x", _D_THEIRS),
        # Both sides must contribute an insertion.
        "one-sided insertion": _diff3_empty_base(_D_OURS, ""),
        # A block that does not START with a decision-entry heading.
        "stray leading prose": _diff3_empty_base("stray prose\n" + _D_OURS, _D_THEIRS),
    }
    for name, t in cases.items():
        pf = classify_file(t)
        hunk = [s for s in pf.segments if isinstance(s, Hunk)][0]
        assert hunk.label == "generic-prose", (name, hunk.label)
        assert hunk.label in SEMANTIC, (name, hunk.label)
        assert hunk.label not in AUTO_RESOLVE, (name, hunk.label)
        # ...and the resolver really does leave it for a human, markers intact.
        status, lines, results = resolve_file(t)
        assert status != RESOLVED, name
        assert [r.status for r in results] == [DEFER], name
        assert "<<<<<<<" in "\n".join(lines), name


def test_decision_entry_hunk_is_not_log_entry_insertion():
    # The two insertion classes are mutually exclusive by their opening line — one starts with
    # `- **`, the other with `### [`.
    assert labels(_diff3_empty_base(_D_OURS, _D_THEIRS)) == ["decision-entry-insertion"]
    log_hunk = _diff3_empty_base("- **2026-07-04** — decision OURS", "- **2026-07-05** — decision THEIRS")
    assert labels(log_hunk) == ["log-entry-insertion"]


def test_decision_entry_nested_log_bullet_still_pure():
    # The real nested shape (basesync-prepend-log/decisions.md:124): a decision entry whose
    # Reasoning body carries a LOG-shaped changelog bullet. The bullet is a plain body line to
    # the classifier — not foreign — so the block stays insertion-pure.
    nested = (_D_OURS + "\n- **`fde5bdc1`** — classify.py: the log class now fires on empty base")
    assert labels(_diff3_empty_base(nested, _D_THEIRS)) == ["decision-entry-insertion"]


def test_parse_roundtrip_multiple_hunks():
    t = "clean head\n" + _diff3("*Last updated: x*", "*Last updated: w*", "*Last updated: y*") + \
        "\nmiddle\n" + _diff3("### L4: a", "", "### L4: b")
    pf = parse_conflict(t)
    hunks = [s for s in pf.segments if isinstance(s, Hunk)]
    assert len(hunks) == 2
    # second hunk should carry the 'middle' pre-context line
    assert hunks[1].pre_context == "middle"


def test_known_issues_low_file_shape_is_the_same_class_as_known_issues():
    """skill-context-diet 2.2 (D5b): `known_issues_low.md` is the same living-doc class.

    The low file holds one-line `### L<n>:` entries in newest-first order, so a base-sync
    conflict there is byte-for-byte the shape `known_issues.md` produces (see
    `conflict_fixtures`' live known_issues shape): two concurrent ID-heading insertions.
    The classifier sees no path, only line shape, so the same class must answer here —
    a class it already gives `known_issues.md`. Pinning the shape is what keeps the low
    file inside the base-sync lane when it lands as a new living doc.
    """
    t = _diff3_empty_base("### L63: ours Low entry", "### L64: theirs Low entry",
                          pre="## Low issues")
    assert labels(t) == labels(_diff3_empty_base("### L63: ours entry", "### L64: theirs entry",
                                                 pre="## Medium"))
    assert labels(t) == ["keyed-heading-insertion"]
    assert "keyed-heading-insertion" in AUTO_RESOLVE
