"""Adversarial harness -- attack 4 [case 4]: squash / rebase / amend head-moves, all of which
collapse a would-be 2-parent base-sync merge into a shape RME condition 1 refuses (plan.md
Phase 4, task 4.4). Split from `test_base_sync_cert_attacks.py` per the plan's named escape
hatch to stay under the 300-line soft cap.

Same non-vacuousness posture as the sibling file: the oracle precondition is satisfied
explicitly via the case-14 seat-on-base shape before every assertion.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "fixtures"))

import base_sync_oracle  # noqa: E402
from base_sync_cert import certify_link  # noqa: E402
from base_sync_repo import (  # noqa: E402
    build_scenario,
    diverge_base_only,
    diverge_living_doc,
    make_certified_sync_merge,
)


def _seat_oracle_on_base(s, monkeypatch) -> None:
    """Case-14 shape -- see `test_base_sync_cert_attacks.py::_seat_oracle_on_base`."""
    s.git("fetch", "--quiet", "origin", s.base_ref, check=True)
    s.git("checkout", "--quiet", "-B", s.base_ref, f"origin/{s.base_ref}", check=True)
    monkeypatch.setattr(base_sync_oracle, "_oracle_code_dir", lambda: s.repo_dir)


def test_attack4a_squash_commit_fails_condition1(tmp_path, monkeypatch):
    """A real squash (`git reset --soft` + one commit) collapses what would have been a
    2-parent base-sync merge into a single-parent commit carrying the same resultant tree --
    condition 1 refuses ('expected 2 parents, found 1')."""
    s = build_scenario(tmp_path)
    diverge_living_doc(s)
    h0 = s.head()
    make_certified_sync_merge(s)
    s.git("reset", "--quiet", "--soft", h0, check=True)
    s.git("commit", "--quiet", "-m", "squash: collapsed base-sync", check=True)
    squashed = s.head()
    _seat_oracle_on_base(s, monkeypatch)

    lc = certify_link(str(s.repo_dir), h0, squashed, base_ref=s.base_ref)
    assert lc.ok is False
    assert lc.reason == "merge shape: expected 2 parents, found 1"


def test_attack4b_rebased_head_fails_condition1(tmp_path, monkeypatch):
    """A real `git rebase` replays a design-only commit onto the moved base tip -- the
    resulting head is a single-parent commit whose parent is the NEW base tip, not h0 ->
    condition 1 refuses."""
    s = build_scenario(tmp_path)
    (s.repo_dir / "design-only.txt").write_text("design work\n", encoding="utf-8")
    s.git("add", "--", "design-only.txt", check=True)
    s.git("commit", "--quiet", "-m", "design: unrelated work", check=True)
    h0 = s.head()
    diverge_base_only(s)
    s.git("fetch", "--quiet", "origin", s.base_ref, check=True)
    r = s.git("rebase", f"origin/{s.base_ref}", check=False)
    assert r.returncode == 0, r.stdout + r.stderr
    rebased = s.head()
    assert rebased != h0
    _seat_oracle_on_base(s, monkeypatch)

    lc = certify_link(str(s.repo_dir), h0, rebased, base_ref=s.base_ref)
    assert lc.ok is False
    assert lc.reason == "merge shape: expected 2 parents, found 1"


def test_attack4c_amended_head_fails_condition1(tmp_path, monkeypatch):
    """A real `git commit --amend` on what is still just a single design-side commit (never
    a merge) -- condition 1 refuses identically to the squash/rebase shapes above (the design
    contract's own note: these three head-move mechanisms are observably identical at the
    git-object level -- a non-2-parent, or p1-mismatched, commit)."""
    s = build_scenario(tmp_path)
    h0 = s.head()
    diverge_living_doc(s)
    s.git("commit", "--quiet", "--amend", "-m", "amended: design-side change (reworded)", check=True)
    amended = s.head()
    _seat_oracle_on_base(s, monkeypatch)

    lc = certify_link(str(s.repo_dir), h0, amended, base_ref=s.base_ref)
    assert lc.ok is False
    assert lc.reason == "merge shape: expected 2 parents, found 1"
