"""Round 17, F3/F4/F5/F10 — the mechanical merges must read BASE, the file, and the entry.

F3   `resolve_inventory` never read `h.base`: for a shared row id it took theirs' row even when
     theirs' row WAS base, reverting an ours-only edit; and it re-added a row ours had deleted.
F4   `id-renumber-collision` ignored base and the rest of the file: (a) a retitled existing heading
     became an invented entry; (b) the new number came from the in-hunk maximum and could reuse an
     ID the file already had; (c) it renumbered across letters with no collision at all.
F5   `append-only-log` is reachable on real git output (base's last line lacking a newline), and its
     per-line cross-side dedupe dropped a body line two DISTINCT entries shared.
F10  No test put the cross-side duplicate on the two SIDES for the verbatim classes, so replacing
     `ours + theirs` with `ours | theirs` in `resolve_totality.required_counts` survived.

Each end-to-end case runs real git through `merge_driver.merge_back`. Round 20 GATED
`id-renumber-collision` (`classify.GATED`): F4's end-to-end cases now assert deferral, and its
resolver-level cases run the dormant resolver directly or with the gate lifted (`ungated_renumber`).
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import classify  # noqa: E402
import resolve_totality  # noqa: E402
import resolvers  # noqa: E402
from classify import Hunk, classify_file  # noqa: E402
from licence_oracle import lost_lines  # noqa: E402
from merge_driver import merge_back  # noqa: E402
from resolve import DEFER, RESOLVED, resolve_file, resolve_hunk  # noqa: E402
from resolve_totality import unplaceable  # noqa: E402
from test_merge_driver import commit, git, make_repo, write  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "_shared"))
from auto_safe_resolution import deferred_hunk_reasons, diff3_conflict  # noqa: E402

ROADMAP = "three-pillars-docs/product_roadmap.md"
KI = "three-pillars-docs/known_issues.md"
VISION = "three-pillars-docs/vision.md"


def _merge(tmp_path, path, base, ours, theirs):
    repo = make_repo(tmp_path)
    write(repo, path, base)
    commit(repo, "base")
    git(repo, "checkout", "-q", "-b", "design")
    write(repo, path, ours)
    commit(repo, "ours")
    git(repo, "checkout", "-q", "master")
    write(repo, path, theirs)
    commit(repo, "theirs")
    git(repo, "checkout", "-q", "design")
    return repo, merge_back(str(repo), "master")


RENUMBER = "id-renumber-collision"


@pytest.fixture
def ungated_renumber(monkeypatch):
    """Lift the production gate on `id-renumber-collision` (round 20) for ONE unit test, so
    `resolve_hunk` / `resolve_file` run the dormant resolver and its file-level refusal. Imported
    by the other modules that pin that resolver; never used on an end-to-end merge."""
    import resolve
    assert RENUMBER in resolve.GATED, "the class is gated in production (round 20)"
    monkeypatch.setattr(resolve, "GATED", resolve.GATED - {RENUMBER})


class _Result:
    def __init__(self, label, lines, renumbered=None):
        self.label, self.lines, self.renumbered = label, lines, renumbered or {}


# ---- F3: the inventory row merge is three-way ----------------------------------------------------

TABLE = "# Roadmap\n\n| ID | Design | Status |\n| --- | --- | --- |\n| D11 | alpha | Complete |\n"
ROWS = "| D12 | my-design | In progress |\n| D13 | other-design | In progress |\n"


def test_f3_an_ours_only_row_edit_is_not_reverted_by_theirs_base_row(tmp_path):
    """THE F3 repro. Ours completed D12, theirs completed D13; adjacent rows are one git conflict.
    Pre-fix the output carried D12 `In progress` again — ours' edit gone, staged, exit 0."""
    ours = TABLE + ROWS.replace("my-design | In progress", "my-design | Complete — PR #143")
    theirs = TABLE + ROWS.replace("other-design | In progress", "other-design | Complete — PR #140")
    repo, report = _merge(tmp_path, ROADMAP, TABLE + ROWS, ours, theirs)
    assert ROADMAP in report.auto_resolved, report.to_json()
    merged = (repo / ROADMAP).read_text(encoding="utf-8")
    assert "| D12 | my-design | Complete — PR #143 |" in merged, merged
    assert "| D13 | other-design | Complete — PR #140 |" in merged
    assert "In progress" not in merged


def test_f3_a_row_ours_deleted_is_not_resurrected(tmp_path):
    ours = TABLE + "| D13 | other-design | In progress |\n"                       # ours dropped D12
    theirs = TABLE + ROWS.replace("other-design | In progress", "other-design | Done")
    repo, report = _merge(tmp_path, ROADMAP, TABLE + ROWS, ours, theirs)
    assert ROADMAP not in report.auto_resolved, report.to_json()
    assert git(repo, "ls-files", "-u", "--", ROADMAP).stdout.strip(), "must stay unmerged"


@pytest.mark.parametrize("ours_row,theirs_row,base_row", [
    ("| D1 | a | OURS |", "| D1 | a | THEIRS |", "| D1 | a | base |"),   # both changed differently
    ("| D1 | a | OURS |", "| D1 | a | THEIRS |", None),                   # both added differently
])
def test_f3_a_row_both_sides_changed_differently_refuses(ours_row, theirs_row, base_row):
    h = Hunk(ours=[ours_row], base=[base_row] if base_row else [], theirs=[theirs_row],
             label="design-inventory-row-merge")
    r = resolve_hunk(h)
    assert r.status == DEFER and r.code == "cannot-place", r.reason


def test_f3_the_decision_table_outcomes_that_resolve():
    h = Hunk(ours=["| D1 | a | base |", "| D2 | b | OURS |", "| D3 | c | same |", "| D5 | e | new |"],
             base=["| D1 | a | base |", "| D2 | b | base |", "| D3 | c | base |", "| D4 | d | gone |"],
             theirs=["| D1 | a | THEIRS |", "| D2 | b | base |", "| D3 | c | same |", "| D6 | f | t |"],
             label="design-inventory-row-merge", line_after="")   # round 21: known, not a delimiter
    r = resolve_hunk(h)
    assert r.status == RESOLVED, r.reason
    assert r.lines == ["| D1 | a | THEIRS |", "| D2 | b | OURS |", "| D3 | c | same |",
                       "| D5 | e | new |", "| D6 | f | t |"]


# ---- F4: an ID renumber needs a genuine collision, and reads the file ---------------------------

LOW = "# Known Issues\n\n## Low\n"


def test_f4a_a_retitled_existing_heading_is_an_edit_not_a_collision(tmp_path):
    base = LOW + "### L62: flaky symbolic-ref tests\nTests shell out to git.\n\n### L61: x\nbody\n"
    ours = base.replace("## Low\n", "## Low\n### L63: new issue from design\nBody of L63, see L62.\n\n")
    theirs = base.replace("flaky symbolic-ref tests", "flaky symbolic-ref tests under detached HEAD")
    repo, report = _merge(tmp_path, KI, base, ours, theirs)
    assert KI not in report.auto_resolved, report.to_json()
    text = (repo / KI).read_text(encoding="utf-8")
    assert "### L64:" not in text, "no entry may be invented for the retitle"


def test_f4b_the_new_number_is_free_in_the_whole_file(tmp_path):
    mid = "### L62: existing issue\nbody 62\n\n### L57: older\nbody 57\n\n"
    ours = LOW + "### L63: ours new issue\nours body\n\n" + mid + "### L64: ours second issue\nbody\n\n"
    theirs = LOW + "### L63: master new issue\nsee L63 notes\n\n" + mid
    repo, report = _merge(tmp_path, KI, LOW + mid, ours, theirs)
    # Round 20: the class is GATED, so production renumbers nothing and the file waits for a human.
    assert KI not in report.auto_resolved, report.to_json()
    text = (repo / KI).read_text(encoding="utf-8")
    assert text.count("### L64:") == 1 and "### L65:" not in text, text
    assert "### L63: master new issue\nsee L63 notes" in text, "the base's entry keeps its number"
    # The dormant resolver, called directly on the same real region, still draws a number free in
    # the WHOLE file: pre-fix theirs became a SECOND L64.
    d = diff3_conflict(base=LOW + mid, ours=ours, theirs=theirs)
    (hunk,) = [s for s in classify_file(d.text, labels=d.labels).segments if isinstance(s, Hunk)]
    r = resolvers.resolve_id_renumber(hunk)
    assert r.renumbered == {"L63": "L65"}, r.renumbered
    assert ["### L65: master new issue", "see L65 notes"] == r.lines[-3:-1], r.lines


def test_f4c_two_different_new_ids_do_not_collide_and_are_never_renumbered_across_letters():
    text = ("<<<<<<< ours\n### M22: ours issue\nbody\n||||||| base\n=======\n"
            "### L41: theirs issue\nL41 closed\n>>>>>>> theirs")
    status, lines, results = resolve_file(text)
    assert results[0].label == "generic-prose" and status == DEFER
    assert "\n".join(lines) == text, "pre-fix theirs became M23 and its body `M23 closed`"
    same_letter = text.replace("M22", "L40")
    assert classify_file(same_letter).segments[0].label == "generic-prose"


def test_f4_a_reference_outside_the_region_or_a_taken_next_id_refuses(ungated_renumber):
    region = ("<<<<<<< ours\n### L4: ours\n||||||| base\n=======\n### L4: theirs\n>>>>>>> theirs")
    status, _l, results = resolve_file("see L4 for the history\n" + region)
    assert status == DEFER and "referenced outside" in results[0].reason, results[0].reason
    status, _l, results = resolve_file("### L3: prior\nthe L5 migration is pending\n" + region)
    assert status == DEFER and "next free ID L5" in results[0].reason, results[0].reason
    status, lines, results = resolve_file("### L3: prior\n" + region)
    assert status == RESOLVED and results[0].renumbered == {"L4": "L5"}


def test_f4_a_base_line_one_side_kept_or_both_replaced_is_not_a_collision():
    """Round 18 (R2) narrowed the second half: a base line BOTH sides replaced used to count as
    agreement, but line by line it is indistinguishable from two different rewrites of that line,
    which the merge glued together. Only an empty base is a collision now."""
    kept = Hunk(ours=["### L4: a", "shared prose"], base=["shared prose"], theirs=["### L4: b"])
    assert classify.classify_hunk(kept) != "id-renumber-collision"
    gone = Hunk(ours=["### L4: a"], base=["seed body line."], theirs=["### L4: b"])
    assert classify.classify_hunk(gone) != "id-renumber-collision"


# ---- R4 (round 18): a one-sided deletion refuses in BOTH directions ----------------------------

R4_TABLE = "# Roadmap\n\n| ID | Design | Status |\n| --- | --- | --- |\n"


def test_r4_a_non_row_table_line_theirs_deleted_and_ours_kept_is_not_resurrected(tmp_path):
    """Theirs deletes a `| TBD |` placeholder line (no design ID, so not a row), ours keeps it while
    editing the rows around it. With the non-row refusal disabled this auto-resolved with the
    placeholder resurrected."""
    base = R4_TABLE + "| D11 | a | x |\n| TBD | | | placeholder |\n| D12 | b | x |\n"
    ours = R4_TABLE + "| D11 | a | done |\n| TBD | | | placeholder |\n| D12 | b | done |\n"
    theirs = R4_TABLE + "| D11 | a | x |\n| D12 | b | x |\n| D13 | c | new |\n"
    repo, report = _merge(tmp_path, ROADMAP, base, ours, theirs)
    assert ROADMAP not in report.auto_resolved, report.to_json()
    assert git(repo, "ls-files", "-u", "--", ROADMAP).stdout.strip(), "must stay unmerged"


def test_r4_a_row_theirs_deleted_and_ours_kept_is_not_resurrected(tmp_path):
    """The mirror of `test_f3_a_row_ours_deleted_is_not_resurrected`: theirs drops D12, ours keeps
    it verbatim while completing D11 and D13."""
    base = R4_TABLE + "| D11 | a | x |\n| D12 | b | x |\n| D13 | c | x |\n"
    ours = R4_TABLE + "| D11 | a | done |\n| D12 | b | x |\n| D13 | c | done |\n"
    theirs = R4_TABLE + "| D11 | a | x |\n| D13 | c | x |\n| D14 | d | new |\n"
    repo, report = _merge(tmp_path, ROADMAP, base, ours, theirs)
    assert ROADMAP not in report.auto_resolved, report.to_json()
    assert git(repo, "ls-files", "-u", "--", ROADMAP).stdout.strip(), "must stay unmerged"
    h = Hunk(ours=["| D12 | b | x |"], base=["| D12 | b | x |"], theirs=[],
             label="design-inventory-row-merge")
    r = resolve_hunk(h)
    assert r.status == DEFER and "deleted the row of design ID D12" in r.reason, r.reason


# ---- F5: append-only-log never collapses a line of a distinct entry -----------------------------

V_BASE = "# Vision\n\n## Change log\n\n- **2026-08-01** — first principles"   # no final newline
V_OURS = V_BASE + "\n- **2026-09-01** — tightened non-goals\n  Approved-by: operator\n"
V_THEIRS = V_BASE + "\n- **2026-09-02** — added success signal\n  Approved-by: operator\n"
F5_REFUSAL = ("append-only-log: resolver cannot place a line (append-only-log) — both tails carry "
              "this line, and a line-level collapse cannot tell one entry from two: "
              "'  Approved-by: operator'")


def test_f5_append_only_log_is_reachable_and_a_shared_body_line_is_not_collapsed(tmp_path):
    """Base's last line has no final newline, so real merge-file keeps it in the region as both
    sides' shared prefix, and each tail is ONE whole log entry ending in the same continuation line.

    The PATH is asserted, not just the deferral (round 20, Q3): the previous fixture's tails began
    with `## Change log`, so round 19's tail purity relabelled the hunk `generic-prose` and this
    test held for any deferral at all — `if shared:` -> `if False:` in `resolve_append_log` passed
    it. Now the hunk is `append-only-log` and defers at exactly that shared-line refusal; with the
    refusal removed the keep-both is lossless, so the file would auto-resolve and this fails."""
    d = diff3_conflict(base=V_BASE, ours=V_OURS, theirs=V_THEIRS)
    hunks = [s for s in classify_file(d.text, labels=d.labels).segments if isinstance(s, Hunk)]
    assert [h.label for h in hunks] == ["append-only-log"], hunks
    assert deferred_hunk_reasons(base=V_BASE, ours=V_OURS, theirs=V_THEIRS) == [F5_REFUSAL]
    repo, report = _merge(tmp_path, VISION, V_BASE, V_OURS, V_THEIRS)
    assert VISION not in report.auto_resolved, report.to_json()
    (outcome,) = [o for o in report.outcomes if o["path"] == VISION]
    assert outcome["reason"].endswith(" — deferred: " + F5_REFUSAL), outcome
    assert (repo / VISION).read_text(encoding="utf-8").count("Approved-by: operator") == 2


def test_f5_the_licence_itself_now_reports_the_old_collapse():
    """Belt and braces: even a resolver that regressed to the per-line dedupe is caught, by the
    checker and by the oracle, because the licence no longer covers a non-base key when the tails
    differ."""
    h = Hunk(ours=["base", "- **a** —", "  Approved-by: operator"], base=["base"],
             theirs=["base", "- **b** —", "  Approved-by: operator"], label="append-only-log")
    old = ["base", "- **a** —", "  Approved-by: operator", "- **b** —"]
    assert unplaceable(h, "append-only-log", old) == ["  Approved-by: operator"]
    assert lost_lines(h, _Result("append-only-log", old))
    rerun = Hunk(ours=["base", "- x"], base=["base"], theirs=["base", "- x"])
    assert unplaceable(rerun, "append-only-log", ["base", "- x"]) == []


# ---- F10: exact cross-side multiplicity for the verbatim classes --------------------------------

@pytest.mark.parametrize("label,side,renumbered,output", [
    ("log-entry-insertion", ["- **2026-07-04** — entry", "  body"], None,
     ["- **2026-07-04** — entry", "  body"]),
    ("decision-entry-insertion", ["### [tp-plan] clip", "**Decided**: yes"], None,
     ["### [tp-plan] clip", "**Decided**: yes"]),
    ("id-renumber-collision", ["### L4: Bar", "body"], {"L4": "L5"}, ["### L4: Bar", "body"]),
])
def test_f10_one_copy_of_a_line_both_sides_carry_is_a_drop(label, side, renumbered, output):
    """Both sides carry the same lines; the output carries them once. For these classes the licence
    is exact multiplicity, so that is a drop — under `ours | theirs` (max) it went unreported."""
    h = Hunk(ours=list(side), base=[], theirs=list(side), label=label)
    assert sorted(unplaceable(h, label, output, renumbered)) == sorted(side)
    assert lost_lines(h, _Result(label, output, renumbered)), "the oracle agrees"


def test_classify_inv_row_is_pinned_to_ascii_digits():
    """m-M1's `[0-9]`, pinned for `classify.INV_ROW` too (only the totality copy was)."""
    assert classify.INV_ROW.pattern == resolve_totality.INV_ROW.pattern
    assert classify.INV_ROW.match("| D12 | a |") and not classify.INV_ROW.match("| D１２ | a |")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__]))
