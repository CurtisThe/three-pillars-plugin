"""Round 20 — `id-renumber-collision` is GATED, on every path that can turn a hunk into bytes.

Q1  The renumber's reference scope is the one conflicted file, and it renumbers THEIRS — on a
    base-sync, the base branch's entry that has already landed. Both branches file `### L67:` in
    known_issues.md and a product_roadmap.md bullet `Filed **L67** (...)`: pre-gate both files
    auto-resolved, master's entry became L68 while master's roadmap bullet still said L67.
Q2  The next free ID was drawn from this file only, so it could be an ID known_issues_resolved.md
    already spent: both file `### H8:`, master has `### H9 (RESOLVED ...)` there -> master's H8
    became H9.

The gate is `classify.GATED`, honoured by `resolve.resolve_hunk`. The paths checked here: the
producer (`merge_driver.merge_back` -> `auto_safe_resolution.resolve_conflict_bytes_detail` ->
`resolve.resolve_file`), the carry lane's clean-merge comparison
(`living_doc_carry._mechanical_resolution`) and `stage_oracle`, which cross-checks only RESOLVED
hunks. The certifier's condition 5 re-runs the same byte path and keeps no class allowlist of its
own; its real-git test is `skills/_shared/test_base_sync_cert_renumber_gate.py`.

Each end-to-end case also runs the same blobs with the gate lifted (`ungated_renumber`), which
reproduces the pre-gate alteration — so the case fails if the gate is removed.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import resolve  # noqa: E402
from classify import GATED, Hunk, classify_file  # noqa: E402
from merge_driver import merge_back  # noqa: E402
from stage_oracle import index_disagreement, parse_disagrees_with_index  # noqa: E402
from test_merge_driver import commit, git, make_repo, write  # noqa: E402
from test_resolve_three_way import KI, RENUMBER, ROADMAP, ungated_renumber  # noqa: E402,F401

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "_shared"))
from auto_safe_resolution import (  # noqa: E402
    RESOLVED, deferred_hunk_reasons, diff3_conflict, resolve_conflict_bytes,
)
from living_doc_carry import _mechanical_resolution  # noqa: E402

RESOLVED_DOC = "three-pillars-docs/known_issues_resolved.md"
GATED_REASON = (f"{RENUMBER}: gated class ({RENUMBER}) — withheld from auto-resolution "
                f"(classify.GATED); a human resolves it")

KI_BASE = "# Known Issues\n\n## Low\n\n### L66: older flake\nbody 66\n"
KI_DESIGN = KI_BASE.replace("## Low\n\n", "## Low\n\n### L67: design-side flake\ndesign body\n\n")
KI_MASTER = KI_BASE.replace("## Low\n\n", "## Low\n\n### L67: master-side flake\nmaster body\n\n")
RM_BASE = "# Roadmap\n\n## Roadmap History\n\n- **2026-09-01** — shipped alpha\n"
RM_DESIGN = RM_BASE.replace("\n\n- **2026-09-01**",
                            "\n\n- **2026-09-10** — Filed **L67** (design-side flake)\n- **2026-09-01**")
RM_MASTER = RM_BASE.replace("\n\n- **2026-09-01**",
                            "\n\n- **2026-09-09** — Filed **L67** (master-side flake)\n- **2026-09-01**")


def _sync(tmp_path, files):
    """`files` = {path: (base, design, master)}. Design is checked out and master merged in."""
    repo = make_repo(tmp_path)
    for side, n in (("base", 0), ("design", 1), ("master", 2)):
        if side == "design":
            git(repo, "checkout", "-q", "-b", "design")
        if side == "master":
            git(repo, "checkout", "-q", "master")
        for path, texts in files.items():
            write(repo, path, texts[n])
        commit(repo, side)
    git(repo, "checkout", "-q", "design")
    return repo, merge_back(str(repo), "master")


def _reason(report, path):
    (outcome,) = [o for o in report.outcomes if o["path"] == path]
    return outcome["reason"]


def test_q1_the_base_branch_entry_keeps_its_number_and_the_file_waits_for_a_human(tmp_path):
    repo, report = _sync(tmp_path, {KI: (KI_BASE, KI_DESIGN, KI_MASTER),
                                    ROADMAP: (RM_BASE, RM_DESIGN, RM_MASTER)})
    assert ROADMAP in report.auto_resolved, report.to_json()      # the log merge is unaffected
    assert KI not in report.auto_resolved and report.needs_human, report.to_json()
    assert git(repo, "ls-files", "-u", "--", KI).stdout.strip(), "known_issues.md must not be staged"
    assert _reason(report, KI).endswith(" — deferred: " + GATED_REASON), report.to_json()
    ki = (repo / KI).read_text(encoding="utf-8")
    assert "### L67: master-side flake" in ki and "### L67: design-side flake" in ki
    assert "L68" not in ki
    assert "Filed **L67** (master-side flake)" in (repo / ROADMAP).read_text(encoding="utf-8")


def test_q1_control_without_the_gate_the_same_blobs_renumber_the_landed_entry(ungated_renumber):
    """The alteration the gate withholds, reproduced on the same blobs: RESOLVED, master's entry
    moved to L68 while the roadmap bullet on master still cites L67."""
    status, merged = resolve_conflict_bytes(base=KI_BASE, ours=KI_DESIGN, theirs=KI_MASTER)
    assert status == RESOLVED and "### L68: master-side flake" in merged, merged


def test_q2_an_id_spent_in_known_issues_resolved_is_not_reused(tmp_path, monkeypatch):
    base = "# Known Issues\n\n## High\n\n### H7: older\nbody 7\n"
    design = base.replace("## High\n\n", "## High\n\n### H8: design issue\nd body\n\n")
    master = base.replace("## High\n\n", "## High\n\n### H8: master issue\nm body\n\n")
    resolved = "# Resolved\n\n### H6 (RESOLVED 2026-08-01): old\nbody\n"
    resolved_master = resolved + "\n### H9 (RESOLVED 2026-09-01): fixed on master\nbody\n"
    repo, report = _sync(tmp_path, {KI: (base, design, master),
                                    RESOLVED_DOC: (resolved, resolved, resolved_master)})
    assert KI not in report.auto_resolved and report.needs_human, report.to_json()
    assert git(repo, "ls-files", "-u", "--", KI).stdout.strip()
    assert "H9" not in (repo / KI).read_text(encoding="utf-8")
    monkeypatch.setattr(resolve, "GATED", GATED - {RENUMBER})           # the pre-gate control
    status, merged = resolve_conflict_bytes(base=base, ours=design, theirs=master)
    assert status == RESOLVED and "### H9: master issue" in merged, merged


# ---- every other path that resolves a hunk ------------------------------------------------------

def test_the_carry_lanes_clean_merge_comparison_sees_no_mechanical_merge():
    """`_mechanical_resolution` is what the relaxed certifier byte-compares a committed blob to. A
    renumber collision gives it nothing: a committed renumber can only ever be a hand-resolution."""
    assert _mechanical_resolution(KI_BASE, KI_DESIGN, KI_MASTER) is None


def test_stage_oracle_resolves_the_hunk_the_same_way_and_so_checks_nothing(monkeypatch):
    d = diff3_conflict(base=KI_BASE, ours=KI_DESIGN, theirs=KI_MASTER)
    hunks = [s for s in classify_file(d.text, labels=d.labels).segments if isinstance(s, Hunk)]
    assert [h.label for h in hunks] == [RENUMBER]
    assert [resolve.resolve_hunk(h).code for h in hunks] == ["gated"]
    # Only RESOLVED hunks are cross-checked, so a gated one cannot be vouched for: a text that
    # claims a line stage 2 never held is silent while gated, and faults once the gate is lifted.
    lie = d.text.replace("design body", "a line stage 2 never held")
    kw = dict(base=KI_BASE, ours=KI_DESIGN, theirs=KI_MASTER, conflict_text=lie, labels=d.labels)
    assert parse_disagrees_with_index(**kw) == []
    assert index_disagreement(base=KI_BASE, ours=KI_DESIGN, theirs=KI_MASTER) is None
    monkeypatch.setattr(resolve, "GATED", GATED - {RENUMBER})
    assert parse_disagrees_with_index(**kw), "control: the ungated hunk is cross-checked"


def test_the_deferral_names_the_gate_on_the_byte_path():
    assert deferred_hunk_reasons(base=KI_BASE, ours=KI_DESIGN, theirs=KI_MASTER) == [GATED_REASON]
    assert resolve_conflict_bytes(base=KI_BASE, ours=KI_DESIGN, theirs=KI_MASTER)[0] != RESOLVED


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__]))
