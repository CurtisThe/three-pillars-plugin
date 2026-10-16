"""Task 3.1 — `last-updated-preamble` wired through classify, resolve, totality and the licence.

`keyed_classes` (Task 1.2) holds the predicate and the merge; this file pins the wiring around them,
end to end through `resolve.resolve_file` behind every backstop (confidence gate, `unplaceable`,
`overproduced`) and the oracle's independent reading of the same licence. A date-only or
summary-only `*Last updated:*` conflict resolves; a richer preamble region still defers.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from classify import AUTO_RESOLVE, GATED, MECHANICAL, Hunk, classify_file, is_confident  # noqa: E402
from conflict_fixtures import ALL_FIXTURES, diff3  # noqa: E402
from licence_oracle import lost_lines  # noqa: E402
from resolve import DEFER, MECH_RESOLVERS, RESOLVED, resolve_file  # noqa: E402
from resolve_totality import overproduced, unplaceable  # noqa: E402

LABEL = "last-updated-preamble"
BASE = "*Last updated: 2026-06-01*"
D02, D03 = "*Last updated: 2026-06-02*", "*Last updated: 2026-06-03*"


def region(ours, theirs, base=BASE):
    return "# Title\n" + diff3(ours, base, theirs) + "\n\n## Section\nbody\n"


def hunk_of(text):
    return next(s for s in classify_file(text).segments if isinstance(s, Hunk))


def test_the_class_is_mechanical_auto_resolve_and_has_a_resolver():
    assert LABEL in MECHANICAL and LABEL in AUTO_RESOLVE and LABEL not in GATED
    assert LABEL in MECH_RESOLVERS


@pytest.mark.parametrize("ours,theirs,expected", [
    (D02, D03, D03),                                          # (a) date-only: the later date
    (D03, D02, D03),
    ("*Last updated: 2026-06-03 — a: x*", "*Last updated: 2026-06-02 — b: y*",
     "*Last updated: 2026-06-03 — a: x; b: y*"),              # (b) the union line of Task 1.2
    ("*Last updated: 2026-06-02 — b: y*", "*Last updated: 2026-06-03 — a: x*",
     "*Last updated: 2026-06-03 — a: x; b: y*"),
])
def test_resolve_file_resolves_a_last_updated_conflict(ours, theirs, expected):
    text = region(ours, theirs)
    assert hunk_of(text).label == LABEL and is_confident(hunk_of(text))
    status, lines, results = resolve_file(text)
    assert status == RESOLVED, results
    assert [r.label for r in results] == [LABEL]
    assert results[0].status == RESOLVED and results[0].code == "" and results[0].renumbered == {}
    assert lines == ["# Title", expected, "", "## Section", "body", ""]


def test_a_preamble_region_with_an_extra_prose_line_still_defers_as_preamble():
    text = region(D03 + "\nA second prose line.", D02)
    assert hunk_of(text).label == "preamble"
    status, lines, results = resolve_file(text)
    assert status == DEFER and results[0].status == DEFER
    assert "<<<<<<<" in "\n".join(lines)


@pytest.mark.parametrize("ours,theirs", [
    (D03, D02), ("*Last updated: 2026-06-03 — a: x*", "*Last updated: 2026-06-02 — b: y*"),
    (D03, D03),
])
def test_the_result_passes_unplaceable_overproduced_and_the_oracle(ours, theirs):
    """(d) the licensed collapse of two one-line sides into one, by all three observers."""
    h = hunk_of(region(ours, theirs))
    r = MECH_RESOLVERS[LABEL](h)
    assert len(r.lines) == 1
    assert unplaceable(h, LABEL, r.lines) == []
    assert overproduced(h, LABEL, r.lines) == []
    assert lost_lines(h, r) == []


def test_the_licence_is_narrow():
    """Nothing but the one-line collapse: no output at all is a drop, a padded or invented line is
    overproduced, and a different label gets no exemption."""
    h = hunk_of(region("*Last updated: 2026-06-03 — a: x*", "*Last updated: 2026-06-02 — b: y*"))
    assert unplaceable(h, LABEL, []) == [h.ours[0]]       # one line owed, whichever side's
    assert len(lost_lines(h, type("R", (), {"label": LABEL, "renumbered": {}, "lines": []}))) == 1
    union = "*Last updated: 2026-06-03 — a: x; b: y*"
    assert overproduced(h, LABEL, [union]) == []                       # the one licensed line
    assert overproduced(h, LABEL, [union, union]) == [union, union]    # two lines: no exemption
    assert overproduced(h, LABEL, ["an invented line"]) == ["an invented line"]
    assert overproduced(h, LABEL, [union, "*Last updated: 2026-06-04*"]) != []
    assert overproduced(h, "log-entry-insertion", [union]) == [union]
    # an exact-multiplicity class still owes both lines
    assert len(unplaceable(h, "log-entry-insertion", [h.ours[0]])) == 1


def test_the_corpus_has_a_last_updated_fixture_the_class_labels():
    name, text = next((n, t) for n, t in ALL_FIXTURES if n == LABEL)
    assert hunk_of(text).label == LABEL
    status, _lines, results = resolve_file(text)
    assert status == RESOLVED and results[0].label == LABEL


def test_the_hunk_corpus_yields_one_fixed_last_updated_hunk_after_the_seeded_ones():
    from resolver_hunk_corpus import generated_hunks

    hunks = list(generated_hunks(5))
    assert [n for n, _t in hunks][-1] == "fixed:last-updated"
    assert [n for n, _t in hunks][:5] == [f"hunk:{k}" for k in range(5)]
    assert hunk_of(hunks[-1][1]).label == LABEL
    assert [t for n, t in generated_hunks(5) if n.startswith("hunk:")] == [t for _n, t in hunks[:5]]
