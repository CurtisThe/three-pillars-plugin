"""Independent-oracle guard tests -- topology-builder smoke (task 3.1) + FRESH-DATA/oracle
identity (task 3.2). DISJOINT-CODE branch classification continues in
`test_base_sync_cert_oracle2.py`; the content criterion + entry wiring in
`test_base_sync_cert_oracle3.py` (split per the plan's named escape hatch, mirroring
`test_base_sync_cert_link.py`/`link2.py`/`link3.py`, to stay under the 300-line soft cap).

All fixture repos come from `fixtures/base_sync_repo.py` (LOCAL clones/forks of the real
running checkout) and `fixtures/base_sync_topologies.py` (topology-zoo builders on top of
those). `run_git` is never injected in this file except where the task explicitly calls for
an error-path simulation (fetch failure).
"""
from __future__ import annotations

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "fixtures"))

from base_sync_oracle import _oracle_code_dir, oracle_independent  # noqa: E402
from base_sync_repo import build_scenario, break_remote  # noqa: E402
from base_sync_topologies import (  # noqa: E402
    add_design_worktree,
    add_unknown_worktree,
    build_bare_hub_with_worktrees,
    checkout_detached,
    detach_seat,
    distinct_clone_at_ref,
    reparented_tree_identical_commit,
    unpushed_descendant_clone,
)


def _porcelain_paths(repo_dir) -> str:
    r = subprocess.run(["git", "-C", str(repo_dir), "worktree", "list", "--porcelain"],
                       capture_output=True, text=True, check=True)
    return r.stdout


# ============================================================
# Task 3.1: topology builder smoke -- every builder works, offline, on real git objects
# ============================================================


def test_add_design_worktree_registers_under_wt_dir(tmp_path):
    s = build_scenario(tmp_path)
    dest = add_design_worktree(s, name="feature")
    assert dest.is_dir()
    assert dest.parent.name.endswith("-wt")
    assert str(dest) in _porcelain_paths(s.repo_dir)


def test_add_unknown_worktree_is_registered_outside_wt_dir(tmp_path):
    s = build_scenario(tmp_path)
    dest = add_unknown_worktree(s, name="odd")
    assert dest.is_dir()
    assert not dest.parent.name.endswith("-wt")
    assert str(dest) in _porcelain_paths(s.repo_dir)


def test_detach_seat_leaves_head_detached_at_ref(tmp_path):
    s = build_scenario(tmp_path)
    ref = s.head()
    sha = detach_seat(s, ref)
    assert sha == ref
    r = s.git("symbolic-ref", "-q", "--short", "HEAD", check=False)
    assert r.returncode != 0   # detached: no symbolic ref


def test_distinct_clone_at_ref_is_a_separate_git_dir(tmp_path):
    s = build_scenario(tmp_path)
    ref = s.origin_head()
    dest = distinct_clone_at_ref(s, ref, tmp_path / "distinct")
    r = subprocess.run(["git", "-C", str(dest), "rev-parse", "--show-toplevel"],
                       capture_output=True, text=True, check=True)
    assert r.stdout.strip() != str(s.repo_dir)
    assert subprocess.run(["git", "-C", str(dest), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip() == ref


def test_unpushed_descendant_clone_adds_exactly_one_new_commit(tmp_path):
    s = build_scenario(tmp_path)
    ref = s.origin_head()
    dest = unpushed_descendant_clone(s, ref, tmp_path / "unpushed")
    r = subprocess.run(["git", "-C", str(dest), "rev-list", "--count", f"{ref}..HEAD"],
                       capture_output=True, text=True, check=True)
    assert r.stdout.strip() == "1"


def test_reparented_tree_identical_commit_matches_source_tree(tmp_path):
    s = build_scenario(tmp_path)
    head = s.head()
    base_tip = s.origin_head()
    crafted = reparented_tree_identical_commit(s, head, base_tip)
    src_tree = s.git("rev-parse", f"{head}^{{tree}}", check=True).stdout.strip()
    crafted_tree = s.git("rev-parse", f"{crafted}^{{tree}}", check=True).stdout.strip()
    assert crafted_tree == src_tree
    parents = s.git("rev-list", "--parents", "-n1", crafted, check=True).stdout.strip().split()[1:]
    assert parents == [base_tip]
    # orphan variant
    orphan = reparented_tree_identical_commit(s, head, None)
    orphan_parents = s.git("rev-list", "--parents", "-n1", orphan, check=True).stdout.strip().split()[1:]
    assert orphan_parents == []


def test_checkout_detached_lands_on_a_free_floating_commit(tmp_path):
    s = build_scenario(tmp_path)
    head = s.head()
    crafted = reparented_tree_identical_commit(s, head, s.origin_head())
    sha = checkout_detached(s, crafted)
    assert sha == crafted


def test_build_bare_hub_with_worktrees(tmp_path):
    s = build_scenario(tmp_path)
    hub, base_wt, design_wt = build_bare_hub_with_worktrees(s)
    is_bare = subprocess.run(["git", "-C", str(hub), "rev-parse", "--is-bare-repository"],
                             capture_output=True, text=True, check=True).stdout.strip()
    assert is_bare == "true"
    assert base_wt.is_dir() and design_wt.is_dir()
    porcelain = subprocess.run(["git", "-C", str(hub), "worktree", "list", "--porcelain"],
                               capture_output=True, text=True, check=True).stdout
    assert str(base_wt) in porcelain
    assert str(design_wt) in porcelain


# ============================================================
# Task 3.2: FRESH-DATA (mandatory fetch) + oracle identity
# ============================================================


def test_fetch_failure_refuses_with_stale_base_reason(tmp_path):
    s = build_scenario(tmp_path)
    break_remote(s)
    ok, reason = oracle_independent(str(s.repo_dir), s.head(), base_ref=s.base_ref)
    assert ok is False
    assert reason == (
        "could not fetch origin/<base> — refusing to certify against a possibly-stale base ref"
    )


def test_missing_origin_remote_refuses_with_stale_base_reason(tmp_path):
    s = build_scenario(tmp_path)
    s.git("remote", "remove", "origin", check=True)
    ok, reason = oracle_independent(str(s.repo_dir), s.head(), base_ref=s.base_ref)
    assert ok is False
    assert "could not fetch origin/<base>" in reason


def test_fetch_seam_raising_refuses_with_stale_base_reason(tmp_path):
    s = build_scenario(tmp_path)

    def _boom(args):
        raise RuntimeError("boom")
    ok, reason = oracle_independent(str(s.repo_dir), s.head(), base_ref=s.base_ref, run_git=_boom)
    assert ok is False
    assert "could not fetch origin/<base>" in reason


def test_oracle_code_dir_resolves_to_this_modules_directory():
    # Sanity check against the actual installed environment (no injection): the module's
    # own physical directory, and that directory's git toplevel resolves for real.
    code_dir = _oracle_code_dir()
    assert (code_dir / "base_sync_oracle.py").is_file()
    r = subprocess.run(["git", "-C", str(code_dir), "rev-parse", "--show-toplevel"],
                       capture_output=True, text=True, check=True)
    assert r.returncode == 0
    assert r.stdout.strip()


def test_happy_path_resolved_identity_accepts_pending_later_tasks(tmp_path):
    # Phase 3.2 scope: with identity resolved (this real worktree is inside a repo) and a
    # working fetch, the guard accepts -- steps 3/4 aren't wired yet (tasks 3.3/3.4).
    s = build_scenario(tmp_path)
    ok, reason = oracle_independent(str(s.repo_dir), s.head(), base_ref=s.base_ref)
    assert ok is True, reason
