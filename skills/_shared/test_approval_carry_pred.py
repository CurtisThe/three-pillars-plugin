"""test_approval_carry_pred.py -- consumer 1, task 6.4: pred_human_approved detail
plumbing + the never-FAIL/never-PASS property sweep over the Phase 4-5 attack matrix +
oracle fixture 13 (seat-detached-at-chain-ancestor) threaded through consumer 1.

Split from `test_approval_carry.py` per the plan's named escape hatch (300-line soft cap).
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
if str(HERE / "fixtures") not in sys.path:
    sys.path.insert(0, str(HERE / "fixtures"))

import pytest  # noqa: E402
from attack_matrix import ATTACK_CASE_NAMES  # noqa: E402

PR_URL = "https://github.com/example/repo/pull/7"


def _review(state="APPROVED", commit_id="", login="alice", user_type="User"):
    return {
        "user": {"login": login, "type": user_type},
        "state": state,
        "submitted_at": "2026-06-08T14:00:00Z",
        "commit_id": commit_id,
    }


def _head(oid):
    return {"headRefOid": oid, "commits": []}


# ============================================================
# Task 6.4: pred_human_approved detail plumbing (carry-enabled path)
# ============================================================


class TestPredHumanApprovedCarryDetail:
    def _runners(self, *, head_oid, anchor, repo_root, base_ref):
        return {
            "self_login_fn": lambda: "ci-bot",
            "head_fn": lambda _u: _head(head_oid),
            "reviews_fn": lambda _u: [_review(commit_id=anchor)],
            "carry_repo_root": repo_root,
            "derive_base_ref_fn": lambda _u: base_ref,
        }

    def test_pass_detail_is_carry_detail_when_carried(self, tmp_path, monkeypatch):
        import base_sync_oracle
        from base_sync_repo import build_scenario, diverge_base_only, make_certified_sync_merge
        from deterministic_gate import GateVerdict, pred_human_approved
        from attack_matrix import CARRY_CONFIG

        s = build_scenario(tmp_path)
        diverge_base_only(s)
        h0 = s.head()
        h1 = make_certified_sync_merge(s)
        s.git("fetch", "--quiet", "origin", s.base_ref, check=True)
        s.git("checkout", "--quiet", "-B", s.base_ref, f"origin/{s.base_ref}", check=True)
        monkeypatch.setattr(base_sync_oracle, "_oracle_code_dir", lambda: s.repo_dir)

        r = self._runners(head_oid=h1, anchor=h0, repo_root=str(s.repo_dir), base_ref=s.base_ref)
        result = pred_human_approved(PR_URL, runners=r, config=CARRY_CONFIG)
        assert result.verdict == GateVerdict.PASS
        assert "approval carried across 1 certified base-sync merge(s)" in result.detail
        assert result.detail != "a non-automation human approved THIS head"

    def test_pass_detail_unchanged_when_current(self):
        from deterministic_gate import GateVerdict, pred_human_approved
        from attack_matrix import CARRY_CONFIG

        r = {
            "self_login_fn": lambda: "ci-bot",
            "head_fn": lambda _u: _head("deadbeef"),
            "reviews_fn": lambda _u: [_review(commit_id="deadbeef")],
        }
        result = pred_human_approved(PR_URL, runners=r, config=CARRY_CONFIG)
        assert result.verdict == GateVerdict.PASS
        assert result.detail == "a non-automation human approved THIS head"

    def test_indeterminate_carry_reason_appended_when_attempted_and_failed(
        self, tmp_path, monkeypatch,
    ):
        import base_sync_oracle
        from base_sync_repo import build_scenario, diverge_base_only, make_certified_sync_merge
        from deterministic_gate import GateVerdict, pred_human_approved
        from attack_matrix import CARRY_CONFIG

        s = build_scenario(tmp_path)
        diverge_base_only(s)
        h0 = s.head()
        h1 = make_certified_sync_merge(s)
        s.git("fetch", "--quiet", "origin", s.base_ref, check=True)
        s.git("checkout", "--quiet", "-B", s.base_ref, f"origin/{s.base_ref}", check=True)
        monkeypatch.setattr(base_sync_oracle, "_oracle_code_dir", lambda: s.repo_dir)

        bogus_anchor = "9988776655443322110aabbccddeeff00112233"
        r = self._runners(
            head_oid=h1, anchor=bogus_anchor, repo_root=str(s.repo_dir), base_ref=s.base_ref,
        )
        result = pred_human_approved(PR_URL, runners=r, config=CARRY_CONFIG)
        assert result.verdict == GateVerdict.INDETERMINATE
        assert "; carry:" in result.detail
        assert "APPROVED PR review" in result.detail   # today's remediation string, verbatim

    def test_indeterminate_no_carry_suffix_when_not_attempted(self):
        """Carry enabled but nothing to try (no human review at all) -> today's
        remediation detail with NO '; carry:' suffix (not attempted, not failed)."""
        from deterministic_gate import GateVerdict, pred_human_approved
        from attack_matrix import CARRY_CONFIG

        r = {
            "self_login_fn": lambda: "ci-bot",
            "head_fn": lambda _u: _head("deadbeef"),
            "reviews_fn": lambda _u: [],
        }
        result = pred_human_approved(PR_URL, runners=r, config=CARRY_CONFIG)
        assert result.verdict == GateVerdict.INDETERMINATE
        assert "; carry:" not in result.detail


# ============================================================
# Task 6.4: never-FAIL/never-PASS property sweep + fixture 13
# ============================================================


@pytest.mark.parametrize("case_name", ATTACK_CASE_NAMES)
def test_property_attack_fixture_is_indeterminate_never_fail_or_pass(
    case_name, tmp_path, monkeypatch,
):
    from deterministic_gate import GateVerdict, pred_human_approved
    from attack_matrix import CARRY_CONFIG, build_attack_case

    s, head_oid, anchor = build_attack_case(case_name, tmp_path, monkeypatch)
    r = {
        "self_login_fn": lambda: "ci-bot",
        "head_fn": lambda _u, h=head_oid: _head(h),
        "reviews_fn": lambda _u, a=anchor: [_review(commit_id=a)],
        "carry_repo_root": str(s.repo_dir),
        "derive_base_ref_fn": lambda _u, b=s.base_ref: b,
    }
    result = pred_human_approved(PR_URL, runners=r, config=CARRY_CONFIG)
    assert result.verdict != GateVerdict.FAIL, f"{case_name}: got FAIL"
    assert result.verdict == GateVerdict.INDETERMINATE, (
        f"{case_name}: expected INDETERMINATE (a tampered/uncertified chain must never "
        f"carry), got {result.verdict}: {result.detail}"
    )


def test_fixture13_seat_detached_at_chain_ancestor_threaded_no_carry(tmp_path, monkeypatch):
    """Oracle round-2 case 13 threaded through consumer 1: the seat detached at an
    ancestor of head_oid INSIDE the certified chain -> the oracle guard refuses ->
    no carry, INDETERMINATE (never FAIL/PASS)."""
    import base_sync_oracle
    from base_sync_repo import build_scenario, diverge_base_only, make_certified_sync_merge
    from base_sync_topologies import checkout_detached
    from deterministic_gate import GateVerdict, pred_human_approved
    from attack_matrix import CARRY_CONFIG

    s = build_scenario(tmp_path)
    diverge_base_only(s)
    h0 = make_certified_sync_merge(s)   # first certified link, anchored on the base line
    diverge_base_only(s)
    h1 = make_certified_sync_merge(s)   # head under verification: further along the chain
    checkout_detached(s, h0)            # the seat mis-detached at the ancestor merge h0
    monkeypatch.setattr(base_sync_oracle, "_oracle_code_dir", lambda: s.repo_dir)

    r = {
        "self_login_fn": lambda: "ci-bot",
        "head_fn": lambda _u: _head(h1),
        "reviews_fn": lambda _u: [_review(commit_id=h0)],
        "carry_repo_root": str(s.repo_dir),
        "derive_base_ref_fn": lambda _u: s.base_ref,
    }
    result = pred_human_approved(PR_URL, runners=r, config=CARRY_CONFIG)
    assert result.verdict == GateVerdict.INDETERMINATE
    assert result.verdict != GateVerdict.FAIL
    assert "; carry:" in result.detail
