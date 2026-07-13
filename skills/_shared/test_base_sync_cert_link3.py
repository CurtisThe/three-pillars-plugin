"""Real-git + injected-seam tests for the chain walk (task 2.6:
`find_certified_anchor`/`certified_noop_chain`) and the live-git-binary smoke test (task 2.7,
SHIP GATE -- must RUN, not skip, on this machine's git 2.43). Split from
`test_base_sync_cert_link2.py` per the plan's named escape hatch.
"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "fixtures"))

from base_sync_cert import (  # noqa: E402
    _oracle_guard,
    certified_noop_chain,
    find_certified_anchor,
    git_version_ok,
)
from base_sync_oracle import _make_default_git, oracle_independent  # noqa: E402
from base_sync_repo import (  # noqa: E402
    build_scenario,
    diverge_base_only,
    diverge_living_doc,
    make_certified_sync_merge,
    shallow_clone,
)


def test_oracle_guard_is_wired_to_the_real_guard():
    """Task 3.4 landed: this module's oracle-guard slot is the real `oracle_independent`
    (base_sync_oracle.py), not the Phase-2 pass-through stub. Every fixture-repo test in
    this file remains oracle-independent by CONSTRUCTION (per `base_sync_repo.py`'s own
    docstring: every scenario is a local clone/fork of the real running checkout, so this
    checkout's HEAD is always an ancestor-or-equal of the fixture's `origin/<base>` tip) --
    not because the guard is stubbed out."""
    assert _oracle_guard is oracle_independent


# ============================================================
# Task 2.6(a): links==0 pre-walk short-circuit
# ============================================================


def test_links_zero_preval_short_circuit(tmp_path):
    s = build_scenario(tmp_path)
    head = s.head()
    result = find_certified_anchor(str(s.repo_dir), head, {head}, base_ref=s.base_ref)
    assert result == find_certified_anchor(str(s.repo_dir), head, {head}, base_ref=s.base_ref)
    assert result.certified is True
    assert result.anchor == head
    assert result.links == 0
    assert result.reason == ""


def test_pre_walk_short_circuit_is_case_insensitive(tmp_path):
    s = build_scenario(tmp_path)
    head = s.head()
    result = find_certified_anchor(str(s.repo_dir), head.upper(), {head.lower()}, base_ref=s.base_ref)
    assert result.certified is True
    assert result.links == 0


# ============================================================
# Task 2.6(b): entry-guard order
# ============================================================


def test_git_version_below_floor_fails_entry_guard(tmp_path):
    s = build_scenario(tmp_path)
    head = s.head()

    def old_git(args):
        if args[0] == "version":
            return (0, "git version 2.30.0\n", "")
        return (0, "", "")

    result = find_certified_anchor(str(s.repo_dir), head, set(), base_ref=s.base_ref, run_git=old_git)
    assert result.certified is False
    assert result.reason == "git < 2.38 — carry unavailable"


def test_shallow_repo_fails_entry_guard_with_distinct_reason(tmp_path):
    s = build_scenario(tmp_path)
    shallow_dir = shallow_clone(s, tmp_path / "shallow")
    head = subprocess.run(["git", "-C", str(shallow_dir), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()
    result = find_certified_anchor(str(shallow_dir), head, set(), base_ref=s.base_ref)
    assert result.certified is False
    assert result.reason == "shallow/incomplete history — cannot walk chain; carry requires a full clone"


def test_head_commit_unavailable_fails_entry_guard(tmp_path):
    s = build_scenario(tmp_path)
    bogus_head = "f" * 40
    result = find_certified_anchor(str(s.repo_dir), bogus_head, set(), base_ref=s.base_ref)
    assert result.certified is False
    assert result.reason == "head commit unavailable — fetch origin"


# ============================================================
# Task 2.6(c): walk shape
# ============================================================


def test_cap_hit_at_zero_links(tmp_path):
    s = build_scenario(tmp_path)
    head = s.head()
    result = find_certified_anchor(str(s.repo_dir), head, set(), base_ref=s.base_ref, max_links=0)
    assert result.certified is False
    assert result.links == 0
    assert result.reason == "chain cap 0 exceeded — re-approve on the current head"


def test_history_incomplete_on_rev_list_failure(tmp_path):
    s = build_scenario(tmp_path)
    head = s.head()
    real_git = _make_default_git(str(s.repo_dir))

    def fake_git(args):
        # Everything the entry guards + the now-real oracle guard need (version, shallow
        # probe, fetch, worktree list, merge-base, cat-file -e) is delegated to the real
        # git backend against this fixture's real objects -- only the WALK's first
        # rev-list call is faked to fail, isolating "history incomplete" from the guard.
        if args[0] == "rev-list":
            return (1, "", "")
        return real_git(args)

    result = find_certified_anchor(str(s.repo_dir), head, set(), base_ref=s.base_ref, run_git=fake_git)
    assert result.certified is False
    assert result.links == 0
    assert result.reason == "history incomplete"


def test_in_walk_match_fires_at_links_one(tmp_path):
    s = build_scenario(tmp_path)
    diverge_living_doc(s)
    h0 = s.head()
    h1 = make_certified_sync_merge(s)
    result = find_certified_anchor(str(s.repo_dir), h1, {h0}, base_ref=s.base_ref)
    assert result.certified is True
    assert result.anchor == h0
    assert result.links == 1


def test_uncertified_first_parent_refuses_with_link_reason(tmp_path):
    s = build_scenario(tmp_path)
    h0 = s.head()   # h0 has no parent that is a certified sync merge of anything
    result = find_certified_anchor(str(s.repo_dir), h0, {"0" * 40}, base_ref=s.base_ref, max_links=5)
    assert result.certified is False
    assert result.reason != ""


# ============================================================
# Task 2.6(d): certified_noop_chain ≡ find_certified_anchor(head, {anchor})
# ============================================================


def test_certified_noop_chain_matches_find_certified_anchor(tmp_path):
    s = build_scenario(tmp_path)
    diverge_living_doc(s)
    h0 = s.head()
    h1 = make_certified_sync_merge(s)
    a = certified_noop_chain(str(s.repo_dir), h0, h1, base_ref=s.base_ref)
    b = find_certified_anchor(str(s.repo_dir), h1, {h0}, base_ref=s.base_ref)
    assert a == b


# ============================================================
# Task 2.7: live-git-binary smoke test (SHIP GATE -- must RUN, not skip, on git 2.43)
# ============================================================


@pytest.mark.skipif(not git_version_ok(),
                    reason="SHIP GATE (task 2.7): git < 2.38 -- live merge-tree smoke cannot run")
def test_live_git_smoke_clean_merge(tmp_path):
    s = build_scenario(tmp_path)
    diverge_base_only(s)
    h0 = s.head()
    s.git("fetch", "--quiet", "origin", s.base_ref, check=True)
    p2 = s.origin_head()
    r = subprocess.run(["git", "-C", str(s.repo_dir), "merge-tree", "--write-tree", "-z",
                        "--no-messages", h0, p2], capture_output=True)
    assert r.returncode == 0
    assert r.stdout.endswith(b"\x00")
    assert len(r.stdout) == 41   # 40-hex tree oid + one NUL, no conflict stanzas


@pytest.mark.skipif(not git_version_ok(),
                    reason="SHIP GATE (task 2.7): git < 2.38 -- live merge-tree smoke cannot run")
def test_live_git_smoke_conflicted_merge(tmp_path):
    s = build_scenario(tmp_path)
    diverge_living_doc(s)
    h0 = s.head()
    s.git("fetch", "--quiet", "origin", s.base_ref, check=True)
    p2 = s.origin_head()
    r = subprocess.run(["git", "-C", str(s.repo_dir), "merge-tree", "--write-tree", "-z",
                        "--no-messages", h0, p2], capture_output=True)
    assert r.returncode == 1
    assert r.stdout.count(b"\x00") == 4   # tree + 3 conflict stanzas (stages 1/2/3)
