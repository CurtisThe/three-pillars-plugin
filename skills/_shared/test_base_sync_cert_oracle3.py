"""Independent-oracle guard tests -- the universal content criterion + entry wiring
(task 3.4). Continues `test_base_sync_cert_oracle.py` (topology smoke + FRESH-DATA/
identity) and `test_base_sync_cert_oracle2.py` (DISJOINT-CODE classification).

Exercises `_content_whitelist` directly against real fixture git objects, plus the
once-per-walk fetch-count pin (entry wiring) via `find_certified_anchor`.
"""
from __future__ import annotations

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "fixtures"))

from base_sync_cert import find_certified_anchor  # noqa: E402
from base_sync_oracle import _CONTENT_REFUSE, _content_whitelist, _make_default_git  # noqa: E402
from base_sync_repo import build_scenario, diverge_base_only, diverge_living_doc, make_certified_sync_merge  # noqa: E402


# ============================================================
# _content_whitelist: the ancestor-of-base_tip positive whitelist
# ============================================================


def test_whitelist_accepts_when_oracle_head_equals_base_tip(tmp_path):
    s = build_scenario(tmp_path)
    git = _make_default_git(str(s.repo_dir))
    ok, reason = _content_whitelist(s.repo_dir, str(s.repo_dir), s.origin_head(), run_git=git)
    assert (ok, reason) == (True, "")


def test_whitelist_accepts_when_oracle_head_is_a_strict_ancestor(tmp_path):
    s = build_scenario(tmp_path)
    diverge_base_only(s)   # advances ONLY origin's base_ref
    s.git("fetch", "origin", s.base_ref, check=True)
    base_tip = s.git("rev-parse", f"origin/{s.base_ref}^{{commit}}", check=True).stdout.strip()
    git = _make_default_git(str(s.repo_dir))
    ok, reason = _content_whitelist(s.repo_dir, str(s.repo_dir), base_tip, run_git=git)
    assert (ok, reason) == (True, "")


def test_whitelist_refuses_sibling_divergence(tmp_path):
    s = build_scenario(tmp_path)
    diverge_living_doc(s)   # BOTH sides gain a new, distinct commit -- a sibling, not an ancestor
    s.git("fetch", "origin", s.base_ref, check=True)
    base_tip = s.git("rev-parse", f"origin/{s.base_ref}^{{commit}}", check=True).stdout.strip()
    git = _make_default_git(str(s.repo_dir))
    ok, reason = _content_whitelist(s.repo_dir, str(s.repo_dir), base_tip, run_git=git)
    assert (ok, reason) == (False, _CONTENT_REFUSE)


def test_whitelist_refuses_unrelated_origin_oracle(tmp_path):
    s = build_scenario(tmp_path)
    base_tip = s.origin_head()
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=unrelated, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.invalid"], cwd=unrelated, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=unrelated, check=True)
    (unrelated / "f.txt").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "f.txt"], cwd=unrelated, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "unrelated"], cwd=unrelated, check=True)
    git = _make_default_git(str(s.repo_dir))
    ok, reason = _content_whitelist(s.repo_dir, str(unrelated), base_tip, run_git=git)
    assert (ok, reason) == (False, _CONTENT_REFUSE)   # merge-base rc 128: unknown to repo_root


def test_whitelist_refuses_when_oracle_head_unresolvable(tmp_path):
    s = build_scenario(tmp_path)
    base_tip = s.origin_head()
    empty = tmp_path / "empty"
    empty.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=empty, check=True)   # no commits: unborn HEAD
    git = _make_default_git(str(s.repo_dir))
    ok, reason = _content_whitelist(s.repo_dir, str(empty), base_tip, run_git=git)
    assert (ok, reason) == (False, _CONTENT_REFUSE)


def test_whitelist_refuses_on_merge_base_error_rc(tmp_path):
    s = build_scenario(tmp_path)
    base_tip = s.origin_head()

    def _bad_merge_base(args):
        if args[0] == "merge-base":
            return (2, "", "fatal")
        return (0, "", "")
    ok, reason = _content_whitelist(s.repo_dir, str(s.repo_dir), base_tip, run_git=_bad_merge_base)
    assert (ok, reason) == (False, _CONTENT_REFUSE)


def test_whitelist_refuses_when_run_git_raises(tmp_path):
    s = build_scenario(tmp_path)
    base_tip = s.origin_head()

    def _boom(args):
        raise RuntimeError("boom")
    ok, reason = _content_whitelist(s.repo_dir, str(s.repo_dir), base_tip, run_git=_boom)
    assert (ok, reason) == (False, _CONTENT_REFUSE)


# ============================================================
# Entry wiring: ONE fetch per `find_certified_anchor` evaluation, not per link
# ============================================================


def test_fetch_called_once_per_walk_across_a_two_link_chain(tmp_path):
    s = build_scenario(tmp_path)
    anchor = s.head()
    diverge_base_only(s)
    h0 = make_certified_sync_merge(s)
    diverge_base_only(s)
    h1 = make_certified_sync_merge(s)

    real_git = _make_default_git(str(s.repo_dir))
    calls = {"fetch": 0}

    def counting_git(args):
        if args and args[0] == "fetch":
            calls["fetch"] += 1
        return real_git(args)

    result = find_certified_anchor(str(s.repo_dir), h1, {anchor}, base_ref=s.base_ref, run_git=counting_git)
    assert result.certified is True, result.reason
    assert result.links == 2
    assert calls["fetch"] == 1
