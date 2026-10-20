"""Task 2.3 — `low-count-line` wired through classify, resolve, totality, the oracle and the corpora.

`keyed_classes` (Task 1.2) holds the predicate and the merge; this file pins the wiring around them,
end to end through `resolve.resolve_file` behind every backstop (confidence gate, `unplaceable`,
`overproduced`, and the oracle's independent reading of the same licence). A count-line conflict —
the number edited on both sides of a base-sync, optionally with keyed entries inserted alongside —
resolves to ONE recomputed line; any other difference on the line still defers. The two shapes are
the 10-16 replays' `306` and `308a` `known_issues.md` hunks (`test_replay_history_syncs.py` `PAIRS`).
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from classify import AUTO_RESOLVE, GATED, MECHANICAL, Hunk, classify_file, is_confident  # noqa: E402
from conflict_fixtures import ALL_FIXTURES, LOW_COUNT_LINE, diff3  # noqa: E402
from keyed_classes import is_low_count_line, merge_low_count_lines  # noqa: E402
from licence_oracle import lost_lines  # noqa: E402
from resolve import DEFER, MECH_RESOLVERS, RESOLVED, resolve_file  # noqa: E402
from resolve_totality import overproduced, unplaceable  # noqa: E402

LABEL = "low-count-line"
# The text after the number, verbatim from `known_issues.md` (the plan's shared facts).
REST = ("Low issues → [known_issues_low.md](known_issues_low.md) (one line each; promote a Low "
        "to Medium by moving its entry back into this doc in the same commit).")


def C(n):
    return f"{n} {REST}"


def region(ours, theirs, base, pre="### M76: x\n- body\n"):
    """A real 3-way region under a keyed entry, with a blank run and `## History` below it."""
    return diff3(ours, base, theirs, pre=pre) + "\n\n## History\n"


def hunk_of(text):
    return next(s for s in classify_file(text).segments if isinstance(s, Hunk))


def count_lines(lines):
    return [ln for ln in lines if ln.endswith(REST) and ln.split(" ")[0].isdigit()]


def test_the_class_is_mechanical_auto_resolve_and_has_a_resolver():
    assert LABEL in MECHANICAL and LABEL in AUTO_RESOLVE and LABEL not in GATED
    assert LABEL in MECH_RESOLVERS


def test_resolve_file_resolves_the_306_fixture():
    """Theirs inserted `### M77:` and `### M78:` and edited the count line; ours edited only the
    count line. Both survive: theirs' entries verbatim, and exactly one recomputed line."""
    assert hunk_of(LOW_COUNT_LINE).label == LABEL and is_confident(hunk_of(LOW_COUNT_LINE))
    status, lines, results = resolve_file(LOW_COUNT_LINE)
    assert status == RESOLVED, results
    assert [r.label for r in results] == [LABEL]
    assert results[0].status == RESOLVED and results[0].code == "" and results[0].renumbered == {}
    for line in ("### M77: M77 title", "- M77 body", "### M78: M78 title", "- M78 body"):
        assert lines.count(line) == 1, line
    assert count_lines(lines) == [C(224)], count_lines(lines)


def test_the_308a_shape_resolves_to_the_recomputed_count_line():
    """223 + 224 - 219 = 228, the count the merged Low doc really holds (the plan's shared facts)."""
    text = region(C(223), C(224), C(219))
    assert hunk_of(text).label == LABEL
    status, lines, results = resolve_file(text)
    assert status == RESOLVED and results[0].label == LABEL, results
    assert count_lines(lines) == [C(228)], count_lines(lines)


def test_a_changed_link_text_on_the_line_defers_and_is_not_this_class():
    """The same text after the number on both sides is what makes ONE merged line decidable. Ours
    reworded the link, so which line survives is the human's call."""
    ours = C(223).replace("[known_issues_low.md]", "[the low doc]")
    text = region(ours, C(224), C(219))
    assert hunk_of(text).label != LABEL
    status, lines, results = resolve_file(text)
    assert status == DEFER and results[0].status == DEFER
    assert "<<<<<<<" in "\n".join(lines)


def test_entries_that_sort_into_a_block_with_no_trailing_blank_defer():
    """Phase-1 finding C2. `merge_keyed_heading_lines` sorts whole entries, and a side whose entries
    run out of order (`### M79:` above `### M78:`) leaves the SORTED block ending in the last
    entry's own body line. A recomputed count line glued there is that entry's list continuation,
    not a line of the document, so the class refuses the shape and the region defers with every
    line intact — the merge never invents the separating blank."""
    ours = "### M79: a\n- b\n### M78: c\n- d\n\n" + C(215)
    h = hunk_of(region(ours, C(222), C(213)))
    assert h.label != LABEL, h.label
    assert not is_low_count_line(h)
    assert merge_low_count_lines(h) == h.ours + h.theirs      # the total fallback, nothing invented
    status, lines, results = resolve_file(region(ours, C(222), C(213)))
    assert status == DEFER and results[0].status == DEFER
    assert "<<<<<<<" in "\n".join(lines)


@pytest.mark.parametrize("ours,theirs,base", [
    (C(223), C(224), C(219)),                                        # 308a
    ("### M80: e\n- f\n\n" + C(215), "### M77: a\n- b\n\n" + C(222), C(213)),  # both sides
])
def test_the_result_passes_unplaceable_overproduced_and_the_oracle(ours, theirs, base):
    """(d) the licensed collapse of two count lines into one recomputed one, by all three
    observers."""
    h = hunk_of(region(ours, theirs, base))
    assert h.label == LABEL
    r = MECH_RESOLVERS[LABEL](h)
    assert unplaceable(h, LABEL, r.lines) == []
    assert overproduced(h, LABEL, r.lines) == []
    assert lost_lines(h, r) == []


def test_the_licence_is_narrow():
    """Nothing but the one count-line collapse: an empty output owes ONE count line (the cross-side
    `max` of the two it was handed), two recomputed lines or an invented prose line is overproduced,
    and another label gets no exemption."""
    h = hunk_of(region(C(223), C(224), C(219)))
    assert unplaceable(h, LABEL, []) == [h.ours[0]]        # one line owed, whichever side's
    assert len(lost_lines(h, type("R", (), {"label": LABEL, "renumbered": {}, "lines": []}))) == 1
    assert overproduced(h, LABEL, [C(228)]) == []                    # the one licensed line
    assert overproduced(h, LABEL, [C(228), C(228)]) == [C(228), C(228)]   # two count lines
    assert overproduced(h, LABEL, [C(228), "an invented prose line"]) == ["an invented prose line"]
    assert overproduced(h, "log-entry-insertion", [C(228)]) == [C(228)]   # no exemption elsewhere


def test_the_licence_reaches_the_count_line_key_only():
    """S-K2's shape for this class: the entry lines around the count line are held to exact
    multiplicity, so a merge that drops one of theirs' entries is reported."""
    h = hunk_of(region("### M80: e\n- f\n\n" + C(215), "### M77: a\n- b\n\n" + C(222), C(213)))
    merged = merge_low_count_lines(h)
    assert unplaceable(h, LABEL, merged) == []
    assert lost_lines(h, type("R", (), {"label": LABEL, "renumbered": {}, "lines": merged})) == []
    assert unplaceable(h, LABEL, [ln for ln in merged if ln != "- b"]) == ["- b"]
    assert lost_lines(h, type("R", (), {
        "label": LABEL, "renumbered": {},
        "lines": [ln for ln in merged if ln != "- b"]})) == ["- b"]


def test_the_corpus_has_a_low_count_fixture_the_class_labels():
    name, text = next((n, t) for n, t in ALL_FIXTURES if n == LABEL)
    assert hunk_of(text).label == LABEL
    status, _lines, results = resolve_file(text)
    assert status == RESOLVED and results[0].label == LABEL


def test_the_hunk_corpus_yields_one_fixed_low_count_hunk_before_the_last_updated_one():
    from resolver_hunk_corpus import generated_hunks

    hunks = list(generated_hunks(5))
    names = [n for n, _t in hunks]
    assert names[-2:] == ["fixed:low-count-line", "fixed:last-updated"]
    assert names[:5] == [f"hunk:{k}" for k in range(5)]
    assert hunk_of(hunks[-2][1]).label == LABEL
    assert [t for n, t in generated_hunks(5) if n.startswith("hunk:")] == [t for _n, t in hunks[:5]]
