"""Round 19, P1/P2 — a keep-both merge must keep every line under the entry it was written under.

P1  `id-renumber-collision` had no block-purity predicate: it required only an empty base, then
    emitted ours' block and theirs'. (a) theirs' leading non-entry line (`Workaround: rerun the
    job.`, which continued base's L4) landed under ours' new L5; an identical such line on both
    sides was duplicated too. (b) ours' trailing `## Won't Fix` section swallowed theirs' entry.
    The same defect sits at the region's far edge: a body line AFTER the region, which both sides
    made part of their own new entry, moved from ours' entry to theirs'. Each side must now be
    whole ID-headed entries, and the region must end at a level-1..3 heading or EOF.
P2  `append-only-log` put theirs' continuation line (`  (alpha later reverted in PR #9)`) under
    ours' last appended bullet. Two differing tails must each be whole log entries now.
    The far-edge arm applies to `log-entry-insertion` and `decision-entry-insertion` as well.
M-a An entry byte-identical on both sides was kept twice, the copy under an invented ID.
M-e A partially-resolved outcome discarded why each remaining region deferred.

End-to-end cases run real git through `merge_driver.merge_back`; every arm is also reached alone.
Round 20 GATED `id-renumber-collision`: its end-to-end cases defer in production whatever the
predicate says, so the P1 and M-a arms are pinned at the classifier and by calling the dormant
`resolvers.resolve_id_renumber` directly.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import merge_driver  # noqa: E402
import resolvers  # noqa: E402
from auto_safe_resolution import MergeFileError  # noqa: E402
from classify import Hunk, classify_hunk, parse_conflict  # noqa: E402
from resolve import RESOLVED, resolve_hunk  # noqa: E402
from resolve_totality import CannotPlace  # noqa: E402
from merge_driver import merge_back  # noqa: E402
from test_merge_driver import git, setup_collision  # noqa: E402
from test_resolve_three_way import KI, ROADMAP, _merge  # noqa: E402

L4 = "# Known Issues\n\n## Low\n\n### L4: flaky retry\nStatus: open\n"
RENUMBER = "id-renumber-collision"


def _deferred_untouched(repo, report, path):
    assert path not in report.auto_resolved, report.to_json()
    assert git(repo, "ls-files", "-u", "--", path).stdout.strip(), "the file must stay unmerged"


# ---- P1, end to end ------------------------------------------------------------------------------

@pytest.mark.parametrize("lead", [
    "Workaround: rerun the job.\n", "**Update 2026-09-10**: L4 now also reproduces on CI.\n",
], ids=["workaround", "update-note"])
def test_p1a_theirs_leading_line_is_not_re_parented_under_ours_entry(tmp_path, lead):
    """THE P1(a) repro. Pre-fix: staged, with the line under ours' L5 and theirs' entry as L6."""
    ours = L4 + "\n### L5: ours issue\nours body\n"
    theirs = L4 + lead + "\n### L5: theirs issue\ntheirs body\n"
    repo, report = _merge(tmp_path, KI, L4, ours, theirs)
    _deferred_untouched(repo, report, KI)
    assert "### L6:" not in (repo / KI).read_text(encoding="utf-8")


def test_p1a_an_identical_leading_line_is_neither_re_parented_nor_duplicated(tmp_path):
    ours = L4 + "Note X.\n\n### L5: ours issue\nours body\n"
    theirs = L4 + "Note X.\n\n### L5: theirs issue\ntheirs body\n"
    repo, report = _merge(tmp_path, KI, L4, ours, theirs)
    _deferred_untouched(repo, report, KI)
    assert "### L6:" not in (repo / KI).read_text(encoding="utf-8")


def test_p1b_ours_trailing_section_does_not_swallow_theirs_entry(tmp_path):
    """THE P1(b) repro. Pre-fix: theirs' entry, renumbered L6, landed under ours' `## Won't Fix`."""
    ours = L4 + "\n### L5: ours issue\nours body\n\n## Won't Fix\n\n### L3: old\nold body\n"
    theirs = L4 + "\n### L5: theirs issue\ntheirs body\n"
    repo, report = _merge(tmp_path, KI, L4, ours, theirs)
    _deferred_untouched(repo, report, KI)
    assert "### L6:" not in (repo / KI).read_text(encoding="utf-8")


def test_p1_a_body_line_after_the_region_does_not_move_to_theirs_entry(tmp_path):
    """Both sides insert `### L5:` between L4's `Status` and its `Workaround` paragraph, so on each
    side the paragraph ends that side's L5. Pre-fix the merge put it under theirs' L6 only."""
    base = L4 + "\nWorkaround: rerun the job.\n"
    ours = base.replace("Status: open\n", "Status: open\n\n### L5: ours issue\nours body\n")
    theirs = base.replace("Status: open\n", "Status: open\n\n### L5: theirs issue\ntheirs body\n")
    repo, report = _merge(tmp_path, KI, base, ours, theirs)
    _deferred_untouched(repo, report, KI)


def test_p1_the_real_newest_first_shape_is_the_class_and_defers_as_gated(tmp_path):
    """The shape the predicate must keep claiming: both branches add a new top entry under `## Low`,
    right above the newest one, exactly as `known_issues.md` is laid out. Until round 20 it
    auto-resolved (theirs' entry became L68); the class is GATED now, so it defers AS that class."""
    base = "# Known Issues\n\n## Low\n### L66: newest\nbody 66\n\n### L65: older\nbody 65\n"
    ours = base.replace("## Low\n", "## Low\n### L67: ours issue\nours body\n\n")
    theirs = base.replace("## Low\n", "## Low\n### L67: theirs issue\ntheirs body\n\n")
    repo, report = _merge(tmp_path, KI, base, ours, theirs)
    _deferred_untouched(repo, report, KI)
    assert _ki_outcome(report).endswith(" — deferred: id-renumber-collision: gated class "
                                        "(id-renumber-collision) — " + GATED_WHY), report.to_json()
    assert "### L68:" not in (repo / KI).read_text(encoding="utf-8")


# ---- P1, each arm alone --------------------------------------------------------------------------

def _renumber_hunk(ours, theirs, post=""):
    return Hunk(ours=list(ours), base=[], theirs=list(theirs), post_context=post)


PURE_OURS = ["", "### L5: ours issue", "ours body", ""]
PURE_THEIRS = ["", "### L5: theirs issue", "theirs body"]


def test_p1_the_pure_control_with_blank_edges_is_a_collision_and_resolves():
    h = _renumber_hunk(PURE_OURS, PURE_THEIRS)
    assert classify_hunk(h) == RENUMBER
    h.label = RENUMBER
    assert resolvers.resolve_id_renumber(h).renumbered == {"L5": "L6"}   # the dormant resolver
    assert resolve_hunk(h).code == "gated"                              # production


@pytest.mark.parametrize("side", ["ours", "theirs"])
@pytest.mark.parametrize("impurity", [
    ("lead", "Workaround: rerun the job."),     # first non-blank line is not an ID heading
    ("tail", "## Won't Fix"),                   # a section heading inside the block
    ("tail", "#### Repro steps"),               # a sub-heading is foreign too
    ("tail", "### L7 (BY-DESIGN): not an ID heading"),
    ("tail", "   ## Won't Fix"),                  # round 20: an ATX heading indented 3 spaces
    ("tail", "Won't Fix\n---"),                   # round 20: a setext heading
], ids=["leading-line", "section", "sub-heading", "non-id-heading", "indented-atx", "setext"])
def test_p1_an_impure_side_alone_refuses(side, impurity):
    where, line = impurity
    blocks = {"ours": list(PURE_OURS), "theirs": list(PURE_THEIRS)}
    lines = line.split("\n")
    blocks[side] = [*lines, *blocks[side]] if where == "lead" else [*blocks[side], *lines]
    assert classify_hunk(_renumber_hunk(blocks["ours"], blocks["theirs"])) != RENUMBER


@pytest.mark.parametrize("post,ok", [
    ("", True), ("### L3: older", True), ("## Resolved", True), ("# Top", True),
    ("Workaround: rerun the job.", False), ("#### Repro steps", False),
    ("- a bullet of the entry above", False), (None, False),
], ids=["eof", "id-heading", "section", "h1", "prose", "sub-heading", "bullet", "next-region"])
def test_p1_the_line_after_the_region_alone_decides(post, ok):
    assert (classify_hunk(_renumber_hunk(PURE_OURS, PURE_THEIRS, post)) == RENUMBER) is ok


def test_p1_post_context_is_the_first_non_blank_clean_line_or_none_before_another_region():
    region = "<<<<<<< ours\n### L5: a\n||||||| base\n=======\n### L5: b\n>>>>>>> theirs"
    hunks = lambda text: [s for s in parse_conflict(text).segments if isinstance(s, Hunk)]  # noqa
    assert hunks(region + "\n\n\n## Next\n")[0].post_context == "## Next"
    assert hunks(region + "\n\n")[0].post_context == ""
    assert [h.post_context for h in hunks(region + "\n\n" + region)] == [None, ""]


def test_p1_the_resolver_rechecks_purity_on_a_hand_built_hunk():
    h = Hunk(ours=["### L5: a"], base=[], theirs=["stray line", "### L5: b"], label=RENUMBER)
    with pytest.raises(CannotPlace, match="whole new entries"):
        resolvers.resolve_id_renumber(h)


# ---- P2 ------------------------------------------------------------------------------------------

RB = "# Roadmap\n\n## History\n\n- **2026-01-01** — shipped alpha"


def test_p2_theirs_continuation_line_is_not_re_parented_under_ours_bullet(tmp_path):
    """THE P2 repro (base without a final newline). Pre-fix: staged, with the revert note under
    ours' 2026-01-03 bullet."""
    ours = RB + "\n- **2026-01-03** — ours entry\n"
    theirs = RB + "\n  (alpha later reverted in PR #9)\n- **2026-01-02** — theirs entry\n"
    repo, report = _merge(tmp_path, ROADMAP, RB, ours, theirs)
    _deferred_untouched(repo, report, ROADMAP)


def test_p2_two_whole_entry_tails_still_resolve_end_to_end(tmp_path):
    ours = RB + "\n- **2026-01-03** — ours entry\n  wrapped\n"
    theirs = RB + "\n- **2026-01-02** — theirs entry\n"
    repo, report = _merge(tmp_path, ROADMAP, RB, ours, theirs)
    assert ROADMAP in report.auto_resolved, report.to_json()


SEED = "- **2026-01-01** — seed"
OURS_T = ["- **2026-01-03** — ours", "  wrapped"]
THEIRS_T = ["- **2026-01-02** — theirs"]


def _append_hunk(ours_tail, theirs_tail, post=""):
    return Hunk(ours=[SEED, *ours_tail], base=[SEED], theirs=[SEED, *theirs_tail],
                post_context=post)


@pytest.mark.parametrize("ours_tail,theirs_tail,ok", [
    (OURS_T, THEIRS_T, True),                                     # the pure control
    (OURS_T, ["  (reverted)", *THEIRS_T], False),                 # theirs starts mid-entry
    (["  (reverted)", *OURS_T], THEIRS_T, False),                 # ours starts mid-entry
    ([*OURS_T, "", "## Archive"], THEIRS_T, False),               # a section on ours' tail
    (OURS_T, ["plain prose"], False),                             # not a log entry at all
    (OURS_T, ["", ""], True),                                     # blank lines only
    (["  (reverted)"], [], True),                                 # one side added nothing
    (["  (reverted)"], ["  (reverted)"], True),                   # identical tails, emitted once
], ids=["pure", "theirs-lead", "ours-lead", "section", "prose", "blank-only", "one-sided",
        "identical"])
def test_p2_each_tail_arm_alone(ours_tail, theirs_tail, ok):
    assert (classify_hunk(_append_hunk(ours_tail, theirs_tail)) == "append-only-log") is ok


@pytest.mark.parametrize("post,ok", [
    ("", True), ("- **2025-12-31** — older", True), ("## Next", True),
    ("  continuation of the last entry", False), (None, False),
], ids=["eof", "log-entry", "section", "continuation", "next-region"])
def test_p2_the_line_after_the_region_alone_decides(post, ok):
    assert (classify_hunk(_append_hunk(OURS_T, THEIRS_T, post)) == "append-only-log") is ok


def test_p2_the_confidence_gate_and_the_resolver_each_recheck_the_predicate():
    h = _append_hunk(OURS_T, ["  (reverted)", *THEIRS_T])
    h.label = "append-only-log"
    assert resolve_hunk(h).code == "not-confident"
    with pytest.raises(CannotPlace, match="whole log entries"):
        resolvers.resolve_append_log(h)


# ---- the far edge, for the two insertion classes too --------------------------------------------

def test_edge_a_log_insertion_does_not_move_a_continuation_line_to_theirs_bullet(tmp_path):
    """Both sides insert a bullet between alpha and its wrapped line, so each side's new bullet ends
    with it. Pre-fix: staged, with the line under theirs' bullet only."""
    arch = "three-pillars-docs/architecture.md"
    base = "# A\n\n## History\n\n- **2026-01-01** — alpha\n  wrapped detail of alpha\n"
    ours = base.replace("— alpha\n", "— alpha\n- **2026-01-03** — ours\n")
    theirs = base.replace("— alpha\n", "— alpha\n- **2026-01-02** — theirs\n")
    repo, report = _merge(tmp_path, arch, base, ours, theirs)
    _deferred_untouched(repo, report, arch)


LOG_O, LOG_T = ["- **2026-01-03** — o"], ["- **2026-01-02** — t"]
DEC_O, DEC_T = ["### [tp-a] o", "**Decided**: yes"], ["### [tp-b] t"]


@pytest.mark.parametrize("ours,theirs,label,post,ok", [
    (LOG_O, LOG_T, "log-entry-insertion", "- **2026-01-01** — prior", True),
    (LOG_O, LOG_T, "log-entry-insertion", "## Older", True),
    (LOG_O, LOG_T, "log-entry-insertion", "  wrapped detail of the entry above", False),
    (LOG_O, LOG_T, "log-entry-insertion", None, False),
    (DEC_O, DEC_T, "decision-entry-insertion", "", True),
    (DEC_O, DEC_T, "decision-entry-insertion", "### [tp-c] next", True),
    (DEC_O, DEC_T, "decision-entry-insertion", "**Decided**: of the entry above", False),
    (DEC_O, DEC_T, "decision-entry-insertion", "#### a sub-heading", False),
], ids=["log-entry", "log-section", "log-continuation", "log-next-region", "dec-eof",
        "dec-entry", "dec-body-line", "dec-sub-heading"])
def test_edge_the_line_after_an_insertion_region_alone_decides(ours, theirs, label, post, ok):
    h = Hunk(ours=list(ours), base=[], theirs=list(theirs), post_context=post)
    assert (classify_hunk(h) == label) is ok


# ---- M-a: the same entry on both sides is not kept twice ----------------------------------------

def test_ma_an_entry_identical_on_both_sides_is_not_duplicated_under_a_new_id(tmp_path):
    """Pre-fix: L68, L67 and a verbatim copy of L67 as `### L69:`, staged."""
    ours = L4 + "\n### L68: ours other\nbody68\n\n### L67: X\nsame body\n"
    theirs = L4 + "\n### L67: X\nsame body\n"
    repo, report = _merge(tmp_path, KI, L4, ours, theirs)
    _deferred_untouched(repo, report, KI)
    assert "### L69:" not in (repo / KI).read_text(encoding="utf-8")


def test_ma_only_a_byte_identical_entry_refuses():
    """At the dormant resolver, called directly (the class is gated in production)."""
    twin = Hunk(ours=["### L7: X", "same body", ""], base=[], theirs=["### L7: X", "same body"],
                label=RENUMBER, post_context="")
    with pytest.raises(CannotPlace, match="byte-identical"):
        resolvers.resolve_id_renumber(twin)
    other = Hunk(ours=["### L7: X", "same body"], base=[], theirs=["### L7: X", "other body"],
                 label=RENUMBER, post_context="")
    assert resolvers.resolve_id_renumber(other).status == RESOLVED


# ---- M-e: the report says why each remaining region deferred -----------------------------------

GENERIC = "mechanical hunks pre-resolved; human must finish the remaining conflict"
GATED_WHY = "withheld from auto-resolution (classify.GATED); a human resolves it"


def _ki_outcome(report):
    (outcome,) = [o for o in report.outcomes if o["path"] == KI]
    assert outcome["action"] == "partially-resolved", outcome
    return outcome["reason"]


def test_me_a_partial_outcome_names_each_deferred_region_and_its_reason(tmp_path):
    """Pre-fix the reason was only the generic sentence — even when, as here, NO hunk resolved —
    and the per-region cause was discarded."""
    ours = L4 + "\n### L5: ours issue\nours body\n"
    theirs = L4 + "Workaround: rerun the job.\n\n### L5: theirs issue\ntheirs body\n"
    assert _ki_outcome(_merge(tmp_path, KI, L4, ours, theirs)[1]) == (
        "no conflict region could be resolved mechanically; human must resolve them — deferred: "
        "generic-prose: semantic class — needs human")


def test_me_a_mixed_file_keeps_the_pre_resolved_wording_and_adds_the_causes(tmp_path):
    """Exactly the DEFERRED regions are named: the resolved log-insertion region is not (round 20,
    pinned by equality — dropping `if r.status != RESOLVED` from `deferred_hunk_reasons` listed it
    too, as `log-entry-insertion: `, and a prefix check passed that)."""
    reason = _ki_outcome(merge_back(str(setup_collision(tmp_path, bump_preamble=True)), "master"))
    assert reason == GENERIC + " — deferred: preamble: semantic class — needs human", reason


def test_me_when_the_causes_cannot_be_re_derived_the_outcome_is_unchanged(tmp_path, monkeypatch):
    def _boom(**_kw):
        raise MergeFileError("merge-file failed")
    monkeypatch.setattr(merge_driver, "deferred_hunk_reasons", _boom)
    repo = setup_collision(tmp_path, bump_preamble=True)
    assert _ki_outcome(merge_back(str(repo), "master")) == GENERIC


if __name__ == "__main__":
    sys.exit(pytest.main([__file__]))
