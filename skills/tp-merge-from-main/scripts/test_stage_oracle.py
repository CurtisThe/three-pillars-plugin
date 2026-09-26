"""S-J1 — THE INDEX IS THE ORACLE FOR THE TEXT PARSE.

The defect: a line of CONTENT beginning `|||||||` (a markdown table row of empty cells) is read as
the base marker, so genuine `ours` content lands in `h.base` — and every enforcement layer passes,
because `unplaceable()` deliberately excludes the base side and `embedded_marker()` never inspected
the marker FIELDS. The resolver then unions ours and theirs, the misrouted line is in neither, and
the hunk certifies RESOLVED with the line gone.

The fix is not another shape rule — thirteen rounds have shown every shape rule on this grammar is
defeasible. It is a SECOND, non-textual source for the same structure: the merge index, whose
stages 1/2/3 are the base, ours and theirs blobs, marker-free and authoritative. Every line of a
region's ours side is a line of stage 2 because `git merge-file` BUILT the region out of those
blobs — a property of production, not of appearance.
"""
import os
import subprocess
import sys
from collections import Counter

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import merge_driver  # noqa: E402
import stage_oracle  # noqa: E402
from classify import Hunk, classify_file  # noqa: E402
from merge_driver import merge_back  # noqa: E402
from resolve import RESOLVED, resolve_file, resolve_hunk  # noqa: E402
from stage_oracle import index_disagreement, parse_disagrees_with_index  # noqa: E402
from test_merge_driver import KI, PRE, commit, git, make_repo, write  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "_shared"))
from auto_safe_resolution import Diff3, diff3_conflict, resolve_conflict_bytes  # noqa: E402

# The S-J1 shape: `| D5 | second real ours row |` is OURS' content; the line above it is a table
# row, not a marker, and an unlabelled prefix scan reads it as one. The orchestrator's original repro
# used `### L4:` headings; round 17 (F4) stopped `id-renumber-collision` claiming a hunk whose base
# is non-blank, so that text now DEFERS before it resolves and could no longer exercise this gate.
# The inventory class still resolves the misroute (D5 then sits in base alone, i.e. "both sides
# deleted it"), which is exactly the RESOLVED-over-a-misroute case the gate exists for.
S_J1 = ("<<<<<<< ours\n| D4 | first |\n||||||| a table row of empty cells\n"
        "| D5 | second real ours row |\n=======\n| D4 | first |\n>>>>>>> theirs")
S_J1_MISROUTED = "| D5 | second real ours row |"
S_J1_OURS = "| D4 | first |\n||||||| a table row of empty cells\n" + S_J1_MISROUTED + "\n"
S_J1_THEIRS = "| D4 | first |\n"
S_J1_BASE = "| D0 | common |\n"


def _plain_mechanical_repo(tmp_path):
    """A repo whose branches each append a dated log entry after the same base entry — the plain
    mechanical merge (`log-entry-insertion`), so the only thing a deferral can be attributed to is
    the gate under test. (Until round 20 both branches added a colliding `### L4:`, an
    `id-renumber-collision`; that class is GATED now and defers on its own.)"""
    repo = make_repo(tmp_path)
    head = PRE.format(date="2026-05-01") + "\n### L1: base issue\nbody\n"
    write(repo, KI, head)
    commit(repo, "base")
    git(repo, "checkout", "-q", "-b", "design")
    write(repo, KI, head + "- **2026-05-02** — ours unique entry\n  ours body\n")
    commit(repo, "ours")
    git(repo, "checkout", "-q", "master")
    write(repo, KI, head + "- **2026-05-03** — theirs entry one\n")
    commit(repo, "theirs")
    git(repo, "checkout", "-q", "design")
    return repo


def test_s_j1_the_misrouted_line_is_caught_by_the_index():
    """The parse puts ours' row in `h.base`; stage 1 has never contained it, so the gate says
    so. This is the check the three text-shape layers structurally cannot make."""
    faults = parse_disagrees_with_index(base=S_J1_BASE, ours=S_J1_OURS, theirs=S_J1_THEIRS,
                                        conflict_text=S_J1)
    assert faults, "the index cross-check missed a line the parse put on the wrong side"
    assert any(S_J1_MISROUTED in f and "stage 1" in f for f in faults), faults


def test_a_faithful_parse_of_a_real_conflict_agrees_with_the_index():
    """The other direction, and the one that matters for not deferring legitimate merges: a real
    `git merge-file --diff3` text over real blobs raises NO disagreement."""
    base = "# Doc\n\n### L1: base\nbody\n"
    ours = "# Doc\n\n### L1: base\nbody\n- **2026-01-04** — ours\n  ours body\n"
    theirs = "# Doc\n\n### L1: base\nbody\n- **2026-01-05** — theirs\n  theirs body\n"
    # A RESOLVED hunk, so the cross-check really runs (an id collision defers as gated since round
    # 20, and a deferred hunk is not cross-checked, so the old fixture now passed vacuously).
    assert resolve_conflict_bytes(base=base, ours=ours, theirs=theirs)[0] == RESOLVED
    assert index_disagreement(base=base, ours=ours, theirs=theirs) is None


def test_an_absent_stage_is_fail_safe_not_skipped():
    """`None` is a MISSING stage (add/add, add/delete), not an empty one. The gate cannot check a
    parse it has no oracle for, and 'cannot check' reports a disagreement — it never returns the
    reassuring answer. `merge_driver` defers those conflicts before reaching here, so this arm is
    defence in depth; it is asserted because 'unavailable' silently reading as 'fine' is exactly
    the shape of the failures this branch keeps finding."""
    assert index_disagreement(base=None, ours="a\n", theirs="b\n") is not None
    assert index_disagreement(base="a\n", ours=None, theirs="b\n") is not None
    for stage in (1, 2, 3):
        kwargs = {"base": "a\n", "ours": "a\n", "theirs": "a\n", "conflict_text": ""}
        kwargs[{1: "base", 2: "ours", 3: "theirs"}[stage]] = None
        assert parse_disagrees_with_index(**kwargs), stage


def test_s_k3_a_misrouted_line_that_recurs_in_the_stage_is_still_caught():
    """S-K3. The gate counted SETS, so a misrouted line was invisible whenever identical text
    occurred anywhere else in the stage it landed in — and in these documents that is the routine
    case, not the exotic one: `| --- |`, blank lines and repeated table headers recur constantly.

    Here stage 1 legitimately contains `| --- | --- |` once, and the parse puts a SECOND copy on the
    base side. Under set containment the line was 'in' stage 1 and the gate said nothing; counting
    the copies says the stage has one and the parse used two."""
    base = "| --- | --- |\n| D0 | common |\n"
    ours = "| D4 | ours |\n| --- | --- |\n"
    theirs = "| D4 | ours |\n"
    conflict = ("<<<<<<< ours\n| D4 | ours |\n||||||| a table row of empty cells\n| --- | --- |\n"
                "| --- | --- |\n=======\n| D4 | ours |\n>>>>>>> theirs")
    faults = parse_disagrees_with_index(base=base, ours=ours, theirs=theirs,
                                        conflict_text=conflict)
    assert faults, "the set-based gate could not see a duplicate of a line the stage also has"
    assert any("stage 1" in f and "this hunk claims 2" in f for f in faults), faults


def test_s_k3_the_count_is_a_budget_and_a_legitimate_repeat_is_not_a_fault():
    """The other direction, which is why a hunk's lines are COUNTED against the stage (each hunk
    charged separately since S-L1) rather than each line allowed once: a side that legitimately
    carries the same line twice is fine when the stage carries it twice too. Counting must not
    turn ordinary repetition into a deferral.

    The repeat has to be IN a resolved hunk to test that (round 21): the previous fixture repeated
    `| --- |` in clean context, which no hunk claims, so capping a charge at one copy passed it."""
    body = "  same body line"
    base = "- **2026-01-01** — common\n"
    ours = f"- **2026-01-04** — ours\n{body}\n- **2026-01-06** — ours again\n{body}\n" + base
    theirs = "- **2026-01-05** — theirs\n" + base
    d = diff3_conflict(base=base, ours=ours, theirs=theirs)
    (hunk,) = [s for s in classify_file(d.text, labels=d.labels).segments if isinstance(s, Hunk)]
    assert resolve_hunk(hunk).status == RESOLVED, "a deferred hunk is not charged at all"
    assert hunk.ours.count(body) == 2 and Counter(ours.split("\n"))[body] == 2
    assert index_disagreement(base=base, ours=ours, theirs=theirs) is None


# ---- S-L1: the budget was shared across hunks, so it could invent a fault -----------------------

# TWO hunks, both RESOLVED, and stage 2 holds ONE copy of `shared entry text` — which belongs to
# hunk 2. Hunk 1's ours section wrongly claims it (the misroute); hunk 2's parse is exactly right.
O4, O7 = "- **2026-01-04** — ours entry", "- **2026-01-07** — ours other"
T4, T7 = "- **2026-01-05** — theirs entry", "- **2026-01-08** — theirs other"
S_L1_BASE = "- **2026-01-01** — common\n"
S_L1_OURS = f"{O4}\n{O7}\nshared entry text\n"
S_L1_THEIRS = f"{T4}\n{T7}\n"
# Two `log-entry-insertion` regions (round 20: they were `### L<n>:` collisions, a class now GATED,
# whose hunks defer and so would leave the gate unexercised). Empty diff3 base sections, the
# insertion shape; the clean line between them is a heading because a prose line right after a
# keep-both region could continue ours' last entry, and the class refuses that (round 19).
S_L1 = (f"<<<<<<< ours\n{O4}\nshared entry text\n||||||| base\n=======\n{T4}\n>>>>>>> theirs\n"
        "## Middle\n"
        f"<<<<<<< ours\n{O7}\nshared entry text\n||||||| base\n=======\n{T7}\n>>>>>>> theirs")


def test_s_l1_a_hunk_is_charged_against_the_whole_stage_not_a_shared_budget():
    """THE S-L1 regression, and the first test here to use more than ONE hunk — which is why this
    shipped. The count used to be one budget spent across the file in hunk order, so a MISROUTED
    hunk 1 consumed the only copy of a line and hunk 2 — parsed perfectly, legitimately carrying
    that line — was reported as the disagreement. The gate invented a fault AND named the wrong
    region, while the module docstring claimed it "can only under-report, never invent".

    Charging each hunk independently against the full stage makes a hunk's verdict a function of
    its own lines alone: no cross-hunk interaction, so no false fault and no misattribution."""
    assert parse_disagrees_with_index(base=S_L1_BASE, ours=S_L1_OURS, theirs=S_L1_THEIRS,
                                      conflict_text=S_L1) == []


def test_s_l1_a_multi_hunk_file_still_catches_the_real_misroute_and_names_the_right_hunk():
    """The other direction, since 'never invent' is worthless if the gate also stopped reporting:
    a line stage 2 has NEVER held is still a fault, in a two-hunk file, attributed to the hunk that
    claims it. `n` counts hunks, not segments — the clean `## Middle` segment between them used
    to be counted, so the number in the message pointed past the region it described."""
    ours = f"{O4}\n{O7}\n"
    conflict = S_L1.replace(f"{O4}\nshared entry text", O4).replace(
        f"{O7}\nshared entry text", f"{O7}\ninvented")
    faults = parse_disagrees_with_index(base=S_L1_BASE, ours=ours, theirs=S_L1_THEIRS,
                                        conflict_text=conflict)
    assert len(faults) == 1, faults
    assert faults[0].startswith("hunk 2 "), ("the fault names the wrong region", faults)
    assert "'invented'" in faults[0] and "stage 2" in faults[0], faults


def test_s_l1_the_joint_overrun_two_hunks_can_hide_is_asserted_not_merely_described():
    """THE COST of per-hunk charging, pinned as the arithmetic it is rather than as a docstring
    promise. `S_L1` is already that case: stage 2 holds ONE copy of `shared entry text`, and each
    of the two hunks claims one copy of it. Individually both charges fit; jointly they claim two
    copies of a line the stage has only ever held once, which no faithful pair of parses can do —
    so one of them IS a misroute, and it is reported by NEITHER. The shared budget this replaced
    could see that one total overrun; charging each hunk against the full stage cannot.

    That is the safe direction — an unseen misroute still faces the resolver's own three layers,
    where a false fault would kill a correct merge — but it is a real narrowing.

    The precondition is asserted, not assumed: without both hunks RESOLVED and both claiming the
    line, this would pass for the wrong reason and pin nothing.

    Note the tension a future round must resolve deliberately. Closing this means faulting hunk 1
    on evidence that lives OUTSIDE hunk 1, and the S-L1 regression above pins the same fixture to
    `[]` because the bug it fixed was blaming hunk 2 for hunk 1's claim. Both assertions therefore
    move together: whatever closes this must name hunk 1 and only hunk 1, at which point that test
    becomes "no fault names hunk 2" and this one is deleted."""
    hunks = [seg for seg in classify_file(S_L1).segments if isinstance(seg, Hunk)]
    line = "shared entry text"
    assert len(hunks) == 2 and all(resolve_hunk(h).status == RESOLVED for h in hunks), hunks
    assert Counter(S_L1_OURS.split("\n"))[line] == 1, "stage 2 must hold exactly one copy"
    assert [list(h.ours).count(line) for h in hunks] == [1, 1], "each hunk claims one of that one"
    assert parse_disagrees_with_index(base=S_L1_BASE, ours=S_L1_OURS, theirs=S_L1_THEIRS,
                                      conflict_text=S_L1) == []


def test_a_single_hunk_over_claiming_a_1_copy_line_still_faults_on_its_own():
    """The BOUND on that residual, and the reason it is narrow: per-hunk charging still catches
    everything one hunk can be shown to have got wrong by itself. Mutate hunk 2 so it alone claims
    TWO copies of the line stage 2 holds once — a charge that fits in no budget, joint or per-hunk
    — and the gate faults. Every fault names hunk 2: hunk 1's single claim is inside the residual
    above and stays correctly silent, which is what the `all(...)` pins."""
    faults = parse_disagrees_with_index(
        base=S_L1_BASE, ours=S_L1_OURS, theirs=S_L1_THEIRS,
        conflict_text=S_L1.replace(f"{O7}\nshared entry text",
                                   f"{O7}\nshared entry text\nshared entry text"))
    assert faults, "a hunk claiming 2 copies of a 1-copy line must still fault on its own"
    assert all(f.startswith("hunk 2 ") for f in faults), faults


def test_a_deferred_hunk_is_not_cross_checked():
    """Only a RESOLVED hunk is checked. A deferral re-emits the region VERBATIM, so a mis-cut there
    loses nothing, and deferring it a second time would only cost legitimate merges."""
    semantic = ("<<<<<<< ours\nsome prose one side rewrote\n||||||| base\nthe original\n"
                "=======\nthe other side's rewrite\n>>>>>>> theirs")
    assert parse_disagrees_with_index(base="x\n", ours="y\n", theirs="z\n",
                                      conflict_text=semantic) == []


def test_without_an_index_the_misrouted_line_is_still_lost():
    """THE RESIDUAL, pinned rather than left to be rediscovered. `resolve_file` on its own — the
    CLI, a unit test, any caller with no merge index — has only the text, and the text is exactly
    what cannot answer this question: the parse still reads the table row as a base marker, still
    routes ours' row into `h.base`, and `unplaceable` still (correctly, for a well-scanned
    hunk) ignores that side. The line is gone.

    Nothing in the driver's lane depends on this: `merge_driver` is the only caller that WRITES,
    it holds the stages, and since round 17 the byte path parses LABELLED text, where this line
    cannot be read as a marker at all (`test_parse_labels.py`). The residual is the UNLABELLED
    parse's. But the boundary of the fix is a fact about the system, so it is
    asserted instead of described. If this test starts FAILING, the residual has been closed at the
    parse level and the right response is to delete the test, not to restore the behaviour.
    """
    status, lines, _results = resolve_file(S_J1)
    assert status == RESOLVED, "the shape resolves — that is the whole problem"
    assert S_J1_MISROUTED not in lines, "if this fails, S-J1 is closed WITHOUT the index; rejoice"


def test_the_driver_defers_untouched_when_the_parse_disagrees(tmp_path, monkeypatch):
    """The gate WIRED IN: with a conflict text whose parse contradicts the stages, the driver
    defers the file, leaves git's own markers in the worktree and stages nothing.

    The conflict is substituted rather than provoked, deliberately: real labelled `--diff3` output
    cannot be mis-cut this way at all, so the substitution hands the gate labels under which the
    table row IS the base marker. It asks the question this test is for: if the parse is wrong for
    ANY reason a shape rule did not anticipate, does the driver still refuse to write?
    """
    repo = _plain_mechanical_repo(tmp_path)

    monkeypatch.setattr(stage_oracle, "diff3_conflict", lambda *, base, ours, theirs: Diff3(
        S_J1, ("ours", "a table row of empty cells", "theirs"), 1))
    report = merge_back(str(repo), "master")
    assert KI in report.deferred, report.to_json()
    assert KI not in report.auto_resolved and KI not in report.partially_resolved
    outcome = next(o for o in report.outcomes if o["path"] == KI)
    assert "disagrees with the git index" in outcome["reason"], outcome
    left = (repo / KI).read_text(encoding="utf-8")
    assert "<<<<<<<" in left, "the driver must leave git's own markers for the human"
    unmerged = git(repo, "diff", "--name-only", "--diff-filter=U").stdout
    assert KI in unmerged, "a file the gate rejected must NOT be staged"


def test_the_gate_does_not_defer_the_ordinary_mechanical_merge(tmp_path):
    """The fall-closed direction, bounded: the gate is a validation pass, not a second opinion on
    whether to resolve. The plain log-insertion merge still auto-resolves and stages."""
    repo = _plain_mechanical_repo(tmp_path)
    report = merge_back(str(repo), "master")
    assert KI in report.auto_resolved, report.to_json()
    content = (repo / KI).read_text(encoding="utf-8")
    assert "ours unique entry" in content and "theirs entry one" in content


def test_merge_driver_calls_the_gate_before_it_writes(tmp_path, monkeypatch):
    """Wiring, stated as an order: the gate runs BEFORE any `write_bytes`. A gate consulted after
    the write would defer a file it had already overwritten."""
    repo = _plain_mechanical_repo(tmp_path)
    seen = []

    def _spy(**kw):
        seen.append((sorted(kw), (repo / KI).read_text(encoding="utf-8")))
        return None

    monkeypatch.setattr(merge_driver, "index_disagreement", _spy)
    merge_back(str(repo), "master")
    assert len(seen) == 1, seen
    kwargs, on_disk_when_called = seen[0]
    assert kwargs == ["base", "ours", "theirs"], kwargs
    assert "<<<<<<<" in on_disk_when_called, "the driver had already written before consulting"
    assert "<<<<<<<" not in (repo / KI).read_text(encoding="utf-8")   # ...and wrote afterwards


def test_git_is_available():
    assert subprocess.run(["git", "--version"], capture_output=True).returncode == 0


if __name__ == "__main__":
    sys.exit(pytest.main([__file__]))
