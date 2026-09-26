"""Rounds 25-26 — the parse and the labelling of a file of many conflict regions are linear.

M1  `_fill_context` gave every region a copy of every content line outside it (`Hunk.context`),
    R x L references for R regions and L lines: a 300 KB file of 12,500 regions peaked at about
    4.9 GB, an out-of-memory kill `merge_back`'s `except Exception` cannot catch. The regions of a
    file now share one tuple (`conflict_parse._Outside`).
M2  `parse_conflict` called `_pre_context` for each region, and on a file whose regions are
    separated by blank lines only each call walked back over every earlier region. The value is
    now kept as the scan goes.
R26 `classify_hunk` searched each region's `pre_context` for the focus words, and the regions
    separated by blank lines only share one context line: regions x its length. `classify_file`
    now searches each distinct context line object once.

No test reads a clock: memory is bounded with `tracemalloc`, and work is the number of lines the
parser's own code executes (`sys.settrace`), which is exact for a given input. That count sees
Python lines only. Work done inside ONE C operation is invisible to it: `lines = lines + part` in
place of `lines += part` would copy every earlier line at each segment, quadratic, in the same
number of line events, and neither test here catches that (its memory peak stays about twice the
list). The focus search is C work too (`str.__contains__`), so R26 counts it with a `str`
subclass that records the length of every string it searches.
"""
import os
import sys
import tracemalloc

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import classify  # noqa: E402
import conflict_parse  # noqa: E402
from conflict_parse import Hunk, parse_conflict  # noqa: E402

LABELS = ("ours-r25", "base-r25", "theirs-r25")


def _doc(regions: int, separator) -> str:
    """`regions` labelled diff3 regions, each after a clean `separator(i)` line."""
    return "".join(f"{separator(i)}\n<<<<<<< {LABELS[0]}\nours {i}\n||||||| {LABELS[1]}\nbase {i}\n"
                   f"=======\ntheirs {i}\n>>>>>>> {LABELS[2]}\n" for i in range(regions)) + "tail"


def test_m1_many_regions_parse_in_memory_linear_in_the_file():
    """3,000 regions and 12,001 content lines: the per-region copies held 35,994,000 references (a
    312 MB traced peak); the regions now share one tuple of 12,001 and the parse peaks under 4 MB.
    What a region's context reads is unchanged: all content lines but its own three, in order."""
    text = _doc(3000, lambda i: f"line {i}")
    tracemalloc.start()
    try:
        pf = parse_conflict(text, labels=LABELS)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 16 * 2**20, peak
    hunks = [s for s in pf.segments if isinstance(s, Hunk)]
    assert len(hunks) == 3000
    lines = text.split("\n")
    content = [ln for ln in lines if not ln.startswith(("<<<<<<< ", "||||||| ", "=======",
                                                        ">>>>>>> "))]
    h = hunks[1500]
    own = content.index("ours 1500")
    expected = content[:own] + content[own + 3:]
    assert list(h.context) == expected and len(h.context) == len(expected)
    assert [h.context[k] for k in (0, own - 1, own, -1)] == [expected[k] for k in (0, own - 1, own,
                                                                                    -1)]
    assert h.context[own:own + 2] == expected[own:own + 2]
    assert (h.pre_context, h.post_context, h.line_after) == ("line 1500", "line 1501", "line 1501")


def _lines_executed(text: str) -> int:
    """How many lines of `conflict_parse`'s own code run while parsing `text`."""
    count = 0
    source = conflict_parse.__file__

    def local(frame, event, arg):
        nonlocal count
        count += event == "line"
        return local

    def call(frame, event, arg):
        return local if frame.f_code.co_filename == source else None

    sys.settrace(call)
    try:
        parse_conflict(text, labels=LABELS)
    finally:
        sys.settrace(None)
    return count


def test_m2_doubling_the_regions_at_most_doubles_the_parse_work():
    """Regions separated by blank lines only: git keeps them apart, and every region's
    `pre_context` is the heading above the first. Walking back per region made the work grow as
    the square of the region count (x3.9 from 300 regions to 600); a linear parse grows x2."""
    blank = lambda i: ""                                                   # noqa: E731
    small, large = (_lines_executed("## Head\n" + _doc(n, blank)) for n in (300, 600))
    assert large < 2.2 * small, (small, large)
    pf = parse_conflict("## Head\n" + _doc(600, blank), labels=LABELS)
    hunks = [s for s in pf.segments if isinstance(s, Hunk)]
    assert {h.pre_context for h in hunks} == {"## Head"}
    assert [h.post_context for h in hunks[-2:]] == [None, "tail"]
    last = [s for s in parse_conflict(_doc(2, blank)[:-len("tail")], labels=LABELS).segments
            if isinstance(s, Hunk)][-1]
    assert (last.post_context, last.line_after) == ("", "")                # only EOF follows


def _labels_and_chars_searched(monkeypatch, text):
    """`classify_file(text)`'s labels, and how many characters the focus search read: every hunk's
    `pre_context` is swapped for a `str` subclass that adds its length at each `in` test. Hunks
    that shared one context line object share one spy."""
    searched = []

    class Spy(str):
        def __contains__(self, key):
            searched.append(len(self))
            return str.__contains__(self, key)

    real = classify.parse_conflict

    def spying(text, labels=None):
        pf = real(text, labels=labels)
        spies = {}
        for h in (s for s in pf.segments if isinstance(s, Hunk)):
            if id(h.pre_context) not in spies:
                spies[id(h.pre_context)] = (h.pre_context, Spy(h.pre_context))   # keeps it alive
            h.pre_context = spies[id(h.pre_context)][1]
        return pf

    monkeypatch.setattr(classify, "parse_conflict", spying)
    pf = classify.classify_file(text, labels=LABELS)
    return [s.label for s in pf.segments if isinstance(s, Hunk)], sum(searched)


@pytest.mark.parametrize("words,label", [("", "generic-prose"),
                                         (" Current Focus", "current-focus-reprioritization")])
def test_r26_a_context_line_shared_by_many_regions_is_searched_once(monkeypatch, words, label):
    """2,000 regions under one 20 KB heading, separated by blank lines only, so all share it as
    `pre_context`. Searching it per region read 3 x 2,000 x 20 KB = 120 MB of characters (a 1 MB
    file of such regions took about a minute per `merge_back`); once per line object reads at most
    3 x 20 KB. Each region's sides carry a priority row and a design row, the one shape whose label
    the focus words decide, and every label equals what `classify_hunk` says for that hunk alone."""
    head = "## " + "x" * 20_000 + words
    regions = "".join(f"\n<<<<<<< {LABELS[0]}\n| 1 | a |\n| D{i} | b |\n||||||| {LABELS[1]}\n"
                      f"| 2 | c |\n=======\n| 3 | d |\n>>>>>>> {LABELS[2]}\n" for i in range(2000))
    labels, chars = _labels_and_chars_searched(monkeypatch, head + "\n" + regions + "\ntail")
    assert labels == [label] * 2000
    assert chars <= 3 * len(head), chars
    pf = parse_conflict(head + "\n" + regions + "\ntail", labels=LABELS)
    hunks = [s for s in pf.segments if isinstance(s, Hunk)]
    assert len({id(h.pre_context) for h in hunks}) == 1
    assert [classify.classify_hunk(h) for h in hunks] == labels
