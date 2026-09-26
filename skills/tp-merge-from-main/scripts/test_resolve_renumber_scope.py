"""Round 18, R1-R3 — the id-renumber lane, narrowed to the one shape it can prove.

R1  Two renumbering regions in ONE file each drew their new number from the same input, so both
    picked the same "free" ID: `L67 -> L69` and `L68 -> L69`, two `### L69:` headings staged as
    auto-resolved. `resolve.resolve_file` now refuses every renumber in such a file, and checks the
    assembled output for a duplicated renumbered heading as a backstop.
R2  The class accepted a base line both sides REWROTE (or one edited and the other deleted): the
    merge emits ours then theirs and never reads base, so `Status: fixed` and `Status: wontfix`
    were both glued into the merged entries. The class now requires an EMPTY base — the only
    shape two pure insertions at one point produce.
R3  Every refusal arm of `classify._is_id_renumber_collision` and `resolvers.resolve_id_renumber`
    is reached by a test on its own (a retitled base heading, the letters arm, the predicate
    re-check, the heading-elsewhere arm, a lower-case anchor).

End-to-end cases run real git through `merge_driver.merge_back`.

Round 20 GATED the class (`classify.GATED`): production defers every renumber hunk as `gated`.
The end-to-end cases here still defer, whether or not the class claims the region, and still pin
that nothing is renumbered. The UNIT cases exercise the gated, dormant resolver itself — through
`resolve.resolve_file` with the gate lifted for that one test (the `ungated_renumber` fixture of
`test_resolve_three_way`), or by calling `resolvers.resolve_id_renumber` directly — so the refusals pinned
so far stay pinned for whoever un-gates the class. None of them claims that production renumbers.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import resolvers  # noqa: E402
from classify import Hunk, classify_hunk  # noqa: E402
from resolve import DEFER, MECH_RESOLVERS, RESOLVED, HunkResult, resolve_file  # noqa: E402
from resolve_totality import CannotPlace  # noqa: E402
from test_merge_driver import git  # noqa: E402
from test_resolve_three_way import KI, RENUMBER, _merge, ungated_renumber  # noqa: E402,F401

LOW = "# Known Issues\n\n## Low\n\n"


def _region(ours, theirs, base=None):
    """One labelled-style diff3 region; `base=None` is the real EMPTY base (no line at all)."""
    base_part = "" if base is None else base + "\n"
    return f"<<<<<<< ours\n{ours}\n||||||| base\n{base_part}=======\n{theirs}\n>>>>>>> theirs"


def _assert_unmerged_and_untouched(repo, report):
    assert KI not in report.auto_resolved, report.to_json()
    assert git(repo, "ls-files", "-u", "--", KI).stdout.strip(), "the file must stay unmerged"


# ---- R1: at most one renumbering region per file -------------------------------------------------

def _two_points(tmp_path, base, top, bottom):
    ours = base.replace("## Low\n\n", "## Low\n\n" + top.format(side="ours")).replace(
        "body z\n", "body z\n\n" + bottom.format(side="ours"))
    theirs = base.replace("## Low\n\n", "## Low\n\n" + top.format(side="theirs")).replace(
        "body z\n", "body z\n\n" + bottom.format(side="theirs"))
    return _merge(tmp_path, KI, base, ours, theirs)


def test_r1_two_collisions_in_one_file_never_share_a_new_id(tmp_path):
    """THE R1 repro: both branches add `### L67:` near the top and `### L68:` at the bottom. Pre-fix
    both theirs entries became `### L69:` and the file was staged."""
    base = LOW + "### L66: a\nbody a\n\n## Tail\n\n### L10: z\nbody z\n"
    repo, report = _two_points(tmp_path, base, "### L67: {side} top\n{side} body\n\n",
                               "### L68: {side} bottom\n{side} b\n")
    _assert_unmerged_and_untouched(repo, report)
    assert (repo / KI).read_text(encoding="utf-8").count("### L69:") == 0


def test_r1_the_section_variant_defers_too(tmp_path):
    """Base `L60` in section A, `L61` in B; both sides add `L62` in A and `L63` in B. Pre-fix: two
    `### L64:` headings."""
    base = "# Known Issues\n\n## Low\n\n### L60: a\nbody a\n\n## Tail\n\n### L61: z\nbody z\n"
    repo, report = _two_points(tmp_path, base, "### L62: {side} in A\nA {side}\n\n",
                               "### L63: {side} in B\nB {side}\n")
    _assert_unmerged_and_untouched(repo, report)
    assert "### L64:" not in (repo / KI).read_text(encoding="utf-8")


def test_r1_every_renumbering_region_defers_verbatim_and_other_regions_still_resolve(
        ungated_renumber):
    text = ("### L66: a\n" + _region("### L67: ours", "### L67: theirs") + "\n## Middle\n"
            + _region("### L68: ours", "### L68: theirs") + "\n## Tail\n"
            + _region("- **2026-09-01** — ours", "- **2026-09-02** — theirs"))
    status, lines, results = resolve_file(text)
    assert status == DEFER
    assert [(r.status, r.code) for r in results] == [
        (DEFER, "cannot-place"), (DEFER, "cannot-place"), (RESOLVED, "")], results
    assert "renumber IDs" in results[0].reason, results[0].reason
    out = "\n".join(lines)
    assert out.count("<<<<<<< ours\n### L67: ours") == 1 and "### L69:" not in out
    single = "### L66: a\n" + _region("### L67: ours", "### L67: theirs")
    assert resolve_file(single)[2][0].renumbered == {"L67": "L68"}, "the happy path still works"


def test_r1_backstop_a_renumbered_id_that_is_already_a_heading_defers(monkeypatch,
                                                                     ungated_renumber):
    """The output-reading backstop, driven by a resolver that ignores the file and renames theirs'
    `L4` to the `L3` a clean line already carries. Every per-hunk post-condition passes (the
    renumber licence masks both spellings), so only the file-level check can see it."""
    real = resolvers.resolve_id_renumber

    def _reuses_l3(h):
        r = real(h)
        return HunkResult(r.label, RESOLVED, [ln.replace("L5", "L3") for ln in r.lines],
                          renumbered={"L4": "L3"})
    monkeypatch.setitem(MECH_RESOLVERS, "id-renumber-collision", _reuses_l3)
    text = "### L3: prior\n" + _region("### L4: ours", "### L4: theirs")
    status, lines, results = resolve_file(text)
    assert status == DEFER and results[0].code == "cannot-place", results[0].reason
    assert "heading 2 time(s)" in results[0].reason, results[0].reason
    assert "\n".join(lines) == text


# ---- R2: the base must be empty ------------------------------------------------------------------

def test_r2_both_sides_rewriting_a_base_line_is_not_a_collision(tmp_path):
    """THE R2 repro. Pre-fix: auto-resolved with L60 `Status: fixed` and `Status: wontfix` glued
    onto ours' L61 body."""
    base = LOW + "### L60: flaky merge\nBody\nStatus: open\n"
    ours = base.replace("Status: open\n", "Status: fixed\n\n### L61: ours new\nours body\n")
    theirs = base.replace("Status: open\n", "Status: wontfix\n\n### L61: theirs new\ntheirs body\n")
    repo, report = _merge(tmp_path, KI, base, ours, theirs)
    _assert_unmerged_and_untouched(repo, report)


def test_r2_an_edit_against_a_deletion_of_a_base_line_is_not_a_collision(tmp_path):
    """Theirs edits L4's Workaround line, ours deletes it; both add `### L5:`. Pre-fix theirs'
    edited Workaround line landed under ours' L5."""
    base = LOW + "### L4: slow ci\n**Workaround**: rerun\n"
    ours = base.replace("**Workaround**: rerun\n", "\n### L5: ours new\nours body\n")
    theirs = base.replace("**Workaround**: rerun\n",
                          "**Workaround**: rerun twice\n\n### L5: theirs new\ntheirs body\n")
    repo, report = _merge(tmp_path, KI, base, ours, theirs)
    _assert_unmerged_and_untouched(repo, report)


def test_r3_both_sides_retitling_a_base_heading_is_not_a_collision(tmp_path):
    """F4a's shape with NO side keeping base's heading line, so the base-line arm alone decides.
    On the round-17 mutant without the heading check this auto-resolved with an invented
    `### L63:` and L62's body under ours' heading."""
    base = LOW + "### L62: flaky\nbody62\n\n### L61: x\nbody\n"
    ours = base.replace("### L62: flaky", "### L62: flaky ours title")
    theirs = base.replace("### L62: flaky", "### L62: flaky theirs title")
    repo, report = _merge(tmp_path, KI, base, ours, theirs)
    _assert_unmerged_and_untouched(repo, report)
    assert "### L63:" not in (repo / KI).read_text(encoding="utf-8")


@pytest.mark.parametrize("hunk", [
    Hunk(ours=["### L4: a"], base=["Status: open"], theirs=["### L4: b"], post_context=""),
    Hunk(ours=["### L4: a"], base=[""], theirs=["### L4: b"], post_context=""),
    Hunk(ours=["### L4: a"], base=[], theirs=["### L4: b"], base_marker=None, post_context=""),
], ids=["non-blank-base", "blank-base", "two-way"])
def test_r2_anything_but_an_empty_recorded_base_is_refused(hunk):
    assert classify_hunk(hunk) != "id-renumber-collision"
    control = Hunk(ours=["### L4: a"], base=[], theirs=["### L4: b"], post_context="")   # EOF
    assert classify_hunk(control) == "id-renumber-collision"


# ---- R3: every remaining refusal arm, on its own -------------------------------------------------

def test_r3_the_letters_arm_alone():
    """A real `L4` collision, empty base — but ours also adds an `M2`. Only the one-letter arm
    refuses this; without it the resolver renumbered with whichever letter `set.pop()` gave."""
    h = Hunk(ours=["### L4: a", "### M2: b"], base=[], theirs=["### L4: c"], post_context="")
    assert classify_hunk(h) == "generic-prose"
    control = Hunk(ours=["### L4: a", "### L2: b"], base=[], theirs=["### L4: c"], post_context="")
    assert classify_hunk(control) == RENUMBER


def test_r3_the_resolver_rechecks_the_predicate_on_a_hand_built_hunk():
    h = Hunk(ours=["### L4: a"], base=["Status: open"], theirs=["### L4: b"],
             label="id-renumber-collision")
    with pytest.raises(CannotPlace, match="not a same-letter collision"):
        resolvers.resolve_id_renumber(h)


def test_r3_an_id_that_is_already_a_heading_elsewhere_refuses(ungated_renumber):
    text = "### L5: earlier\n" + _region("### L4: ours\n### L5: ours again", "### L4: theirs")
    status, lines, results = resolve_file(text)
    assert status == DEFER and "already a heading elsewhere" in results[0].reason, results[0].reason
    assert "\n".join(lines) == text


@pytest.mark.parametrize("where", ["outside", "theirs"])
def test_minor_a_lower_case_anchor_to_the_colliding_id_refuses(where, ungated_renumber):
    """GitHub lowercases heading anchors: `### L5: retry flake` is `#l5-retry-flake`. Pre-fix the
    case-sensitive scan missed it, theirs' L5 moved, and the link dangled at ours' entry."""
    link = "see [the flake](#l5-retry-flake)"
    theirs = "### L5: retry flake" + (f"\n{link}" if where == "theirs" else "")
    text = ("### L4: prior\n" + (link + "\n" if where == "outside" else "")
            + _region("### L5: ours", theirs))
    status, lines, results = resolve_file(text)
    assert status == DEFER and results[0].code == "cannot-place", results[0].reason
    assert "\n".join(lines) == text


# ---- round 19, M-c / M-d: the two unpinned directions -------------------------------------------

def test_minor_the_backstop_also_refuses_a_renumbered_id_that_is_no_heading_at_all(
        monkeypatch, ungated_renumber):
    """The other half of `heads.count(new) != 1`: a resolver that reports `L4 -> L5` but never
    retags theirs' heading. The renumber licence masks both spellings, so every per-hunk check
    passes; only the file-level backstop can see that `L5` is a heading zero times. With `> 1` in
    place of `!= 1` this resolved."""
    monkeypatch.setitem(MECH_RESOLVERS, "id-renumber-collision", lambda h: HunkResult(
        h.label, RESOLVED, list(h.ours) + list(h.theirs), renumbered={"L4": "L5"}))
    text = "### L3: prior\n" + _region("### L4: ours", "### L4: theirs")
    status, lines, results = resolve_file(text)
    assert status == DEFER and results[0].code == "cannot-place", results[0].reason
    assert "heading 0 time(s)" in results[0].reason, results[0].reason
    assert "\n".join(lines) == text


def test_minor_a_lower_case_mention_of_the_next_free_id_refuses(ungated_renumber):
    """The next-free-ID check reads the file case-insensitively too: `#l5-slug` links an entry
    that is (or was) `L5`, so choosing `L5` would make that link point at theirs' renumbered
    entry. A case-sensitive scan at that site resolved this to `{"L4": "L5"}`."""
    text = "### L3: prior\nsee [the slug](#l5-slug)\n" + _region("### L4: ours", "### L4: theirs")
    status, lines, results = resolve_file(text)
    assert status == DEFER and "next free ID L5" in results[0].reason, results[0].reason
    assert "\n".join(lines) == text


if __name__ == "__main__":
    sys.exit(pytest.main([__file__]))
