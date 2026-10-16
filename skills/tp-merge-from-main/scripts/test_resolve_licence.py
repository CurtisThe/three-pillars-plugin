"""THE PER-CLASS LICENCE, and the three ways a drop hid inside it (S-J2, S-J3, S-J4).

`test_resolve_totality.py` pins the RULE over the corpus. This module pins the LICENCE the rule is
evaluated against — what each class may legitimately change about the lines it was handed — because
all three defects here were the licence being stated too loosely rather than the rule being wrong
(the two resolver-level renumber cases run the class GATED since round 20 with the gate lifted for
that test, `ungated_renumber`; they pin the dormant resolver, not a production merge):

  S-J2  the id-renumber key masks every ID it renumbered, so two entries differing ONLY in their ID
        share a key; under SET containment one survivor accounted for both.
  S-J3  set containment is multiplicity-blind, so a silently deduped duplicate was undetectable for
        the two classes whose licence is *nothing — verbatim concatenation*.
  S-J4  `resolve_append_log` ran BOTH tails through one `seen` set, collapsing two entries appended
        to the SAME side — which the re-run licence never covered.

One change answers all three: MULTISET containment, with the collapsing licence named explicitly as
`max(ours, theirs)` — a duplicate may collapse across the two sides, never within one.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from classify import Hunk, classify_file  # noqa: E402
from licence_oracle import lost_lines  # noqa: E402
from resolve import (  # noqa: E402
    DEFER, RESOLVED, resolve_append_log, resolve_file, resolve_hunk, resolve_inventory,
)
from resolve_totality import (  # noqa: E402
    CROSS_SIDE_DEDUPE, CannotPlace, embedded_marker, key_for, licensed_keys, table_frame_lines,
    unplaceable,
)
from test_resolve_three_way import ungated_renumber  # noqa: E402,F401 — a pytest fixture


# ---- S-J2: two entries that differ ONLY in a renumbered ID -------------------------------------

REMAP = {"L4": "L5", "L7": "L8"}
TWO_ENTRIES = ["### L4: Bar body", "### L7: Bar body"]


def test_s_j2_the_key_is_not_injective_and_that_is_why_the_count_is_load_bearing():
    """The premise, asserted rather than assumed: the two lines DO share a key. Anything that made
    them distinguishable by key alone would make the multiset check redundant here — this test
    fails loudly in that happy case rather than leaving a dead assertion behind."""
    key = key_for("id-renumber-collision", REMAP)
    assert key(TWO_ENTRIES[0]) == key(TWO_ENTRIES[1])


def test_s_j2_dropping_one_of_two_id_only_siblings_is_reported():
    """THE S-J2 regression. Input carries both entries; the output carries one. Pre-fix
    `unplaceable` returned `[]` — the set already contained the shared key — and the entry was gone
    under a RESOLVED verdict."""
    h = Hunk(ours=["### L1: ours"], base=[], theirs=list(TWO_ENTRIES))
    out = ["### L1: ours", "### L5: Bar body"]          # L7's entry never made it out
    assert unplaceable(h, "id-renumber-collision", out, REMAP) == ["### L4: Bar body"]
    assert lost_lines(h, _Result("id-renumber-collision", out, REMAP)), "the oracle agrees"


def test_s_j2_both_siblings_surviving_is_not_reported():
    """Injectivity is about the COUNT, so the count has to be right in both directions: two
    entries in, two out — renumbered, as the licence allows — is not a drop."""
    h = Hunk(ours=["### L1: ours"], base=[], theirs=list(TWO_ENTRIES))
    out = ["### L1: ours", "### L5: Bar body", "### L8: Bar body"]
    assert unplaceable(h, "id-renumber-collision", out, REMAP) == []
    assert lost_lines(h, _Result("id-renumber-collision", out, REMAP)) == []


def test_a_repeated_id_on_theirs_refuses_instead_of_renumbering_it_twice(ungated_renumber):
    """The shape S-J2's example comes from, at the resolver. `remap` is keyed by the OLD ID, so
    theirs carrying `### L5:` twice cannot be represented in it: the second mapping overwrites the
    first, `_apply_xref` then points BOTH entries' cross-references at the second entry's new
    number, and the audit dict names one of the two moves. The class's licence presupposes a
    renumber map that is a function, so the resolver refuses."""
    # Round 17: theirs' repeated ID must also COLLIDE with ours', or the hunk is not an ID
    # collision at all and never reaches the resolver (it defers as `semantic` instead).
    text = ("<<<<<<< ours\n### L4: ours entry\n||||||| base\n=======\n"
            "### L4: theirs one\nbody\n### L4: theirs two\nbody two\n>>>>>>> theirs")
    status, lines, results = resolve_file(text)
    assert status == DEFER and "not a function" in results[0].reason, results[0].reason
    assert "\n".join(lines) == text, "a deferral must round-trip byte-for-byte"


def test_the_ordinary_renumber_moves_only_the_colliding_id(ungated_renumber):
    """The floor for S-J2's fix, restated for round 17 (F4). The old resolver renumbered theirs'
    whole block contiguously (`L4->L5` alongside `L5->L6` — a CHAIN, the case an inverse-remap key
    would have reported as a drop). It now moves only the ID that collides, to a number above every
    ID the file uses, so a chain cannot form; every entry still survives."""
    text = ("<<<<<<< ours\n### L4: ours entry\n||||||| base\n=======\n"
            "### L4: theirs one\nsee L5 for detail\n### L5: theirs two\n>>>>>>> theirs")
    status, lines, results = resolve_file(text)
    merged = "\n".join(lines)
    assert status == RESOLVED and results[0].renumbered == {"L4": "L6"}
    assert "### L4: ours entry" in merged                      # ours untouched
    assert "### L6: theirs one" in merged and "### L5: theirs two" in merged
    assert "see L5 for detail" in merged                       # theirs' L5 did not move


# ---- S-J3: multiplicity, for the classes whose licence is "nothing" ----------------------------

@pytest.mark.parametrize("label", ["log-entry-insertion", "decision-entry-insertion"])
def test_s_j3_a_deduped_duplicate_is_a_drop_for_the_verbatim_classes(label):
    """Their licence is verbatim concatenation, so a second copy of a line is a second LINE. A
    counterfactual resolver that dedups is reported — under set containment it could not be."""
    h = Hunk(ours=["- **2026-07-04** — entry", "- **2026-07-04** — entry"], base=[],
             theirs=["- **2026-07-05** — theirs"])
    deduped = ["- **2026-07-04** — entry", "- **2026-07-05** — theirs"]
    assert unplaceable(h, label, deduped) == ["- **2026-07-04** — entry"]
    assert lost_lines(h, _Result(label, deduped)), "the oracle agrees"
    assert unplaceable(h, label, list(h.ours) + list(h.theirs)) == []   # the real resolver


def test_s_j3_the_dedupe_licence_is_named_not_implied():
    """The licence lives in a named constant, not in the choice of `set` over `Counter`. That
    implicitness is what hid S-J3 and S-J4 — this asserts the three classes that hold it and, by
    equality rather than membership, that no class quietly joins them. `last-updated-preamble`
    joined deliberately: its licence is narrowed to the one `*Last updated:` key.
    `log-entry-insertion` joined deliberately too (PR #206): its licence is narrowed to the whole
    log entries both blocks open or close with (`resolve_totality.shared_entry_affix`)."""
    assert CROSS_SIDE_DEDUPE == frozenset(
        {"append-only-log", "design-inventory-row-merge", "last-updated-preamble",
         "log-entry-insertion"})


# ---- S-K1 / S-K2: WHERE the licence applies, not only what it says -----------------------------

S_K1 = ("<<<<<<< ours\n| D3 | Widget A | active |\n| D3 | Widget A | legacy |\n"
        "||||||| base\n| D3 | Widget A | active |\n=======\n"
        "| D3 | Widget A | archived |\n>>>>>>> theirs")

S_K2 = ("<<<<<<< ours\n| Design | Name | Status |\n| --- | --- | --- |\n| D12 | a | BASE |\n"
        "| TBD | | | placeholder |\n||||||| base\n| D12 | a | BASE |\n=======\n"
        "| Design | Name | Status |\n"
        "| --- | --- | --- |\n| D12 | a | THEIRS |\n| TBD | | | placeholder |\n>>>>>>> theirs")


def test_s_k1_two_rows_of_one_design_id_on_a_side_refuse_instead_of_guessing():
    """THE S-K1 regression. Ours carries `| D3 |` on two DIFFERENT rows, so "theirs' row replaces
    ours' row of the same id" names no unique row. Pre-fix: RESOLVED, `legacy` gone, theirs' row
    emitted TWICE to fill the count `_row_key` licensed — a drop and an invention in one output,
    and `unplaceable()` reported neither because both rows key to `<row D3>`."""
    status, lines, results = resolve_file(S_K1)
    assert status == DEFER, lines
    assert "D3 on more than one row" in results[0].reason, results[0].reason
    assert "| D3 | Widget A | legacy |" in lines, "the row it could not choose must survive"
    assert lines.count("| D3 | Widget A | archived |") == 1, "and theirs' row is not duplicated"
    assert "\n".join(lines) == S_K1, "a deferral must round-trip byte-for-byte"


def test_s_k1_a_repeated_id_on_theirs_refuses_too():
    """Both sides, not just ours: theirs carrying an id twice makes `theirs_rows[k]` a
    last-one-wins overwrite, which silently discards the row it overwrote."""
    h = Hunk(ours=["| D3 | a | ours |"], base=[],
             theirs=["| D3 | a | x |", "| D3 | a | y |"], label="design-inventory-row-merge")
    with pytest.raises(CannotPlace, match="theirs carries the design ID D3"):
        resolve_inventory(h)
    assert resolve_hunk(h).status == DEFER


def test_s_k1_refuses_even_when_the_two_rows_are_byte_identical():
    """m-L3. S-K1's refusal was widened from "two rows differing in content" to ANY repeated design
    id on a side — and every test used differing content (`active`/`legacy`, `x`/`y`), so the widest
    and least intuitive case was unasserted. Two BYTE-IDENTICAL rows are still two rows: the licence
    is "theirs' row replaces OURS' row of the same id", which names no unique row here either, and
    the old code emitted theirs' row twice while `_row_key` licensed the count. The verdict is not
    'it does not matter because the rows are the same' — the OUTPUT would carry two copies of a row
    the input never had twice, which is R3's invention, so the refusal is the correct answer.
    """
    same = "| D3 | Widget A | active |"
    h = Hunk(ours=[same, same], base=[], theirs=["| D3 | Widget A | archived |"],
             label="design-inventory-row-merge")
    with pytest.raises(CannotPlace, match="ours carries the design ID D3"):
        resolve_inventory(h)
    r = resolve_hunk(h)
    assert r.status == DEFER and r.code == "cannot-place", (r.code, r.reason)
    assert r.lines.count(same) == 2, "both copies survive the deferral"

    theirs_twice = Hunk(ours=["| D3 | a | ours |"], base=[], theirs=[same, same],
                        label="design-inventory-row-merge")
    with pytest.raises(CannotPlace, match="theirs carries the design ID D3"):
        resolve_inventory(theirs_twice)


def test_a_blank_line_on_theirs_defers_the_inventory_merge():
    """m-L5. The narrowed placement rule says a theirs line is placeable only if it is a design-ID
    row or the table frame, and named "blank separators" as something that used to be placed by
    coincidence and now defers. That claim had ZERO corpus instances and no assertion — it existed
    only in prose, which on this branch has repeatedly meant it existed only in prose.

    Round 21 (S1) moved the refusal earlier and made it symmetric: a blank line on EITHER side ends
    the table, so a row the merge places after it is no longer in the table it was written in. The
    class predicate refuses it (`table_run.table_run_refusal`), and the resolver checks the same
    predicate before placing anything. Until round 21 a blank on OURS resolved, and that is what
    let theirs' appended row land after it.
    """
    # Round 17: `D12` is decidable against base (only theirs changed it), so no row decision refuses
    # first — the blank is the only thing wrong with either hunk.
    h = Hunk(ours=["| Design | Name |", "| --- | --- |", "| D12 | a | x |"], base=["| D12 | a | x |"],
             theirs=["| Design | Name |", "| --- | --- |", "", "| D12 | a | THEIRS |"],
             label="design-inventory-row-merge")
    with pytest.raises(CannotPlace, match="theirs carries a blank line"):
        resolve_inventory(h)
    r = resolve_hunk(h)
    assert r.status == DEFER and r.code == "not-confident", (r.code, r.reason)

    ours_blank = Hunk(ours=["| Design | Name |", "| --- | --- |", "", "| D12 | a | x |"],
                      base=["| D12 | a | x |"],
                      theirs=["| Design | Name |", "| --- | --- |", "| D12 | a | THEIRS |"],
                      label="design-inventory-row-merge")
    with pytest.raises(CannotPlace, match="ours carries a blank line"):
        resolve_inventory(ours_blank)
    assert resolve_hunk(ours_blank).code == "not-confident"


def test_the_blank_on_theirs_is_reached_through_the_classifier_not_just_the_resolver():
    """m-L5's reachability claim, asserted where it is actually decidable. Until round 21 the
    CLASSIFIER labelled a hunk carrying a blank on theirs `design-inventory-row-merge` (the purity
    gate constrained non-blank lines only) and the resolver refused the blank. Since round 21 the
    class predicate refuses it, so the hunk is `generic-prose` and defers as semantic. The deferral
    round-trips byte for byte, as every deferral must."""
    text = ("<<<<<<< ours\n| Design | Name |\n| --- | --- |\n| D12 | a | x |\n"
            "||||||| base\n| Design | Name |\n| --- | --- |\n| D12 | a | x |\n=======\n"
            "| Design | Name |\n| --- | --- |\n\n| D12 | a | THEIRS |\n>>>>>>> theirs")
    hunk = next(s for s in classify_file(text).segments if isinstance(s, Hunk))
    assert hunk.label == "generic-prose", hunk.label
    assert classify_file(text.replace("| --- |\n\n|", "| --- |\n|")).segments[0].label == (
        "design-inventory-row-merge"), "control: without the blank it is the inventory class"
    status, lines, results = resolve_file(text)
    assert status == DEFER and results[0].code == "semantic", results[0].reason
    assert "\n".join(lines) == text


def test_s_k2_a_table_shaped_line_both_sides_share_is_not_the_frame():
    """THE S-K2 regression. `| TBD | | | placeholder |` is a data row with no design id, duplicated
    verbatim on both sides. Pre-fix the hunk-wide `max()` licensed one copy out for two in, the
    resolver placed theirs' copy by coincidence (it was already in the output), and the hunk
    returned RESOLVED with nothing to report."""
    status, lines, results = resolve_file(S_K2)
    assert status == DEFER, lines
    assert "is neither" in results[0].reason, results[0].reason
    assert "\n".join(lines) == S_K2


def test_s_k2_the_licence_scope_names_the_row_and_frame_keys_and_nothing_else():
    """The scope itself, asserted rather than inferred from a verdict: the row keys and the table
    frame are licensed to collapse across sides; a table-shaped content line is not."""
    h = Hunk(ours=["| Design | Name |", "| --- | --- |", "| D12 | a |", "| TBD | placeholder |"],
             base=[], theirs=list())
    key = key_for("design-inventory-row-merge")
    covered = licensed_keys(h, key, "design-inventory-row-merge")
    assert covered == frozenset({"<row D12>", "| Design | Name |", "| --- | --- |"}), covered
    assert table_frame_lines(h.ours) == {"| Design | Name |", "| --- | --- |"}


def test_s_k2_the_collapse_is_reported_as_a_drop_by_both_readings():
    """And the post-condition backstop, for a resolver that places such a line anyway: with the
    licence scoped, one copy out for two in is short by one — and the oracle, reading the same
    scope by its own mechanism, says so too."""
    h = Hunk(ours=["| D12 | a | OURS |", "| TBD | placeholder |"], base=[],
             theirs=["| D12 | a | THEIRS |", "| TBD | placeholder |"])
    collapsed = ["| D12 | a | THEIRS |", "| TBD | placeholder |"]
    assert unplaceable(h, "design-inventory-row-merge", collapsed) == ["| TBD | placeholder |"]
    assert lost_lines(h, _Result("design-inventory-row-merge", collapsed))


def test_the_frame_licence_still_holds_for_a_real_table_slice():
    """The floor, and the reason the scope is positional rather than "any pipe line": a genuine
    inventory merge whose sides repeat the header and delimiter still resolves, with one copy of
    each in the output."""
    text = ("<<<<<<< ours\n| Design | Name | Status |\n| --- | --- | --- |\n| D12 | a | BASE |\n"
            "||||||| base\n| D12 | a | BASE |\n=======\n| Design | Name | Status |\n"
            "| --- | --- | --- |\n| D12 | a | THEIRS |\n| D14 | b | y |\n>>>>>>> theirs")
    status, lines, results = resolve_file(text)
    assert status == RESOLVED and results[0].label == "design-inventory-row-merge"
    assert lines.count("| --- | --- | --- |") == 1 and lines.count("| Design | Name | Status |") == 1
    assert "| D14 | b | y |" in lines and "| D12 | a | THEIRS |" in lines


# ---- S-J4: same-side vs cross-side duplicates in the append log --------------------------------

# The shape it takes end to end — a NON-EMPTY base that is a common prefix of both sides. With an
# EMPTY base the hunk classifies `log-entry-insertion` (verbatim concatenation, no dedupe at all),
# which is why the two-identical-ours-lines repro did not reproduce.
S_J4 = ("## History\n<<<<<<< ours\n- **2026-07-01** — shared\n- **2026-07-04** — dup\n"
        "- **2026-07-04** — dup\n||||||| base\n- **2026-07-01** — shared\n=======\n"
        "- **2026-07-01** — shared\n- **2026-07-05** — theirs entry\n>>>>>>> theirs")


def test_s_j4_two_identical_entries_on_one_side_both_survive():
    """THE S-J4 regression. Both copies are ours', so neither is the cross-side duplicate the
    licence is about; the pre-fix single `seen` set collapsed them and returned RESOLVED."""
    status, lines, results = resolve_file(S_J4)
    assert results[0].label == "append-only-log", results[0]
    assert lines.count("- **2026-07-04** — dup") == 2, lines
    assert status == RESOLVED, "and it must still resolve — the fix is not 'defer more'"
    assert "- **2026-07-05** — theirs entry" in lines


def test_s_j4_the_cross_side_duplicate_still_collapses():
    """The licence itself, unchanged: a re-run that appended the SAME entry on both sides folds to
    one. Losing this would make every re-run a hand-resolve."""
    h = Hunk(ours=["- shared", "- both added this"], base=["- shared"],
             theirs=["- shared", "- both added this"])
    assert resolve_append_log(h).lines == ["- shared", "- both added this"]


def test_s_j4_a_partial_cross_side_overlap_now_refuses():
    """Round 17 (F5) replaced this test's old assertion — that two copies on one side and one on
    the other resolve to `max` = two. A line both TAILS carry may be one entry both sides appended
    or two distinct entries' lines, and a per-line collapse cannot tell which, so any shared
    non-blank tail line that is not part of a byte-identical whole tail now refuses. (Round 19: the
    class also needs a non-empty base and whole log-entry tails, so the lines are real entries.)"""
    x, base = "- **2026-07-04** — x", ["- **2026-07-01** — seed"]
    for ours, theirs in (([x, x], [x]), ([x], [x, x])):
        h = Hunk(ours=base + ours, base=base, theirs=base + theirs, label="append-only-log",
                 post_context="")
        with pytest.raises(CannotPlace, match="both tails carry this line"):
            resolve_append_log(h)
        assert resolve_hunk(h).code == "cannot-place"


def test_the_post_condition_would_catch_the_pre_fix_append_log():
    """Belt and braces: even if the resolver regressed, the post-condition now reports it — the
    backstop that makes the rule structural rather than a patch on one function."""
    h = Hunk(ours=["- x", "- x"], base=[], theirs=["- y"], label="append-only-log")
    assert unplaceable(h, "append-only-log", ["- x", "- y"]) == ["- x"]


# ---- the marker FIELDS, not just the side lists -------------------------------------------------

def test_a_labelled_separator_is_content_not_a_separator():
    """`embedded_marker` now inspects the four marker FIELDS. git labels three of them and never
    the separator, so a `sep_marker` carrying a label is a line of content the scan cut at.

    `resolve_hunk` asks the class re-check (`is_confident`) BEFORE the marker check, so the hunk it
    is given is a real `append-only-log` one: the deferral it returns is the marker check's."""
    h = Hunk(ours=["a"], base=[], theirs=["b"], sep_marker="======= see example above")
    assert embedded_marker(h) == "======= see example above"
    seed, o, t = "- **2026-07-01** — seed", "- **2026-07-03** — o", "- **2026-07-02** — t"
    log = Hunk(ours=[seed, o], base=[seed], theirs=[seed, t], post_context="",
               label="append-only-log", sep_marker="======= see example above")
    r = resolve_hunk(log)
    assert r.status == DEFER and r.code == "malformed-hunk", r.reason
    log.sep_marker = "======="
    assert resolve_hunk(log).status == RESOLVED


def test_a_field_holding_the_wrong_marker_is_refused():
    h = Hunk(ours=["a"], base=[], theirs=["b"], base_marker="======= not a base marker")
    assert embedded_marker(h) == "======= not a base marker"


@pytest.mark.parametrize("sep", ["=======", "=========", "=======\r"])
def test_a_bare_separator_of_any_marker_size_is_accepted(sep):
    """The fall-closed direction, bounded: `conflict-marker-size` is configurable and a CRLF file
    carries a trailing `\\r`, so bareness is 'nothing but `=`', not 'exactly seven'."""
    assert embedded_marker(Hunk(ours=["a"], base=[], theirs=["b"], sep_marker=sep)) is None


class _Result:
    """The three attributes `licence_oracle.lost_lines` reads, standing in for a `HunkResult`."""

    def __init__(self, label, lines, renumbered=None):
        self.label, self.lines, self.renumbered = label, lines, renumbered or {}


if __name__ == "__main__":
    sys.exit(pytest.main([__file__]))
