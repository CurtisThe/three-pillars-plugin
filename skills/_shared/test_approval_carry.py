"""test_approval_carry.py -- consumer 1 (approval carry), tasks 6.1-6.3.

Covers:
  approved_on_head_result / human_approved_on_head thin-wrapper equivalence (6.1)
  carried_review_approval conjuncts (6.2)
  carry wiring in approved_on_head_result -- config-off byte-parity + spawn-free (6.3)

Task 6.4 (pred_human_approved detail plumbing + the never-FAIL property sweep + fixture
13) continues in `test_approval_carry_pred.py` (split per the plan's named escape hatch).
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
if str(HERE / "fixtures") not in sys.path:
    sys.path.insert(0, str(HERE / "fixtures"))

PR_URL = "https://github.com/example/repo/pull/7"
HEAD_OID = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"
ANCHOR_OID = "1111111111111111111111111111111111111111"


def _review(state="APPROVED", commit_id=HEAD_OID, login="alice", user_type="User"):
    return {
        "user": {"login": login, "type": user_type},
        "state": state,
        "submitted_at": "2026-06-08T14:00:00Z",
        "commit_id": commit_id,
    }


def _head(oid=HEAD_OID):
    return {"headRefOid": oid, "commits": []}


CARRY_CONFIG = {
    "review": {"approval_survives_safe_base_sync": True, "base_sync_carry_max_chain": 5},
}


def _runners(**extra):
    base = {
        "self_login_fn": lambda: "ci-bot",
        "head_fn": lambda _u: _head(),
        "reviews_fn": lambda _u: [_review()],
    }
    base.update(extra)
    return base


# ============================================================
# Task 6.1: approved_on_head_result / human_approved_on_head equivalence
# ============================================================


class TestApprovedOnHeadResult:
    def test_current_review_returns_true_current(self):
        from human_approval import approved_on_head_result

        approved, detail = approved_on_head_result(PR_URL, runners=_runners())
        assert approved is True
        assert detail == "current"

    def test_carry_disabled_miss_returns_false_empty(self):
        """Currency miss + carry disabled (default) -> (False, ""), byte-identical
        to today's `human_approved_on_head` boolean-false behavior."""
        from human_approval import approved_on_head_result

        r = _runners(reviews_fn=lambda _u: [_review(commit_id="stale0000")])
        approved, detail = approved_on_head_result(PR_URL, runners=r)
        assert approved is False
        assert detail == ""

    def test_absent_review_carry_disabled_false_empty(self):
        from human_approval import approved_on_head_result

        approved, detail = approved_on_head_result(
            PR_URL, runners=_runners(reviews_fn=lambda _u: [])
        )
        assert (approved, detail) == (False, "")

    def test_human_approved_on_head_equals_result_zero_current(self):
        from human_approval import approved_on_head_result, human_approved_on_head

        r = _runners()
        result = approved_on_head_result(PR_URL, runners=r)
        assert human_approved_on_head(PR_URL, runners=r) == result[0]

    def test_human_approved_on_head_equals_result_zero_miss(self):
        from human_approval import approved_on_head_result, human_approved_on_head

        r = _runners(reviews_fn=lambda _u: [])
        result = approved_on_head_result(PR_URL, runners=r)
        assert human_approved_on_head(PR_URL, runners=r) == result[0]

    def test_f2_self_unresolvable_is_false_empty(self):
        from human_approval import approved_on_head_result

        def boom():
            raise RuntimeError("self resolve failed")

        r = _runners(self_login_fn=boom)
        assert approved_on_head_result(PR_URL, runners=r) == (False, "")

    def test_never_raises_on_garbage(self):
        from human_approval import approved_on_head_result

        r = _runners(head_fn=lambda _u: "notadict")
        approved, detail = approved_on_head_result(PR_URL, runners=r)
        assert approved is False


# ============================================================
# Task 6.2: carried_review_approval conjuncts
# ============================================================


class TestCarriedReviewApproval:
    """Fixture-repo + injected runners: a currency-miss review anchored on h0 carries to
    a certified-chain head h1 (or refuses per conjunct)."""

    def _scenario(self, tmp_path, monkeypatch):
        import base_sync_oracle
        from base_sync_repo import build_scenario, diverge_base_only, make_certified_sync_merge

        s = build_scenario(tmp_path)
        diverge_base_only(s)
        h0 = s.head()
        h1 = make_certified_sync_merge(s)
        s.git("fetch", "--quiet", "origin", s.base_ref, check=True)
        s.git("checkout", "--quiet", "-B", s.base_ref, f"origin/{s.base_ref}", check=True)
        monkeypatch.setattr(base_sync_oracle, "_oracle_code_dir", lambda: s.repo_dir)
        return s, h0, h1

    def test_carry_pass_single_link(self, tmp_path, monkeypatch):
        from human_approval_review import carried_review_approval

        s, h0, h1 = self._scenario(tmp_path, monkeypatch)
        ok, detail = carried_review_approval(
            [_review(commit_id=h0)], _head(h1), automation=frozenset({"github-actions"}),
            config=CARRY_CONFIG, repo_root=str(s.repo_dir), base_ref=s.base_ref,
        )
        assert ok is True
        assert "approval carried across 1 certified base-sync merge(s)" in detail
        assert h0[:7] in detail

    def test_no_human_review_no_carry(self, tmp_path, monkeypatch):
        from human_approval_review import carried_review_approval

        s, h0, h1 = self._scenario(tmp_path, monkeypatch)
        ok, detail = carried_review_approval(
            [], _head(h1), automation=frozenset(), config=CARRY_CONFIG,
            repo_root=str(s.repo_dir), base_ref=s.base_ref,
        )
        assert (ok, detail) == (False, "")

    def test_non_approved_state_no_carry(self, tmp_path, monkeypatch):
        from human_approval_review import carried_review_approval

        s, h0, h1 = self._scenario(tmp_path, monkeypatch)
        ok, detail = carried_review_approval(
            [_review(state="CHANGES_REQUESTED", commit_id=h0)], _head(h1),
            automation=frozenset(), config=CARRY_CONFIG,
            repo_root=str(s.repo_dir), base_ref=s.base_ref,
        )
        assert (ok, detail) == (False, "")

    def test_automation_authored_review_no_carry(self, tmp_path, monkeypatch):
        """Identity floor untouched: an automation-authored review never anchors a carry
        (latest_human_review filters it out before the anchor is even read)."""
        from human_approval_review import carried_review_approval

        s, h0, h1 = self._scenario(tmp_path, monkeypatch)
        ok, detail = carried_review_approval(
            [_review(commit_id=h0, login="github-actions[bot]", user_type="Bot")],
            _head(h1), automation=frozenset({"github-actions[bot]"}), config=CARRY_CONFIG,
            repo_root=str(s.repo_dir), base_ref=s.base_ref,
        )
        assert (ok, detail) == (False, "")

    def test_anchor_equals_head_not_a_carry(self, tmp_path, monkeypatch):
        s, h0, h1 = self._scenario(tmp_path, monkeypatch)
        from human_approval_review import carried_review_approval

        ok, detail = carried_review_approval(
            [_review(commit_id=h1)], _head(h1), automation=frozenset(),
            config=CARRY_CONFIG, repo_root=str(s.repo_dir), base_ref=s.base_ref,
        )
        assert (ok, detail) == (False, "")

    def test_uncertified_chain_refuses_with_reason(self, tmp_path, monkeypatch):
        """Anchor distinct from head but NOT reachable via a certified chain -> a real
        chain-walk attempt whose non-empty reason is threaded up (attempted-and-failed,
        distinct from the earlier not-attempted cases)."""
        from human_approval_review import carried_review_approval

        s, h0, h1 = self._scenario(tmp_path, monkeypatch)
        bogus_anchor = "9988776655443322110aabbccddeeff00112233"
        ok, detail = carried_review_approval(
            [_review(commit_id=bogus_anchor)], _head(h1), automation=frozenset(),
            config=CARRY_CONFIG, repo_root=str(s.repo_dir), base_ref=s.base_ref,
        )
        assert ok is False
        assert detail != ""

    def test_never_raises_on_garbage(self):
        from human_approval_review import carried_review_approval

        ok, detail = carried_review_approval(
            "not-a-list", "not-a-dict", automation=frozenset(), config=None,
            repo_root=None, base_ref=None,
        )
        assert (ok, detail) == (False, "")


# ============================================================
# Task 6.3: carry wiring in approved_on_head_result
# ============================================================


class TestCarryWiring:
    def test_config_off_byte_identical_and_spawn_free(self, monkeypatch):
        """Config-off (the default): NO git subprocess is EVER spawned, even on a
        currency miss. Patches subprocess.run at the module level everywhere reachable
        so any spawn attempt raises loudly instead of silently succeeding."""
        import subprocess
        from human_approval import approved_on_head_result

        def _forbidden(*a, **k):
            raise AssertionError("git/gh subprocess spawned on a config-off carry miss")

        monkeypatch.setattr(subprocess, "run", _forbidden)
        r = _runners(reviews_fn=lambda _u: [])
        assert approved_on_head_result(PR_URL, runners=r, config=None) == (False, "")
        assert approved_on_head_result(PR_URL, runners=r, config={}) == (False, "")

    def test_carry_enabled_unresolvable_repo_root_no_carry(self, monkeypatch):
        """derive_base_ref_fn present but repo_root unresolvable (no injected
        carry_repo_root, and find_project_root patched to None) -> no carry attempted,
        no subprocess spawned (a live fallback would otherwise hit THIS actual repo)."""
        import subprocess
        import human_approval
        import project_root

        monkeypatch.setattr(project_root, "find_project_root", lambda: None)

        def _forbidden(*a, **k):
            raise AssertionError("subprocess spawned on an unresolvable repo_root")

        monkeypatch.setattr(subprocess, "run", _forbidden)

        r = _runners(
            reviews_fn=lambda _u: [_review(commit_id=ANCHOR_OID)],
            derive_base_ref_fn=lambda _u: "main",
        )
        assert human_approval.approved_on_head_result(
            PR_URL, runners=r, config=CARRY_CONFIG,
        ) == (False, "")

    def test_carry_enabled_unresolvable_base_ref_no_carry(self, tmp_path):
        """repo_root resolvable (injected) but base_ref unresolvable -> no carry."""
        from human_approval import approved_on_head_result

        r = _runners(
            reviews_fn=lambda _u: [_review(commit_id=ANCHOR_OID)],
            carry_repo_root=str(tmp_path),
            derive_base_ref_fn=lambda _u: None,
        )
        assert approved_on_head_result(PR_URL, runners=r, config=CARRY_CONFIG) == (False, "")

    def test_run_git_seam_threaded(self, tmp_path, monkeypatch):
        """The injected run_git seam reaches certified_noop_chain (not silently
        dropped) -- a run_git stub that always reports git < 2.38 refuses distinctly."""
        from human_approval import approved_on_head_result

        def fake_run_git(args):
            if args and args[0] == "version":
                return (0, "git version 2.30.0\n", "")
            return (0, "", "")

        r = _runners(
            reviews_fn=lambda _u: [_review(commit_id=ANCHOR_OID)],
            carry_repo_root=str(tmp_path),
            derive_base_ref_fn=lambda _u: "main",
            run_git=fake_run_git,
        )
        approved, detail = approved_on_head_result(PR_URL, runners=r, config=CARRY_CONFIG)
        assert approved is False
        assert "git < 2.38" in detail

    def test_head_fetch_shape_unchanged(self):
        """The head fetch remains --json headRefOid,commits shaped -- no headRefName
        (the branch-name proxy was dropped)."""
        src = (HERE / "human_approval.py").read_text(encoding="utf-8")
        assert "headRefOid,commits" in src
        assert "headRefName" not in src
