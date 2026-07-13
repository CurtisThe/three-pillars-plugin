"""Adversarial harness -- chains + attacks 6, 7, 9 (SHIP GATE cases 6, 7, 9) against the
certified no-op-chain walk (plan.md Phase 5, tasks 5.1-5.4). Attack 10 (stale-ref after a
rewritten base and a broken remote, case 10) continues in `test_base_sync_cert_chain2.py`
(split per the plan's named escape hatch).

Task 5.1's happy 1-link/2-link carries prove the walk CAN certify under this suite's oracle
posture (the case-14 seat-on-base shape, `_seat_oracle_on_base`) -- making every refusal
below non-vacuous, not an artifact of an unsatisfiable oracle guard.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "fixtures"))

import base_sync_oracle  # noqa: E402
from base_sync_cert import ChainResult, find_certified_anchor  # noqa: E402
from base_sync_repo import (  # noqa: E402
    build_scenario,
    craft_merge_with_parents,
    diverge_base_only,
    make_certified_sync_merge,
)


def _seat_oracle_on_base(s, monkeypatch) -> None:
    """Case-14 shape -- see `test_base_sync_cert_attacks.py::_seat_oracle_on_base`."""
    s.git("fetch", "--quiet", "origin", s.base_ref, check=True)
    s.git("checkout", "--quiet", "-B", s.base_ref, f"origin/{s.base_ref}", check=True)
    monkeypatch.setattr(base_sync_oracle, "_oracle_code_dir", lambda: s.repo_dir)


# ============================================================
# Task 5.1: happy 1-link and 2-link carries (the #110 case)
# ============================================================


def test_happy_single_certified_sync_carries_one_link(tmp_path, monkeypatch):
    s = build_scenario(tmp_path)
    diverge_base_only(s, extra_line="### Za: advance 1\n")
    h0 = s.head()
    h1 = make_certified_sync_merge(s)
    _seat_oracle_on_base(s, monkeypatch)

    result = find_certified_anchor(str(s.repo_dir), h1, {h0}, base_ref=s.base_ref)
    assert result == ChainResult(True, h0, 1, "")


def test_happy_two_certified_syncs_carry_two_links(tmp_path, monkeypatch):
    s = build_scenario(tmp_path)
    diverge_base_only(s, extra_line="### Za: advance 1\n")
    h0 = s.head()
    make_certified_sync_merge(s)                 # first certified link: h0 -> h1
    diverge_base_only(s, extra_line="### Zb: advance 2\n")
    h2 = make_certified_sync_merge(s)             # second certified link: h1 -> h2

    _seat_oracle_on_base(s, monkeypatch)
    result = find_certified_anchor(str(s.repo_dir), h2, {h0}, base_ref=s.base_ref)
    assert result.certified is True
    assert result.anchor == h0
    assert result.links == 2
    assert result.reason == ""


# ============================================================
# Task 5.2: Attack 6 [case 6] -- an uncertified ORDINARY commit in the middle of the chain
# ============================================================


def test_attack6_ordinary_commit_in_middle_of_chain_refuses(tmp_path, monkeypatch):
    """certified-sync -> ordinary commit -> certified-sync: the walk from head fails at the
    MIDDLE link (the ordinary commit itself is not a 2-parent merge) with its condition
    reason; no carry."""
    s = build_scenario(tmp_path)
    diverge_base_only(s, extra_line="### Za: advance 1\n")
    h0 = s.head()
    make_certified_sync_merge(s)   # first certified link: h0 -> h1

    (s.repo_dir / "ordinary.txt").write_text("an ordinary, non-base-sync commit\n", encoding="utf-8")
    s.git("add", "--", "ordinary.txt", check=True)
    s.git("commit", "--quiet", "-m", "design: ordinary unrelated commit", check=True)

    diverge_base_only(s, extra_line="### Zb: advance 2\n")
    h3 = make_certified_sync_merge(s)   # second certified link, parented on the ORDINARY commit

    _seat_oracle_on_base(s, monkeypatch)
    result = find_certified_anchor(str(s.repo_dir), h3, {h0}, base_ref=s.base_ref)
    assert result.certified is False
    assert result.anchor is None
    assert result.reason == "merge shape: expected 2 parents, found 1"


# ============================================================
# Task 5.3: Attack 7 [case 7] -- chain over the cap
# ============================================================


def test_attack7_chain_over_cap_refuses_at_cap_plus_one(tmp_path, monkeypatch):
    """A chain of cap+1 certified links with max_links pinned at the cap -> 'chain cap N
    exceeded -- re-approve on the current head'; a cap-LENGTH chain still passes."""
    s = build_scenario(tmp_path)
    diverge_base_only(s, extra_line="### Za: advance 1\n")
    h0 = s.head()
    make_certified_sync_merge(s)
    diverge_base_only(s, extra_line="### Zb: advance 2\n")
    h2 = make_certified_sync_merge(s)
    diverge_base_only(s, extra_line="### Zc: advance 3\n")
    h3 = make_certified_sync_merge(s)

    _seat_oracle_on_base(s, monkeypatch)
    over_cap = find_certified_anchor(str(s.repo_dir), h3, {h0}, base_ref=s.base_ref, max_links=2)
    assert over_cap.certified is False
    assert over_cap.anchor is None
    assert over_cap.reason == "chain cap 2 exceeded — re-approve on the current head"

    at_cap = find_certified_anchor(str(s.repo_dir), h2, {h0}, base_ref=s.base_ref, max_links=2)
    assert at_cap.certified is True
    assert at_cap.anchor == h0
    assert at_cap.links == 2


# ============================================================
# Task 5.4: Attack 9 [case 9] -- anchor not a first-parent ancestor
# ============================================================


def test_attack9a_anchor_is_merged_in_base_commit_not_first_parent(tmp_path, monkeypatch):
    """(a) anchor == M, the base commit merged in as h1's SECOND parent -- reachable from h1,
    but the first-parent walk never visits second parents. max_links=1 caps the walk at the
    one link that exists, proving M is never found regardless of budget -> no certified
    anchor."""
    s = build_scenario(tmp_path)
    diverge_base_only(s, extra_line="### Za: advance 1\n")
    h0 = s.head()
    m = s.origin_head()
    h1 = make_certified_sync_merge(s)

    _seat_oracle_on_base(s, monkeypatch)
    result = find_certified_anchor(str(s.repo_dir), h1, {m}, base_ref=s.base_ref, max_links=1)
    assert result.certified is False
    assert result.anchor is None


def test_attack9b_off_branch_sha_never_found(tmp_path, monkeypatch):
    """(b) an off-branch sha -- never appears anywhere on the first-parent chain from head ->
    walked to its budget, never found."""
    s = build_scenario(tmp_path)
    diverge_base_only(s, extra_line="### Za: advance 1\n")
    h0 = s.head()
    h1 = make_certified_sync_merge(s)
    off_branch = craft_merge_with_parents(s, f"{h0}^{{tree}}", [], message="off-branch orphan")

    _seat_oracle_on_base(s, monkeypatch)
    result = find_certified_anchor(str(s.repo_dir), h1, {off_branch}, base_ref=s.base_ref, max_links=1)
    assert result.certified is False
    assert result.anchor is None
