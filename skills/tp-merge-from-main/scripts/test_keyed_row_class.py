"""`keyed-row-insertion` (`keyed_rows`): its predicate, its merge, its wiring and its verifier atom.

Each case builds a real `Hunk` with `classify.parse_conflict` on a small diff3 text, so the fields the
predicate reads (`base`, `base_marker`, `line_after`, `context`) are the ones the parser fills in.
The class admits only an empty-base, 3-way region whose two sides are whole slug-keyed table rows
with distinct keys found nowhere else in the file, and keeps ours' rows then theirs' verbatim.
Test-fragility (`skills/_shared/test-fragility.md`): inputs are built here, never parsed from prose.
"""
import os
import sys
from collections import Counter

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import keyed_rows  # noqa: E402
import verify  # noqa: E402
from classify import Hunk, classify_file, is_confident, parse_conflict  # noqa: E402
from keyed_rows import is_keyed_row_insertion, merge_keyed_row_lines  # noqa: E402
from resolve import RESOLVED, resolve_file  # noqa: E402

HEAD = "| Design | What | Status |\n|---|---|---|\n| prior | A prior row. | Done |\n"
ROW_A = "| a-design | What for a. | Done (completion PR) |\n"
ROW_B = "| b-design | What for b. | Done — PR #7 |\n"


def conflict(ours, theirs, base="", head=HEAD, after="", three_way=True):
    """A diff3 text: `head`, one region (`ours` / `base` / `theirs` sections), then `after`."""
    parts = [head, "<<<<<<< ours\n", ours]
    if three_way:
        parts += ["||||||| base\n", base]
    parts += ["=======\n", theirs, ">>>>>>> theirs\n", after]
    return "".join(parts)


def first_hunk(text):
    hunks = [s for s in parse_conflict(text).segments if isinstance(s, Hunk)]
    assert hunks
    return hunks[0]


@pytest.mark.parametrize("ours,theirs,after", [
    (ROW_A, ROW_B, ""),                                              # the archive shape: EOF after
    (ROW_A, ROW_B, "\n## Roadmap History\n"),                         # a blank line ends the table
    (ROW_A, ROW_B, "| later | A later row. | Done |\n"),              # the table continues
    ("| **a-design** | x |\n", "| `b-design` | y |\n", ""),          # bold and backticked slugs
    (ROW_A + "| c-design | c |\n", ROW_B + "| d2 | d |\n", ""),       # several rows per side
    ("| a-design | x |\r\n", "| b-design | y |\r\n", ""),             # a CRLF file's final `\r`
])
def test_accepts_whole_slug_keyed_rows_with_distinct_keys(ours, theirs, after):
    h = first_hunk(conflict(ours, theirs, after=after))
    assert is_keyed_row_insertion(h)
    assert merge_keyed_row_lines(h) == h.ours + h.theirs


@pytest.mark.parametrize("ours,theirs,base,after,three_way", [
    (ROW_A, ROW_B, "| z-design | z |\n", "", True),                 # a side changed a base line
    (ROW_A, ROW_B, "", "", False),                                   # 2-way: base not recorded
    ("", ROW_B, "", "", True),                                       # one side adds nothing
    (ROW_A, ROW_A, "", "", True),                                    # one row moved on both sides
    (ROW_A, "| a-design | edited |\n", "", "", True),                # one key, two contents
    (ROW_A + "| a-design | again |\n", ROW_B, "", "", True),         # a key twice on one side
    ("| D12 | x | y |\n", ROW_B, "", "", True),                      # an ID row: inventory class
    ("| 3 | `a-design` | y |\n", ROW_B, "", "", True),              # a priority row
    ("| Design | What |\n", ROW_B, "", "", True),                    # a header row
    (ROW_A + "\n", ROW_B, "", "", True),                             # a blank line ends the table
    ("|---|---|\n" + ROW_A, ROW_B, "", "", True),                    # a frame inside a side
    ("| a-design | no closing pipe\n", ROW_B, "", "", True),         # not a whole row
    ("  | a-design | x |\n", ROW_B, "", "", True),                   # indented
    ("prose about a-design\n", ROW_B, "", "", True),                 # not a row at all
    ("| a-design | x\r|\n", ROW_B, "", "", True),                    # a carriage return inside
    (ROW_A, ROW_B, "", "|---|---|---|\n", True),                     # a delimiter row follows
    (ROW_A, ROW_B, "", "<<<<<<< ours\nx\n||||||| base\n=======\ny\n>>>>>>> theirs\n", True),
])
def test_refuses_every_other_shape(ours, theirs, base, after, three_way):
    text = conflict(ours, theirs, base=base, after=after, three_way=three_way)
    assert not is_keyed_row_insertion(first_hunk(text))


@pytest.mark.parametrize("elsewhere", [
    "| a-design | An older row. | Done — PR #3 |\n",                  # same key, other content
    ROW_A,                                                           # same key, same bytes
    "| `a-design` | marked up |\n",                                  # same slug under markup
])
def test_refuses_a_key_already_present_elsewhere_in_the_file(elsewhere):
    for head, after in ((HEAD + elsewhere, ""), (HEAD, "\n### Seeds\n\n| x | y |\n|---|---|\n" + elsewhere)):
        h = first_hunk(conflict(ROW_A, ROW_B, head=head, after=after))
        assert not is_keyed_row_insertion(h), (head, after)


def test_a_key_in_another_region_of_the_file_refuses_both_regions():
    """The same slug moved by the two sides to two different places: each region sees the other's."""
    text = conflict(ROW_A, ROW_B, after="| mid | m |\n" + conflict(
        "| c-design | c |\n", ROW_A.replace("Done (completion PR)", "Done — PR #9"), head=""))
    hunks = [s for s in parse_conflict(text).segments if isinstance(s, Hunk)]
    assert len(hunks) == 2
    assert not any(is_keyed_row_insertion(h) for h in hunks)


def test_hand_built_hunks_count_their_own_context_list():
    base_kwargs = dict(base=[], line_after="")
    clean = Hunk(ours=[ROW_A.rstrip("\n")], theirs=[ROW_B.rstrip("\n")], **base_kwargs)
    assert is_keyed_row_insertion(clean)
    clash = Hunk(ours=[ROW_A.rstrip("\n")], theirs=[ROW_B.rstrip("\n")], **base_kwargs)
    clash.context = ["| a-design | elsewhere |"]
    assert not is_keyed_row_insertion(clash)


def test_classify_labels_it_and_resolve_keeps_every_line_once():
    text = conflict(ROW_A, ROW_B)
    hunk = next(s for s in classify_file(text).segments if isinstance(s, Hunk))
    assert hunk.label == keyed_rows.LABEL and is_confident(hunk)
    status, lines, results = resolve_file(text)
    assert status == RESOLVED and [r.label for r in results] == [keyed_rows.LABEL]
    assert lines == [*HEAD.splitlines(), ROW_A.rstrip("\n"), ROW_B.rstrip("\n"), ""]
    assert Counter(lines) - Counter([*HEAD.splitlines(), *hunk.ours, *hunk.theirs, ""]) == Counter()


def test_a_hunk_mislabelled_keyed_row_insertion_is_not_confident():
    """`is_confident` re-verifies the predicate: the label alone never admits a hunk."""
    hunk = first_hunk(conflict(ROW_A, ROW_A))
    hunk.label = keyed_rows.LABEL
    assert not is_confident(hunk)


def test_the_id_row_shape_still_goes_to_the_inventory_class():
    text = conflict("| D12 | twelve | x |\n", "| D13 | thirteen | y |\n")
    hunk = next(s for s in classify_file(text).segments if isinstance(s, Hunk))
    assert hunk.label == "design-inventory-row-merge"


def test_labelling_a_file_of_many_regions_counts_its_rows_once():
    """`_file_keys` counts the file's rows once per file, not once per region (round 25)."""
    regions = 60
    text = "".join(conflict(f"| o{i} | x |\n", f"| t{i} | y |\n", head=f"| s{i} | z |\n")
                   for i in range(regions))
    calls = Counter()
    real = keyed_rows.row_key

    def counting(line):
        calls[line] += 1
        return real(line)

    keyed_rows.row_key = counting
    try:
        pf = classify_file(text)
    finally:
        keyed_rows.row_key = real
    labels = [s.label for s in pf.segments if isinstance(s, Hunk)]
    assert labels == [keyed_rows.LABEL] * regions
    # each separator row is read once by the file count; each region row once more by its side
    assert calls["| s0 | z |"] == 1 and max(calls.values()) <= 2, calls.most_common(3)


@pytest.mark.parametrize("line,key", [
    ("| a-design | x |", "a-design"),
    ("| **a-design** | x |", "a-design"),
    ("|a-design|x|", "a-design"),
])
def test_the_verifier_reads_a_slug_row_as_one_atom_keyed_by_the_slug(line, key):
    assert verify.atoms(line) == {("slug-row", key): "slug-row"}


def test_a_backticked_slug_row_is_the_row_atom_keyed_by_its_raw_slug_not_a_slug_row():
    """`basesync-three-way-verifier` landed the backticked form as a `row` atom with the backticks
    kept (`test_slug_rows.py`); this class's `slug-row` atom covers the plain and bold forms only, so
    the two kinds never count one line twice and a drop of either form is still seen."""
    assert verify.atoms("| `a-design` | x |") == {("row", "`a-design`"): "row"}


@pytest.mark.parametrize("line", ["| 3 | a-design |", "| D12 | x |", "| --- | --- |", "| - | x |"])
def test_the_verifier_reads_no_slug_row_from_other_rows(line):
    assert ("slug-row" not in {kind for kind, _ in verify.atoms(line)})


def test_the_verifier_reports_a_dropped_row_and_ignores_a_status_flip():
    """`HEAD` is the merge base of this shape (the table before either side appended), so this is
    the three-way verdict (`verify(base=)`, keyword-only since `basesync-three-way-verifier`)."""
    ours, theirs = HEAD + ROW_A, HEAD + ROW_B
    merged = HEAD + ROW_A + ROW_B
    three_way = lambda resolved: verify.verify(ours, theirs, resolved, base=HEAD, mechanical_applied=True)  # noqa: E731
    assert three_way(merged).verdict == verify.VERIFIED
    flipped = merged.replace("Done (completion PR)", "Done — PR #12")
    assert three_way(flipped).verdict == verify.VERIFIED
    dropped = three_way(HEAD + ROW_A)
    assert dropped.verdict == verify.DROPS_DETECTED
    assert dropped.dropped == [("slug-row", "b-design")]
