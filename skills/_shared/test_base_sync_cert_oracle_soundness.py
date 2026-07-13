"""Oracle-soundness ship-gate fixtures (design-audit round-2/round-3 cases 11-16 + the
seat-locally-ahead over-block, task 3.7). All asserted on `oracle_independent` directly
(the full FRESH-DATA -> oracle-identity -> DISJOINT-CODE -> content-criterion assembly), via
`monkeypatch.setattr(base_sync_oracle, "_oracle_code_dir", ...)` -- the sole test seam for
varying the oracle's own physical checkout location (production always resolves to wherever
`base_sync_oracle.py` is actually loaded from; see that module's docstring).

Any failure here is a SOUNDNESS BUG in the guard, never in the test -- fix the guard.

Tasks 3.5 (fixtures 11-13, must-refuse) + 3.6 (fixtures 15-16 must-refuse, 14 must-accept)
continue below; task 3.7 (seat-locally-ahead, documented fail-closed over-block) closes the
file.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "fixtures"))

import base_sync_oracle  # noqa: E402
from base_sync_oracle import _CONTENT_REFUSE, oracle_independent  # noqa: E402
from base_sync_repo import build_scenario, diverge_base_only, make_certified_sync_merge  # noqa: E402
from base_sync_topologies import (  # noqa: E402
    add_unknown_worktree,
    checkout_detached,
    distinct_clone_at_ref,
    reparented_tree_identical_commit,
    unpushed_descendant_clone,
)


# ============================================================
# Task 3.5 -- fixtures 11-13 (must-refuse)
# ============================================================


def test_fixture11_distinct_clone_at_head_oid_refuses(tmp_path, monkeypatch):
    """A fresh clone of the fixture ORIGIN checked out at the exact head_oid under
    verification, used as the oracle code dir: a branch-side commit, never an ancestor of
    base_tip -> refuse."""
    s = build_scenario(tmp_path)
    diverge_base_only(s)
    head_oid = make_certified_sync_merge(s)
    # head_oid is a merge commit on the DESIGN side -- clone from repo_dir (not origin_dir,
    # which never receives this scenario's pushes) so the ref actually resolves.
    clone = distinct_clone_at_ref(s, head_oid, tmp_path / "fixture11-clone", source=s.repo_dir)
    monkeypatch.setattr(base_sync_oracle, "_oracle_code_dir", lambda: clone)

    ok, reason = oracle_independent(str(s.repo_dir), head_oid, base_ref=s.base_ref)
    assert ok is False
    assert reason == _CONTENT_REFUSE


def test_fixture12_unknown_worktree_refuses(tmp_path, monkeypatch):
    """A same-repo registered worktree at a non-`*-wt/`, non-primary path (mirrors
    `test_seat_resolve.sh` fixture 7) -> refuse on the primary-worktree-index check."""
    s = build_scenario(tmp_path)
    odd = add_unknown_worktree(s, name="odd")
    monkeypatch.setattr(base_sync_oracle, "_oracle_code_dir", lambda: odd)

    ok, reason = oracle_independent(str(s.repo_dir), s.head(), base_ref=s.base_ref)
    assert ok is False
    assert reason == (
        "oracle checkout is not the primary worktree — unknown-worktree topology, no carry"
    )


def test_fixture13_seat_detached_at_chain_ancestor_refuses(tmp_path, monkeypatch):
    """The seat detached at an ancestor of head_oid INSIDE the certified chain -- a
    branch-side merge commit, never an ancestor of the freshly-fetched base tip -> refuse."""
    s = build_scenario(tmp_path)
    diverge_base_only(s)
    h0 = make_certified_sync_merge(s)   # first certified link, anchored on the base line
    diverge_base_only(s)
    h1 = make_certified_sync_merge(s)   # head_oid under verification: further along the chain
    checkout_detached(s, h0)            # the seat mis-detached at the ancestor merge h0
    monkeypatch.setattr(base_sync_oracle, "_oracle_code_dir", lambda: s.repo_dir)

    ok, reason = oracle_independent(str(s.repo_dir), h1, base_ref=s.base_ref)
    assert ok is False
    assert reason == _CONTENT_REFUSE


# ============================================================
# Task 3.6 -- fixtures 15-16 (must-refuse) + 14 (must-accept)
# ============================================================


def test_fixture15a_tree_identical_reparented_onto_base_tip_refuses(tmp_path, monkeypatch):
    """`git commit-tree <head_oid>^{tree} -p <base_tip>` -- tree byte-identical to
    head_oid's, reparented onto the base tip -- checked out as the oracle. Not an ancestor
    of base_tip (base_tip is ITS parent, the wrong direction) -> refuse. This is the
    attempt-3 default-permit hole's pin."""
    s = build_scenario(tmp_path)
    diverge_base_only(s)
    head_oid = make_certified_sync_merge(s)
    base_tip = s.git("rev-parse", f"origin/{s.base_ref}^{{commit}}", check=True).stdout.strip()
    crafted = reparented_tree_identical_commit(s, head_oid, base_tip)
    checkout_detached(s, crafted)
    monkeypatch.setattr(base_sync_oracle, "_oracle_code_dir", lambda: s.repo_dir)

    ok, reason = oracle_independent(str(s.repo_dir), head_oid, base_ref=s.base_ref)
    assert ok is False
    assert reason == _CONTENT_REFUSE


def test_fixture15b_tree_identical_orphan_refuses(tmp_path, monkeypatch):
    """The orphan variant: `git commit-tree <head_oid>^{tree}` with NO parent at all --
    still refuses (no ancestry relationship to base_tip whatsoever)."""
    s = build_scenario(tmp_path)
    diverge_base_only(s)
    head_oid = make_certified_sync_merge(s)
    orphan = reparented_tree_identical_commit(s, head_oid, None, message="tree-identical-orphan")
    checkout_detached(s, orphan)
    monkeypatch.setattr(base_sync_oracle, "_oracle_code_dir", lambda: s.repo_dir)

    ok, reason = oracle_independent(str(s.repo_dir), head_oid, base_ref=s.base_ref)
    assert ok is False
    assert reason == _CONTENT_REFUSE


def test_fixture16_unpushed_descendant_refuses(tmp_path, monkeypatch):
    """A clone of the design side at head_oid PLUS one new local commit, never pushed
    anywhere, used as the oracle: a descendant of head_oid is never an ancestor of
    base_tip -> refuse."""
    s = build_scenario(tmp_path)
    diverge_base_only(s)
    head_oid = make_certified_sync_merge(s)
    clone = unpushed_descendant_clone(s, head_oid, tmp_path / "fixture16-clone", source=s.repo_dir)
    monkeypatch.setattr(base_sync_oracle, "_oracle_code_dir", lambda: clone)

    ok, reason = oracle_independent(str(s.repo_dir), head_oid, base_ref=s.base_ref)
    assert ok is False
    assert reason == _CONTENT_REFUSE


def test_fixture14_legitimate_seat_on_base_accepts(tmp_path, monkeypatch):
    """The over-block regression guard: the seat checked out ON origin/<base> (the normal
    post-base-sync topology) -- its HEAD IS the fresh base tip -> MUST ACCEPT."""
    s = build_scenario(tmp_path)
    diverge_base_only(s)
    head_oid = make_certified_sync_merge(s)
    s.git("fetch", "origin", s.base_ref, check=True)
    s.git("checkout", "--quiet", "-B", s.base_ref, f"origin/{s.base_ref}", check=True)
    monkeypatch.setattr(base_sync_oracle, "_oracle_code_dir", lambda: s.repo_dir)

    ok, reason = oracle_independent(str(s.repo_dir), head_oid, base_ref=s.base_ref)
    assert ok is True, reason


# ============================================================
# Task 3.7 -- seat-locally-ahead over-block (documented fail-closed, not a bug)
# ============================================================


def test_task37_seat_locally_ahead_of_origin_refuses_fail_closed(tmp_path, monkeypatch):
    """The seat carries local commits ahead of the freshly-fetched base_tip -- e.g.
    topology.md's orchestration-paper-trail allowance (unpushed `tp-designs/orchestration/`
    commits on master, not yet pushed to `origin`). `oracle_head` (the seat's own advanced
    HEAD) is a DESCENDANT of `base_tip`, never an ancestor-or-equal -> `merge-base
    --is-ancestor` returns rc 1 -> fail-closed refuse.

    Operational consequence (accepted, documented, NOT a bug): carry is unavailable from
    this seat state until either (a) the seat's local base-branch advance is pushed to
    `origin` (so the next fetch picks it up as part of `base_tip`), or (b) the review is
    re-approved on the current head. This over-blocks a legitimate-but-unpushed seat state
    in favor of never certifying against content the fetched base tip hasn't seen -- the
    same fail-closed posture the whole guard is built on (staleness policy, decision 16)."""
    s = build_scenario(tmp_path)
    head_oid = s.head()   # arbitrary head under verification; unused by the guard itself
    s.git("fetch", "origin", s.base_ref, check=True)
    s.git("checkout", "--quiet", "-B", s.base_ref, f"origin/{s.base_ref}", check=True)
    # one local, unpushed commit on the seat's own base branch
    (s.repo_dir / "local-only.txt").write_text("local ahead\n", encoding="utf-8")
    s.git("add", "--", "local-only.txt", check=True)
    s.git("commit", "--quiet", "-m", "seat: local unpushed advance", check=True)
    monkeypatch.setattr(base_sync_oracle, "_oracle_code_dir", lambda: s.repo_dir)

    ok, reason = oracle_independent(str(s.repo_dir), head_oid, base_ref=s.base_ref)
    assert ok is False
    assert reason == _CONTENT_REFUSE
