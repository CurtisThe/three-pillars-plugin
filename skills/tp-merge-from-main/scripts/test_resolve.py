"""Unit tests for the mechanical resolvers + deferral.

`id-renumber-collision` is GATED in production (round 20, `classify.GATED`). The
`test_id_renumber_*` and `test_xref_*` cases below exercise the gated resolver with the gate lifted
for that test only (`ungated_renumber`); they pin the dormant resolver, not a production merge.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from resolve import resolve_file, RESOLVED, DEFER  # noqa: E402
from test_resolve_three_way import ungated_renumber  # noqa: E402,F401 — a pytest fixture


def _diff3(ours, base, theirs, pre=""):
    block = "<<<<<<< ours\n" + ours + "\n||||||| base\n" + base + "\n=======\n" + theirs + "\n>>>>>>> theirs"
    return (pre + "\n" + block) if pre else block


def test_id_renumber_is_zero_drop_and_moves_only_the_colliding_id(ungated_renumber):
    # ours claims L4; theirs claims L4,L5,L6. Only L4 COLLIDES, so only theirs' L4 moves — to L7,
    # above every same-letter heading in the file (round 17, F4). Theirs' L5/L6 are new and unique
    # already; the old resolver renumbered them too (L5->L6, L6->L7), i.e. without a collision.
    t = "### L3: prior\n" + _diff3_empty_base(
        "### L4: ours unique",
        "### L4: theirs a\n### L5: theirs b\n### L6: theirs c",
    )
    status, lines, results = resolve_file(t)
    assert status == RESOLVED
    heads = [l for l in lines if l.startswith("### ")]
    assert heads == ["### L3: prior", "### L4: ours unique", "### L7: theirs a",
                     "### L5: theirs b", "### L6: theirs c"], heads
    nums = [h.split(":")[0] for h in heads]
    assert len(nums) == len(set(nums)), "every ID in the result is unique"
    assert results[0].renumbered == {"L4": "L7"}


def test_id_renumber_updates_cross_references(ungated_renumber):
    t = _diff3_empty_base(
        "### L4: ours",
        "### L4: theirs (see L4 above; detail in L5)\n### L5: detail",
    )
    _, lines, results = resolve_file(t)
    text = "\n".join(lines)
    # theirs' L4 -> L6 (above the file's highest ID, L5); its bare self-reference follows it, and
    # the reference to theirs' un-moved L5 is left alone.
    assert results[0].renumbered == {"L4": "L6"}
    assert "### L6: theirs (see L6 above; detail in L5)" in text, text
    assert "### L5: detail" in text


def test_xref_rewrite_maps_each_reference_once(ungated_renumber):
    # The single-pass rewrite, on the one kind of remap the resolver can now produce: an old ID
    # whose new number is above every same-letter heading in the file, so nothing can cascade.
    t = _diff3_empty_base(
        "### L4: ours",
        "### L4: theirs (refs L4 and L5)\n### L5: detail",
    )
    _, lines, results = resolve_file(t)
    text = "\n".join(lines)
    assert "refs L6 and L5" in text, text
    assert "### L6: theirs" in text and "### L5: detail" in text
    assert text.count("### L6:") == 1


def test_inventory_three_way_keeps_both_sides_edits_zero_row_drop():
    # base D12; theirs edited it, ours left it and added D15; theirs added D14. Each side's edit
    # survives (round 17, F3: the old resolver ignored base and always took theirs' row).
    t = _diff3(
        "| D12 | a | design | x |\n| D15 | c | design | x |",
        "| D12 | a | design | x |",
        "| D12 | a | design | THEIRS |\n| D14 | b | design | y |",
    )
    status, lines, _ = resolve_file(t)
    assert status == RESOLVED
    ids = [l for l in lines if l.startswith("| D")]
    assert ids == ["| D12 | a | design | THEIRS |", "| D15 | c | design | x |",
                   "| D14 | b | design | y |"], ids


def test_inventory_both_sides_adding_one_id_differently_defers():
    t = _diff3("| D12 | a | design | OURS |", "", "| D12 | a | design | THEIRS |")
    status, lines, results = resolve_file(t)
    assert status == DEFER and results[0].code == "cannot-place", results[0].reason
    assert "\n".join(lines) == t


def test_inventory_preserves_header_and_separator_lines():
    # Regression (Feynman CRITICAL #6): non-ID lines (header, separator, blanks) must survive.
    t = _diff3(
        "| Design | Name | Status |\n| --- | --- | --- |\n| D12 | a | x |",
        "| D12 | a | x |",
        "| Design | Name | Status |\n| --- | --- | --- |\n| D12 | a | THEIRS |\n| D14 | b | y |",
    )
    status, lines, _ = resolve_file(t)
    assert status == RESOLVED
    text = "\n".join(lines)
    assert "| Design | Name | Status |" in text        # header not dropped
    assert "| --- | --- | --- |" in text               # separator not dropped
    assert "D14" in text and "THEIRS" in text


def test_xref_anchor_to_a_renumbered_id_defers_and_other_anchors_are_untouched(ungated_renumber):
    # Regression (Feynman MAJOR #4): L<n> inside an anchor/link must NOT be rewritten. Round 17:
    # an anchor to an ID the resolver MOVES would then point at ours' entry, so that hunk defers;
    # an anchor to an ID that does not move is simply left as written.
    moved = _diff3_empty_base("### L4: ours", "### L4: theirs (anchor [L4](#L4-detail))")
    status, lines, results = resolve_file(moved)
    assert status == DEFER and "anchor/link/path" in results[0].reason, results[0].reason
    assert "\n".join(lines) == moved
    t = _diff3_empty_base(
        "### L4: ours",
        "### L4: theirs (prose ref see L5; anchor [L5](#L5-detail))\n### L5: detail body",
    )
    status, lines, _ = resolve_file(t)
    text = "\n".join(lines)
    assert status == RESOLVED
    assert "see L5" in text and "[L5](#L5-detail)" in text


def test_append_only_log_rule_unions_tails():
    # The append-only rule itself is correct (union of tails) — exercised directly.
    from classify import Hunk
    from resolve import resolve_append_log
    ours_tail, theirs_tail = "- **2026-07-04** — ours", "- **2026-07-05** — theirs"
    h = Hunk(ours=["x", "y", ours_tail], base=["x", "y"], theirs=["x", "y", theirs_tail],
             post_context="")                            # EOF after the region
    r = resolve_append_log(h)
    assert r.lines == ["x", "y", ours_tail, theirs_tail]


def test_append_only_log_now_resolves_ungated():
    # The ground-truth fixtures landed by basesync-prepend-log emptied GATED: a synthetic
    # in-hunk-base append now auto-resolves keep-both (was DEFER under the old GATED policy).
    base = "x\ny"
    t = _diff3("x\ny\n- **2026-07-04** — ours", base, "x\ny\n- **2026-07-05** — theirs")
    status, lines, results = resolve_file(t)
    assert status == RESOLVED
    assert results[0].status == RESOLVED
    text = "\n".join(lines)
    assert "— ours" in text and "— theirs" in text           # zero-drop keep-both
    assert "<<<<<<<" not in text                             # no human deferral marker


def _diff3_empty_base(ours, theirs, pre=""):
    # Real `git merge-file --diff3` minimizes a concurrent insertion to an EMPTY base (no line
    # between `||||||| base` and `=======`). _diff3(..., base="") would instead yield a single
    # blank base line, so a dedicated helper is needed to exercise the empty-base predicate.
    block = "<<<<<<< ours\n" + ours + "\n||||||| base\n=======\n" + theirs + "\n>>>>>>> theirs"
    return (pre + "\n" + block) if pre else block


def test_log_entry_insertion_keeps_both_verbatim_zero_drop():
    from classify import Hunk
    from resolve import resolve_log_entry_insertion
    h = Hunk(ours=["- **2026-07-04** — A", "", "  body a"], base=[],
             theirs=["- **2026-07-05** — B", "", "  body b"])
    r = resolve_log_entry_insertion(h)
    # ours block then theirs block, VERBATIM (no dedup, no reorder); every line survives.
    assert r.lines == ["- **2026-07-04** — A", "", "  body a", "- **2026-07-05** — B", "", "  body b"]


def test_log_entry_insertion_no_dedup_preserves_shared_body_line():
    # Two DISTINCT entries that share a body line must NOT lose it — append-style dedup would
    # corrupt an entry. Verbatim concatenation keeps both copies (fail-safe).
    from classify import Hunk
    from resolve import resolve_log_entry_insertion
    h = Hunk(ours=["- **2026-07-04** — A", "  shared body"], base=[],
             theirs=["- **2026-07-05** — B", "  shared body"])
    assert resolve_log_entry_insertion(h).lines.count("  shared body") == 2


def test_log_entry_insertion_resolves_end_to_end():
    t = _diff3_empty_base("- **2026-07-04** — ours\n\n  rat ours",
                          "- **2026-07-05** — theirs\n\n  rat theirs", pre="## History")
    status, lines, results = resolve_file(t)
    assert status == RESOLVED and results[0].label == "log-entry-insertion"
    text = "\n".join(lines)
    for needle in ["ours", "theirs", "## History"]:
        assert needle in text
    assert "<<<<<<<" not in text


def test_log_entry_insertion_defers_on_deletion_nonempty_base():
    # Non-empty base => a side modified/deleted a shared line => not a pure insertion => defer.
    from classify import Hunk, is_confident
    from resolve import resolve_hunk
    h = Hunk(ours=["- **2026-07-04** — A"], base=["- **2026-07-01** — old"],
             theirs=["- **2026-07-05** — B"])
    h.label = "log-entry-insertion"
    assert is_confident(h) is False           # predicate re-check fails (non-empty base)
    assert resolve_hunk(h).status == DEFER


def test_log_entry_insertion_defers_on_foreign_structure():
    # A foreign structural line (here an `### L9:` ID heading) inside the insertion disqualifies
    # the block => defer. Guards against a non-log structure being swept into a keep-both.
    t = _diff3_empty_base("- **2026-07-04** — ours\n### L9: sneaky id",
                          "- **2026-07-05** — theirs", pre="## History")
    status, _lines, results = resolve_file(t)
    assert status == DEFER                     # falls closed to a human


def test_low_confidence_mechanical_hunk_defers():
    # A hunk labelled mechanical but mixing in a foreign structure is not confident -> defer. To
    # test the confidence gate directly, force a log-entry-insertion label on a mixed hunk (round
    # 20: this used an id-renumber label, which the gate now defers before confidence is asked).
    from classify import Hunk, is_confident
    h2 = Hunk(ours=["- **2026-07-04** — ours", "| D9 | x | design | y |"], base=[],
              theirs=["- **2026-07-05** — theirs"], post_context="")
    h2.label = "log-entry-insertion"
    assert is_confident(h2) is False
    from resolve import resolve_hunk
    r = resolve_hunk(h2)
    assert r.status == DEFER and "not confident" in r.reason


def test_semantic_defers_by_default():
    t = _diff3("Some prose A", "base", "Some prose B")
    status, lines, results = resolve_file(t)
    assert status == DEFER
    assert results[0].status == DEFER
    assert "<<<<<<<" in "\n".join(lines)   # markers preserved for the human


def test_force_bypasses_deferral():
    t = _diff3("Some prose A", "base", "Some prose B")
    status, lines, results = resolve_file(t, force=True)
    assert status == RESOLVED
    assert "Some prose B" in "\n".join(lines)
    assert "<<<<<<<" not in "\n".join(lines)


def test_mixed_file_resolves_mechanical_keeps_semantic_markers():
    # ours' preamble side carries a second prose line: a date-only side is the mechanical
    # `last-updated-preamble` now, and this test needs a SEMANTIC region that keeps its markers
    t = _diff3("*Last updated: 2026-05-17*\nA second prose line.", "*Last updated: 2026-05-15*",
               "*Last updated: 2026-05-16*") + \
        "\nmid\n" + _diff3_empty_base("- **2026-05-17** — ours", "- **2026-05-16** — theirs")
    status, lines, results = resolve_file(t)
    text = "\n".join(lines)
    assert status == DEFER                      # preamble keeps it from full-resolve
    assert [r.status for r in results] == [DEFER, RESOLVED]      # mechanical hunk resolved
    assert "- **2026-05-17** — ours\n- **2026-05-16** — theirs" in text
    assert "Last updated" in text and "<<<<<<<" in text          # semantic hunk still marked
