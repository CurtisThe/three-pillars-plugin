"""Independent-oracle guard tests -- DISJOINT-CODE branch classification (task 3.3).
Continues `test_base_sync_cert_oracle.py` (topology smoke + FRESH-DATA/identity); the
content criterion + entry wiring continue in `test_base_sync_cert_oracle3.py` (split per the
plan's named escape hatch to stay under the 300-line soft cap).

Exercises `_classify_disjoint_code` directly against REAL fixture topologies (real
`seat_resolve.sh` subprocess, zero edits to it); `run_cmd`/`run_git` are injected only for
the error/indeterminate paths, per the plan.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "fixtures"))

from base_sync_oracle import (  # noqa: E402
    _GENERIC_REFUSE,
    _UNKNOWN_WORKTREE_REFUSE,
    _classify_disjoint_code,
    _make_default_git,
    _real_run_cmd,
)
from base_sync_repo import build_scenario  # noqa: E402
from base_sync_topologies import (  # noqa: E402
    add_design_worktree,
    add_unknown_worktree,
    build_bare_hub_with_worktrees,
)


def _classify(repo_root, oracle_root, *, run_git=None, run_cmd=None):
    git = run_git or _make_default_git(repo_root)
    cmd = run_cmd or _real_run_cmd
    return _classify_disjoint_code(repo_root, str(oracle_root), run_git=git, run_cmd=cmd)


# ============================================================
# distinct-repo acceptance
# ============================================================


def test_distinct_repo_no_matching_worktree_continues_to_step4(tmp_path):
    s1 = tmp_path / "s1"
    s1.mkdir()
    s = build_scenario(s1)
    s2 = tmp_path / "s2"
    s2.mkdir()
    other = build_scenario(s2)
    ok, reason = _classify(s.repo_dir, other.repo_dir)
    assert (ok, reason) == (True, "")


# ============================================================
# confirmed-seat: primary NOT bare
# ============================================================


def test_confirmed_seat_self_is_primary_accepts(tmp_path):
    s = build_scenario(tmp_path)
    ok, reason = _classify(s.repo_dir, s.repo_dir)
    assert (ok, reason) == (True, "")


def test_code_root_inside_design_worktree_refuses(tmp_path):
    s = build_scenario(tmp_path)
    wt = add_design_worktree(s, name="feature")
    ok, reason = _classify(s.repo_dir, wt)
    assert ok is False
    assert reason == _GENERIC_REFUSE   # --am-i-seat exit 1 (path-shape check fails)


def test_unknown_worktree_passes_am_i_seat_but_fails_primary_index(tmp_path):
    s = build_scenario(tmp_path)
    odd = add_unknown_worktree(s, name="odd")
    ok, reason = _classify(s.repo_dir, odd)
    assert ok is False
    assert reason == _UNKNOWN_WORKTREE_REFUSE


# ============================================================
# confirmed-seat: bare-primary carve-out
# ============================================================


def test_bare_hub_carve_out_standing_base_worktree_accepts(tmp_path):
    s = build_scenario(tmp_path)
    hub, base_wt, design_wt = build_bare_hub_with_worktrees(s)
    ok, reason = _classify(design_wt, base_wt)
    assert (ok, reason) == (True, "")


def test_bare_hub_carve_out_wrong_worktree_refuses(tmp_path):
    # The design worktree itself is NOT the standing base worktree -- state resolves for
    # real but seat_path never matches the design worktree's own canon.
    s = build_scenario(tmp_path)
    hub, base_wt, design_wt = build_bare_hub_with_worktrees(s)
    ok, reason = _classify(design_wt, design_wt)
    assert ok is False
    assert reason == _GENERIC_REFUSE


def test_bare_hub_carve_out_json_error_refuses(tmp_path):
    s = build_scenario(tmp_path)
    hub, base_wt, design_wt = build_bare_hub_with_worktrees(s)

    def _bad_json(argv):
        return (0, "not json", "")
    ok, reason = _classify(design_wt, base_wt, run_cmd=_bad_json)
    assert (ok, reason) == (False, _GENERIC_REFUSE)


def test_bare_hub_carve_out_wrong_state_refuses(tmp_path):
    s = build_scenario(tmp_path)
    hub, base_wt, design_wt = build_bare_hub_with_worktrees(s)

    def _wrong_state(argv):
        return (0, '{"state":"unknown-worktree","seat_path":null,"repair_hint":null}', "")
    ok, reason = _classify(design_wt, base_wt, run_cmd=_wrong_state)
    assert (ok, reason) == (False, _GENERIC_REFUSE)


def test_bare_hub_carve_out_run_cmd_nonzero_refuses(tmp_path):
    s = build_scenario(tmp_path)
    hub, base_wt, design_wt = build_bare_hub_with_worktrees(s)

    def _nonzero(argv):
        return (2, "", "boom")
    ok, reason = _classify(design_wt, base_wt, run_cmd=_nonzero)
    assert (ok, reason) == (False, _GENERIC_REFUSE)


def test_bare_hub_carve_out_run_cmd_raising_refuses(tmp_path):
    s = build_scenario(tmp_path)
    hub, base_wt, design_wt = build_bare_hub_with_worktrees(s)

    def _boom(argv):
        raise RuntimeError("boom")
    ok, reason = _classify(design_wt, base_wt, run_cmd=_boom)
    assert (ok, reason) == (False, _GENERIC_REFUSE)


# ============================================================
# generic refusal triggers: parse failure / subprocess error
# ============================================================


def test_worktree_list_nonzero_rc_refuses(tmp_path):
    s = build_scenario(tmp_path)

    def _bad_git(args):
        return (1, "", "git error")
    ok, reason = _classify(s.repo_dir, s.repo_dir, run_git=_bad_git)
    assert (ok, reason) == (False, _GENERIC_REFUSE)


def test_worktree_list_empty_output_refuses(tmp_path):
    s = build_scenario(tmp_path)

    def _empty(args):
        return (0, "", "")
    ok, reason = _classify(s.repo_dir, s.repo_dir, run_git=_empty)
    assert (ok, reason) == (False, _GENERIC_REFUSE)


def test_worktree_list_run_git_raising_refuses(tmp_path):
    s = build_scenario(tmp_path)

    def _boom(args):
        raise RuntimeError("boom")
    ok, reason = _classify(s.repo_dir, s.repo_dir, run_git=_boom)
    assert (ok, reason) == (False, _GENERIC_REFUSE)


def test_am_i_seat_exit1_refuses(tmp_path):
    s = build_scenario(tmp_path)

    def _not_seat(argv):
        return (1, "", "")
    ok, reason = _classify(s.repo_dir, s.repo_dir, run_cmd=_not_seat)
    assert (ok, reason) == (False, _GENERIC_REFUSE)


def test_am_i_seat_run_cmd_raising_refuses(tmp_path):
    s = build_scenario(tmp_path)

    def _boom(argv):
        raise RuntimeError("boom")
    ok, reason = _classify(s.repo_dir, s.repo_dir, run_cmd=_boom)
    assert (ok, reason) == (False, _GENERIC_REFUSE)
