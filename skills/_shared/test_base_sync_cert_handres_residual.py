"""M3 documented-residual certify-cases for `living_doc_carry.certify_link_carry` (task 2.5).

These assert the ACCEPTED trust boundary: `verify.py`'s zero-drop atoms are only `### L<n>:`
entries, `| D<n> | name |` rows (name-cell signature — blind to status/notes cells), and dated
log bullets. A carry-set hand-resolution that changes NON-atom content (a Current-Focus status
cell, an intra-row status cell, a parenthetical `(RESOLVED …)` heading) is invisible to
zero-drop, so it **certifies** — that fidelity rests on the operator-sanctioned Claude-merge
trust + `ci_local_stamp` + eventual human PR review, NOT on zero-drop. No new production code:
these ride the same `certify_link_carry` as task 2.3; the tests DOCUMENT the residual.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "fixtures"))

from living_doc_carry import certify_link_carry  # noqa: E402
from base_sync_repo import build_scenario, force_merge_commit  # noqa: E402

_MERGE_SCRIPTS = os.path.join(os.path.dirname(__file__), os.pardir, "tp-merge-from-main", "scripts")
if _MERGE_SCRIPTS not in sys.path:
    sys.path.insert(0, _MERGE_SCRIPTS)
import verify as _verify  # noqa: E402

_RESIDUAL = "accepted residual per operator directive; zero-drop does not cover non-atom prose (design.md §Threat model)"


def _whole_file_conflict(s, path, *, base, origin, design) -> str:
    (s.origin_dir / path).parent.mkdir(parents=True, exist_ok=True)
    (s.origin_dir / path).write_text(base, encoding="utf-8")
    s.origin_git("add", "--", path)
    s.origin_git("commit", "--quiet", "-m", "base: seed")
    s.git("fetch", "--quiet", "origin", s.base_ref)
    s.git("merge", "--quiet", "--ff-only", f"origin/{s.base_ref}")
    (s.origin_dir / path).write_text(origin, encoding="utf-8")
    s.origin_git("add", "--", path)
    s.origin_git("commit", "--quiet", "-m", "base: diverge")
    (s.repo_dir / path).write_text(design, encoding="utf-8")
    s.git("add", "--", path)
    s.git("commit", "--quiet", "-m", "design: diverge")
    return s.head()


# ---- (a) Current-Focus status-cell revert — a focus row has no [A-Z]\d+ prefix, so it is not a
#          verify.ROW atom; the Done→Seed revert is invisible to zero-drop → certifies. ----


def test_residual_current_focus_status_revert_certifies(tmp_path):
    path = "three-pillars-docs/product_roadmap.md"

    def doc(status):
        return ("# Roadmap\n\n## Current Focus\n\n| Design | Status | Notes |\n"
                "| --- | --- | --- |\n"
                f"| iteration-speed | {status} | shipped |\n\n"
                "## History\n\n- **2026-07-09** — roadmap entry\n")

    h0 = _whole_file_conflict(s := build_scenario(tmp_path), path,
                              base=doc("Seed"), origin=doc("Done"), design=doc("Blocked"))
    human = doc("Seed")   # a semantic status revert — NOT a verify atom (accepted residual)
    assert _verify.verify(doc("Blocked"), doc("Done"), human, mechanical_applied=False).ok is True
    h1 = force_merge_commit(s, {path: human})

    lc = certify_link_carry(str(s.repo_dir), h0, h1, base_ref=s.base_ref)
    assert lc.ok is True, lc.reason        # _RESIDUAL
    assert lc.conflicted_paths == (path,)


# ---- (b) same-row non-name-cell change — verify.ROW keys on the name cell only, so the
#          status/notes-cell edit is invisible to zero-drop → certifies. ----


def test_residual_same_row_status_cell_change_certifies(tmp_path):
    path = "three-pillars-docs/product_roadmap.md"

    def doc(notes):
        return ("# Roadmap\n\n## Designs\n\n| ID | Design | Status |\n"
                "| --- | --- | --- |\n"
                f"| D12 | some-design | {notes} |\n\n"
                "## History\n\n- **2026-07-09** — entry\n")

    h0 = _whole_file_conflict(s := build_scenario(tmp_path), path,
                              base=doc("Seed"), origin=doc("Done"), design=doc("InProgress"))
    human = doc("Reverted")   # the D12 name-cell survives; the status-cell edit is invisible
    assert _verify.verify(doc("InProgress"), doc("Done"), human, mechanical_applied=False).ok is True
    h1 = force_merge_commit(s, {path: human})

    lc = certify_link_carry(str(s.repo_dir), h0, h1, base_ref=s.base_ref)
    assert lc.ok is True, lc.reason        # _RESIDUAL
    assert lc.conflicted_paths == (path,)


# ---- (c) `### H6 (RESOLVED 2026-07-09):`-style heading — the parenthetical breaks verify.ENTRY's
#          `^### [A-Z]\d+:` regex, so the resolution-status transition is not an atom → certifies. ----


def test_residual_parenthetical_resolved_heading_certifies(tmp_path):
    path = "three-pillars-docs/known_issues.md"

    def doc(paren):
        return (f"# Known Issues\n\n### H6 ({paren}): the SSE leak\nsome body\n\n"
                "## History\n\n- **2026-07-09** — entry\n")

    h0 = _whole_file_conflict(s := build_scenario(tmp_path), path,
                              base=doc("OPEN"), origin=doc("OPEN — retriage"),
                              design=doc("investigating"))
    human = doc("RESOLVED 2026-07-09")   # a status transition on a NON-atom parenthetical heading
    assert _verify.verify(doc("investigating"), doc("OPEN — retriage"), human, mechanical_applied=False).ok is True
    h1 = force_merge_commit(s, {path: human})

    lc = certify_link_carry(str(s.repo_dir), h0, h1, base_ref=s.base_ref)
    assert lc.ok is True, lc.reason        # _RESIDUAL
    assert lc.conflicted_paths == (path,)
