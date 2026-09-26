"""Preservation invariants for the conflict parser + resolver, over a generated corpus.

Companion to `test_resolve_preservation.py`: that module pins the S-H1 defect and the two parse
rules that fix it, this one pins the general properties those rules buy. All four hold for ANY
input, and none needs an atom inventory — the point, since S-H1 was a drop the verifier is
structurally blind to (`entry` atoms are title-only, so a deleted body line is not an atom).

  P0  **The parse is LOSSLESS** — re-emitting every segment verbatim (clean lines, plus each
      hunk's own marker lines around its three sides) rebuilds the input byte-for-byte, so every
      input line belongs to exactly one segment: the parse is a partition.
  P1  **DEFER is a byte-exact round trip** — if no hunk resolved, the output IS the input.
  P2  **Region agreement** — the spans `parse_conflict` calls conflict regions are exactly those
      an INDEPENDENT scanner (`_spans`, written from the diff3 grammar) calls conflict regions.
  P3  **Nothing outside a region is ever deleted**, on any verdict.

P0 and P2 are the pair that fails against the pre-fix code (`test_p0_and_p2_both_fail_against_
the_pre_fix_parser` replays it, so that stays falsifiable). Together the four say: a line can go
missing only from inside a span BOTH observers agree is a genuine region, and only when that
region was mechanically merged.

Why the set needs P0/P2 and not just P3: in the S-H1 repro the dropped prose sits INSIDE a
shape-well-formed 2-way region, so an "outside survives" rule excuses its loss. The drop is a
mis-PARSE — two regions read as one — and only a partition/agreement statement sees it.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(__file__))
from classify import Hunk, parse_conflict  # noqa: E402
from conflict_fixtures import COINCIDENTAL_PROSE_THEN_CONFLICT, PROSE_OPEN  # noqa: E402
from preservation_corpus import corpus as _corpus  # noqa: E402
from resolve import DEFER, RESOLVED, resolve_file  # noqa: E402

S_H1 = COINCIDENTAL_PROSE_THEN_CONFLICT


# ---- an INDEPENDENT region scanner (the P2/P3 observer) ---------------------------------------

_SYMBOL = {"<<<<<<<": "<", "|||||||": "|", "=======": "=", ">>>>>>>": ">"}
# The diff3 region grammar, as a regex over one symbol PER LINE. Reading left to right:
#   3-way  `<` , ours-with-no-`|`-or-`>` , `|` , base-with-no-`=`-or-`>` , `=` , theirs , `>`
#   2-way  `<` , ours , `=` , theirs , `>`   — with no `|` ANYWHERE inside the region
# The character classes are what encode "close FIRST, then split": no branch may cross a `>`, so a
# region always ends at the first close marker; `[^>|]*\|` picks the FIRST base marker, and
# `[^>=]*=` the first separator AFTER it, which is what makes an earlier `=======` CONTENT. The
# 2-way branch forbids `|` on both sides of its separator, because a base marker anywhere before
# the close means the region is 3-way and must satisfy the 3-way branch or not match at all.
_REGION = re.compile(r"<(?:[^>|]*\|[^>=]*=[^>]*|[^>|]*=[^>|]*)>")


def _spans(text):
    """`(first, last)` inclusive line indices of every well-formed conflict region.

    Deliberately a SECOND implementation, and a structurally different one: the parser walks lines
    and slices, this one projects each line to a single marker SYMBOL and matches the grammar as a
    regular expression over that string. If the parser under test were also the oracle, P2 would
    assert only that the parser agrees with itself. Same spirit as
    `test_verify_superset._naive_atoms`.

    Non-overlapping `finditer` gives exactly the parser's scan discipline for free: leftmost match
    wins, the next search resumes after the close marker, and a `<<<<<<<` that cannot start a
    grammatical region is simply skipped over as content.
    """
    symbols = "".join(_SYMBOL.get(ln[:7], ".") for ln in text.split("\n"))
    return [(m.start(), m.end() - 1) for m in _REGION.finditer(symbols)]


def _inside(text):
    return {n for first, last in _spans(text) for n in range(first, last + 1)}


def _outside(text):
    inside = _inside(text)
    return [ln for n, ln in enumerate(text.split("\n")) if n not in inside]


def _parser_spans(text):
    """The same `(first, last)` spans, derived from what `parse_conflict` actually produced. Uses
    only segment SIZES, so it is a faithful readout of the parser's own boundaries."""
    spans, n = [], 0
    for seg in parse_conflict(text).segments:
        if not isinstance(seg, Hunk):
            n += len(seg)
            continue
        size = 3 + len(seg.ours) + len(seg.theirs)      # open + sep + close markers
        if seg.base_marker is not None:
            size += 1 + len(seg.base)
        spans.append((n, n + size - 1))
        n += size
    return spans, n


def _reassemble(text):
    """Every segment re-emitted VERBATIM — the P0 reconstruction."""
    out = []
    for seg in parse_conflict(text).segments:
        if not isinstance(seg, Hunk):
            out += seg
            continue
        out.append(seg.open_marker)
        out += seg.ours
        if seg.base_marker is not None:
            out.append(seg.base_marker)
            out += seg.base
        out.append(seg.sep_marker)
        out += seg.theirs
        out.append(seg.close_marker)
    return "\n".join(out)


def _is_subsequence(needles, haystack):
    it = iter(haystack)
    return all(any(x == y for y in it) for x in needles)


# ---- P0: the parse is a lossless partition of the input ---------------------------------------

def test_p0_parse_conflict_is_lossless_for_any_input():
    """THE structural invariant, and the one the S-H1 defect violated: every input line lands in
    exactly one segment, so re-emitting the segments verbatim rebuilds the input byte-for-byte.

    Pre-fix this failed two ways at once — a region that ran on past EOF swallowed marker lines
    into `ours`, and the unconditional `i += 1` consumed terminators that had never been matched.
    """
    bad = []
    for name, text in _corpus():
        got = _reassemble(text)
        if got != text:
            bad.append((name, repr(text)[:120], repr(got)[:120]))
    assert not bad, f"parse_conflict LOST content — the parse is not a partition: {bad[:4]}"


def test_p0_segment_sizes_account_for_every_line():
    """The same statement counted rather than compared, so a self-cancelling pair of errors (one
    line invented, one dropped) still fails."""
    for name, text in _corpus():
        _spans_, total = _parser_spans(text)
        assert total == len(text.split("\n")), (name, total, len(text.split("\n")))


# ---- P1: DEFER is a byte-exact round trip -----------------------------------------------------

def test_p1_a_fully_deferred_file_is_returned_byte_for_byte():
    """If the resolver resolved NOTHING, it must have CHANGED nothing. This is the strongest
    possible statement of "dropped nothing", and it needs no atom inventory to check."""
    exercised = 0
    for name, text in _corpus():
        status, lines, results = resolve_file(text)
        if not results or any(r.status == RESOLVED for r in results):
            continue
        exercised += 1
        assert status == DEFER, name
        assert "\n".join(lines) == text, (name, repr(text), repr("\n".join(lines)))
    assert exercised >= 50, f"P1 only reached {exercised} inputs — it has gone vacuous"


def test_p1_is_not_vacuous_because_the_deferred_inputs_really_contain_regions():
    """The floor under P1: the inputs it exercises must actually contain hunks, or "output ==
    input" is only asserting the conflict-free round trip already pinned elsewhere."""
    with_hunks = 0
    for _name, text in _corpus():
        _status, _lines, results = resolve_file(text)
        if results and all(r.status == DEFER for r in results):
            with_hunks += 1
    assert with_hunks >= 50, with_hunks


# ---- P2: the two observers agree on where the regions are -------------------------------------

def test_p2_parser_regions_match_an_independent_scan():
    """The parser's own conflict-region boundaries must equal a second implementation's. This is
    what the S-H1 defect broke: two regions were read as one, and the first one's marker line
    became `ours` content of the second — then the resolver dropped it."""
    disagree = []
    for name, text in _corpus():
        mine, _total = _parser_spans(text)
        theirs = _spans(text)
        if mine != theirs:
            disagree.append((name, mine[:3], theirs[:3]))
    assert not disagree, f"parse_conflict disagrees with the grammar on region spans: {disagree[:4]}"


def test_p2_is_not_vacuous():
    """Floors: the independent scanner must find plenty of real regions, and plenty of lines
    outside them, or agreement is agreement about nothing.

    Set just under the MEASURED counts (2026-09-10: 438 docs, 569 regions, 1741 outside lines).
    The previous 100/500 floors sat at a fifth and a third of actual — a regression that halved
    region generation, or one that stopped generating regions inside most documents, would have
    passed them unnoticed, which is the opposite of what a non-vacuity floor is for.
    """
    docs = _corpus()
    assert len(docs) >= 430, len(docs)
    regions = sum(len(_spans(t)) for _n, t in docs)
    outside = sum(len(_outside(t)) for _n, t in docs)
    assert regions >= 520, regions
    assert outside >= 1600, outside


def test_p0_and_p2_both_fail_against_the_pre_fix_parser():
    """Non-vacuity as a counterfactual: replay the OLD scan on the repro and show both invariants
    report it. Guards against a future 'simplification' that makes them unfalsifiable."""
    def _pre_fix(text):
        """The exact pre-fix scan, inlined — returns (reassembled_lines, hunk_count)."""
        lines, out, i, clean, hunks = text.split("\n"), [], 0, [], 0
        while i < len(lines):
            if lines[i].startswith("<<<<<<<"):
                out += clean
                clean = []
                hunks += 1
                ours, base, theirs = [], [], []
                i += 1
                while i < len(lines) and not lines[i].startswith("|||||||"):
                    ours.append(lines[i]); i += 1
                i += 1
                while i < len(lines) and not lines[i].startswith("======="):
                    base.append(lines[i]); i += 1
                i += 1
                while i < len(lines) and not lines[i].startswith(">>>>>>>"):
                    theirs.append(lines[i]); i += 1
                i += 1
                out += ours + base + theirs        # the most generous possible reading
            else:
                clean.append(lines[i]); i += 1
        return out + clean, hunks

    old_lines, old_hunks = _pre_fix(S_H1)
    assert PROSE_OPEN not in old_lines, "the counterfactual no longer reproduces the drop"
    assert "\n".join(old_lines) != S_H1, "P0 must FAIL against the pre-fix parse"
    assert old_hunks == 1 and len(_spans(S_H1)) == 2, (
        "P2 must FAIL against the pre-fix parse: it read the two regions as one")
    assert _parser_spans(S_H1)[0] == _spans(S_H1), "and the fixed parser must agree"


# ---- P3: nothing outside a region is ever deleted ---------------------------------------------

def test_p3_every_line_outside_a_conflict_region_survives_in_order():
    """Weaker than P0/P2 and deliberately kept: on ANY verdict, for ANY input, the lines the
    independent scanner places OUTSIDE a region come out unchanged and in order. Inside a region
    the resolver may merge; outside it has no licence at all."""
    failures = []
    for name, text in _corpus():
        _status, lines, _results = resolve_file(text)
        outside = _outside(text)
        if not _is_subsequence(outside, lines):
            failures.append((name, [ln for ln in outside if ln not in lines][:3]))
    assert not failures, f"lines outside any conflict region were DROPPED: {failures[:6]}"
