"""S-H1: the RESOLVER deleted a real line, and no atom inventory could ever see it.

Every earlier zero-drop defect on this branch was `verify_atoms.atoms()` failing to *see* content.
This one is different in kind: `classify.parse_conflict` mis-parsed, `resolve.resolve_file`
returned RESOLVED, and a line of the input was simply **gone** from the output.

The mechanism: `ours` was terminated ONLY by `|||||||`, so a region without a base section ran on
past its own `=======` and `>>>>>>>` and swallowed the whole rest of the file into `ours` (and the
unconditional `i += 1` after each scan walked past EOF). A line of prose that merely QUOTES
conflict syntax — which this repo's own SKILL.md and decisions.md do constantly — was enough:

    <<<<<<< see below for an example      <- coincidental prose, no `|||||||` follows
    some illustrative text
    =======
    >>>>>>> end example
    ...a genuine conflict further down...

`ours` ate everything from `some illustrative text` to the genuine region's `|||||||`, the hunk
classified as `id-renumber-collision`, the resolver emitted only the entries it recognised, and the
prose line was permanently dropped under a RESOLVED verdict. `verify()` cannot catch it: `entry`
atoms are title-only with no body digest, so the deleted line is not an atom at all.

The fix is two rules in `conflict_parse._scan_region` — `ours` ends at the first `|||||||` OR
`=======`, and an unclosed region is CONTENT rather than a hunk — plus a verbatim
`resolve._deferred`. This module pins the defect and those rules directly; the four preservation
invariants they buy (P0 lossless parse, P1 exact DEFER round trip, P2 region agreement, P3 nothing
outside a region is deleted) are asserted over a generated corpus in `test_resolve_invariants.py`.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from classify import Hunk, parse_conflict  # noqa: E402
from conflict_fixtures import COINCIDENTAL_PROSE_THEN_CONFLICT, PROSE_OPEN  # noqa: E402
from resolve import DEFER, RESOLVED, resolve_file  # noqa: E402
from test_resolve_three_way import ungated_renumber  # noqa: E402,F401 — a pytest fixture

S_H1 = COINCIDENTAL_PROSE_THEN_CONFLICT


# ---- the repro ---------------------------------------------------------------------------------

def test_the_prose_line_survives_resolve_file_verbatim():
    """THE S-H1 regression. Pre-fix: status RESOLVED and the line simply absent from the output."""
    status, lines, _results = resolve_file(S_H1)
    assert PROSE_OPEN in lines, ("the prose line was DROPPED", lines)
    assert "some illustrative text" in lines
    assert "unrelated clean line" in lines
    assert status == DEFER, "a file still carrying quoted-conflict prose must not certify as clean"


def test_the_genuine_conflict_after_the_prose_still_resolves(ungated_renumber):
    """The fix is not "defer everything": the real region below the prose is still parsed and
    still mechanically resolved. Without this, the repro could be 'fixed' by giving up. (That
    region is an `id-renumber-collision`, GATED since round 20; the gate is lifted for this test
    so the resolver behind the parse still runs. In production the region defers as `gated`.)"""
    _status, lines, results = resolve_file(S_H1)
    assert [r.label for r in results] == ["generic-prose", "id-renumber-collision"]
    assert [r.status for r in results] == [DEFER, RESOLVED]
    assert "### L5: theirs" in lines, "the ID collision was renumbered and kept"


def test_the_two_regions_are_parsed_as_two():
    """The mis-parse itself, stated at the parser: the coincidental prose region and the genuine
    one are separate hunks, and neither swallows the other."""
    hunks = [s for s in parse_conflict(S_H1).segments if isinstance(s, Hunk)]
    assert len(hunks) == 2
    assert hunks[0].ours == ["some illustrative text"] and hunks[0].theirs == []
    assert hunks[0].base_marker is None, "the prose region has no base section"
    assert hunks[1].ours == ["### L4: ours"] and hunks[1].theirs == ["### L4: theirs"]


# ---- the two parse rules, stated directly -------------------------------------------------------

def test_ours_ends_at_the_first_equals_when_there_is_no_base_marker():
    """Rule 1. A 2-way region has no `|||||||` at all; `ours` must stop at `=======` anyway."""
    pf = parse_conflict("<<<<<<< a\nO\n=======\nT\n>>>>>>> b\ntail")
    hunks = [s for s in pf.segments if isinstance(s, Hunk)]
    assert len(hunks) == 1
    assert (hunks[0].ours, hunks[0].base, hunks[0].theirs) == (["O"], [], ["T"])
    assert hunks[0].base_marker is None, "no base section was present, so none may be invented"
    assert pf.segments[-1] == ["tail"], "the region must not run on past its own close marker"


def test_an_unterminated_region_is_content_not_a_hunk():
    """Rule 2. `git merge-file` always emits well-formed regions, so an unclosed `<<<<<<<` is
    prose. Treating it as a hunk is what deleted content; keeping it is the fail-safe polarity."""
    text = "### [tp-plan] a decision\n<<<<<<< ours\nours side\n=======\ntheirs side\nno close\n"
    pf = parse_conflict(text)
    assert not [s for s in pf.segments if isinstance(s, Hunk)], "an unclosed region is not a hunk"
    status, lines, results = resolve_file(text)
    assert (status, results) == (RESOLVED, [])
    assert "\n".join(lines) == text, "an unterminated region must round-trip byte-for-byte"


def test_a_region_whose_base_section_never_closes_is_content_too():
    """The `|||||||`-opened variant of rule 2 — the arm the old unconditional `i += 1` walked
    past EOF on."""
    pf = parse_conflict("<<<<<<< a\nO\n||||||| b\nB\nB2\n")
    assert not [s for s in pf.segments if isinstance(s, Hunk)]


def test_a_nested_open_marker_defers_the_whole_region_rather_than_splitting_it():
    """The OUTERMOST open wins, deliberately. A stray `<<<<<<<` above a genuine region makes the
    scan read one big region that then DEFERS — the auto-merge is lost, nothing else is.

    The alternative (innermost wins) would resolve the inner conflict, but at the cost of
    re-cutting a genuine region whose `ours` side legitimately quotes conflict syntax: its real
    open marker and the ours-lines above the quote would become "clean content" and the two sides
    would be mis-paired. Over-merging costs a human a resolve; mis-cutting risks a wrong merge.
    """
    text = ("<<<<<<< stray\nprose under a stray marker\n"
            "<<<<<<< ours\n- **2026-07-04** — A\n||||||| base\n=======\n"
            "- **2026-07-05** — B\n>>>>>>> theirs")
    status, lines, results = resolve_file(text)
    assert (status, [r.status for r in results]) == (DEFER, [DEFER])
    assert "\n".join(lines) == text, "an over-merged region must still round-trip verbatim"


def test_a_deferral_keeps_gits_own_side_labels_and_base_section():
    """Deferral means "we did not understand this", so it must not edit the region. The old form
    re-synthesised generic labels and DELETED the whole `||||||| base` section."""
    text = ("<<<<<<< HEAD\nours rewrote the paragraph\n||||||| merged common ancestors\n"
            "the original paragraph\n=======\ntheirs rewrote it differently\n>>>>>>> origin/master")
    status, lines, results = resolve_file(text)
    assert status == DEFER and results[0].status == DEFER
    assert "\n".join(lines) == text
    assert "<<<<<<< HEAD" in lines and ">>>>>>> origin/master" in lines
    assert "the original paragraph" in lines, "the diff3 base section was dropped pre-fix"


# ---- S-I2: exactly ONE separator in a region is structural ------------------------------------

def test_only_the_separator_after_the_base_marker_is_structural():
    """S-I2. `_scan_region` took the FIRST line prefix-matching `=======` as the separator, with
    no check that it was not content — so a region whose `ours` quotes conflict syntax was cut at
    the quote, and everything from there to the real separator was re-read as `base` and deleted.

    Real `git merge-file --diff3` always orders `<<<<<<<` -> `|||||||` -> `=======` -> `>>>>>>>`,
    so the region's own close marker decides its extent and the base marker decides where `ours`
    ends. Any `=======` BEFORE the `|||||||` is content.

    The resolver half uses `log-entry-insertion` entries, a class that may auto-resolve, so the
    deferral is the marker check's (`malformed-hunk`). The `### L4:` entries it used until round 21
    are an `id-renumber-collision`, GATED since round 20, which deferred before that check ran."""
    ours, theirs = "- **2026-01-02** — ours", "- **2026-01-03** — theirs"
    text = (f"<<<<<<< ours\n{ours}\n======= see example above\n||||||| base\n=======\n"
            f"{theirs}\n>>>>>>> theirs")
    hunks = [s for s in parse_conflict(text).segments if isinstance(s, Hunk)]
    assert len(hunks) == 1
    assert hunks[0].ours == [ours, "======= see example above"]
    assert hunks[0].base == [] and hunks[0].theirs == [theirs]

    status, lines, results = resolve_file(text)
    assert "======= see example above" in lines, ("the content line was DROPPED", lines)
    assert status == DEFER and "\n".join(lines) == text
    assert [(r.label, r.code) for r in results] == [("log-entry-insertion", "malformed-hunk")]


def test_a_setext_underline_inside_ours_is_content_not_a_separator():
    """The same rule on the shape that makes it more than a curiosity: `=======` under a title is
    a setext H1, ordinary markdown that any living doc may carry inside a conflicted region."""
    text = ("<<<<<<< ours\nSection Title\n=======\nunder the rule\n||||||| base\n=======\n"
            "theirs rewrote the section\n>>>>>>> theirs")
    hunk = next(s for s in parse_conflict(text).segments if isinstance(s, Hunk))
    assert hunk.ours == ["Section Title", "=======", "under the rule"]
    assert hunk.theirs == ["theirs rewrote the section"]
    _status, lines, _results = resolve_file(text)
    assert "\n".join(lines) == text


def test_a_region_with_no_separator_before_its_close_is_content():
    """The lookahead's fail-closed arm: a `<<<<<<<` and a `>>>>>>>` with nothing between them that
    the grammar accepts is not a region, so both lines stay as prose."""
    text = "<<<<<<< see below\nan illustrative line\n>>>>>>> end example\nreal tail"
    pf = parse_conflict(text)
    assert not [s for s in pf.segments if isinstance(s, Hunk)]
    status, lines, results = resolve_file(text)
    assert (status, results) == (RESOLVED, [])
    assert "\n".join(lines) == text


# ---- S-I3: context survives an adjacent hunk ---------------------------------------------------

def test_pre_context_looks_back_past_an_adjacent_hunk():
    """S-I3. `_pre_context` returned `""` the moment the preceding segment was a `Hunk`, so with
    two ADJACENT regions the second one lost the heading above the first — and `classify_hunk`'s
    `focus_ctx` check silently evaluated False, the exact inversion of the function's documented
    fail-closed guarantee."""
    text = ("## Current Focus\n"
            "<<<<<<< ours\n| 1 | alpha | act | — |\n||||||| base\n=======\n"
            "| 2 | beta | act | — |\n>>>>>>> theirs\n"
            "<<<<<<< ours\n| 3 | gamma | act | — |\n| D12 | d | design | OURS |\n||||||| base\n"
            "=======\n| 4 | delta | act | — |\n| D12 | d | design | THEIRS |\n>>>>>>> theirs")
    hunks = [s for s in parse_conflict(text).segments if isinstance(s, Hunk)]
    assert [h.pre_context for h in hunks] == ["## Current Focus", "## Current Focus"]


def test_the_second_adjacent_hunk_stays_semantic_and_keeps_theirs_focus_row():
    """The consequence the lost context caused: a hunk mixing a Current-Focus priority row with an
    inventory row classified `design-inventory-row-merge` (MECHANICAL) instead of
    `current-focus-reprioritization` (SEMANTIC), and theirs' non-ID-keyed focus row — which the
    row-merge resolver has no key for — was dropped."""
    text = ("## Current Focus\n"
            "<<<<<<< ours\n| 1 | alpha | act | — |\n||||||| base\n=======\n"
            "| 2 | beta | act | — |\n>>>>>>> theirs\n"
            "<<<<<<< ours\n| 3 | gamma | act | — |\n| D12 | d | design | OURS |\n||||||| base\n"
            "=======\n| 4 | delta | act | — |\n| D12 | d | design | THEIRS |\n>>>>>>> theirs")
    status, lines, results = resolve_file(text)
    assert [r.label for r in results] == ["current-focus-reprioritization"] * 2
    assert status == DEFER
    assert "| 4 | delta | act | — |" in lines, ("theirs' focus row was DROPPED", lines)
    assert "\n".join(lines) == text
