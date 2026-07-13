"""test_proof_carry_pred.py -- consumer 2, tasks 7.2 (property sweep) + 7.3 (gate_roster
runner threading + oracle fixture 13 threaded through consumer 2).

Split from `test_proof_carry.py` per the plan's named escape hatch (300-line soft cap).
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
if str(HERE / "fixtures") not in sys.path:
    sys.path.insert(0, str(HERE / "fixtures"))
_PR_ITERATE = HERE.parent / "tp-pr-iterate" / "scripts"
if str(_PR_ITERATE) not in sys.path:
    sys.path.insert(0, str(_PR_ITERATE))

import review_proof  # noqa: E402
import pytest  # noqa: E402
from attack_matrix import ATTACK_CASE_NAMES  # noqa: E402

PR = "https://github.com/o/r/pull/1"
AUTHOR = "tp-loop-bot"


def _c(body, author=AUTHOR):
    return {"author": author, "body": body}


def _digest_for(head):
    meta = {
        "base": "base000", "head": head, "files_changed": 3,
        "insertions": 5, "deletions": 1, "degraded": False, "reason": None,
    }
    return review_proof.format_proof_digest(meta, [("correctness", 0)])


# ============================================================
# Task 7.2: never-FAIL/never-PASS property sweep
# ============================================================


@pytest.mark.parametrize("case_name", ATTACK_CASE_NAMES)
def test_property_attack_fixture_is_indeterminate_never_fail_or_pass(
    case_name, tmp_path, monkeypatch,
):
    import proof_predicate
    from deterministic_gate import GateVerdict
    from attack_matrix import CARRY_CONFIG, build_attack_case

    s, head_oid, anchor = build_attack_case(case_name, tmp_path, monkeypatch)
    comments = [_c(_digest_for(anchor))]
    r = proof_predicate.pred_review_proof_on_head(
        PR, head_oid,
        comments_fn=lambda _u, c=comments: c,
        self_login_fn=lambda: AUTHOR,
        config=CARRY_CONFIG,
        repo_root=str(s.repo_dir),
        derive_base_ref_fn=lambda _u, b=s.base_ref: b,
    )
    assert r.verdict != GateVerdict.FAIL, f"{case_name}: got FAIL"
    assert r.verdict == GateVerdict.INDETERMINATE, (
        f"{case_name}: expected INDETERMINATE (a tampered/uncertified chain must never "
        f"carry proof), got {r.verdict}: {r.detail}"
    )


def test_fixture13_seat_detached_at_chain_ancestor_threaded_no_carry(tmp_path, monkeypatch):
    """Oracle round-2 case 13 threaded through consumer 2: the seat detached at an
    ancestor of head_oid INSIDE the certified chain -> the oracle guard refuses ->
    no carry, INDETERMINATE (never FAIL/PASS)."""
    import base_sync_oracle
    import proof_predicate
    from base_sync_repo import build_scenario, diverge_base_only, make_certified_sync_merge
    from base_sync_topologies import checkout_detached
    from deterministic_gate import GateVerdict
    from attack_matrix import CARRY_CONFIG

    s = build_scenario(tmp_path)
    diverge_base_only(s)
    h0 = make_certified_sync_merge(s)   # first certified link, anchored on the base line
    diverge_base_only(s)
    h1 = make_certified_sync_merge(s)   # head under verification: further along the chain
    checkout_detached(s, h0)            # the seat mis-detached at the ancestor merge h0
    monkeypatch.setattr(base_sync_oracle, "_oracle_code_dir", lambda: s.repo_dir)

    r = proof_predicate.pred_review_proof_on_head(
        PR, h1,
        comments_fn=lambda _u: [_c(_digest_for(h0))],
        self_login_fn=lambda: AUTHOR,
        config=CARRY_CONFIG,
        repo_root=str(s.repo_dir),
        derive_base_ref_fn=lambda _u: s.base_ref,
    )
    assert r.verdict == GateVerdict.INDETERMINATE
    assert r.verdict != GateVerdict.FAIL
    assert "; carry:" in r.detail


# ============================================================
# Task 7.3: gate_roster runner threading
# ============================================================


def test_gate_roster_threads_carry_seams_fixture13_indeterminate(tmp_path, monkeypatch):
    """build_predicates_and_roster threads run_git/derive_base_ref_fn/carry_repo_root
    into pred_review_proof_on_head — oracle fixture 13 threaded THROUGH THE ROSTER (not
    the predicate directly) still yields INDETERMINATE for review_proof_on_head."""
    import base_sync_oracle
    import gate_roster
    from base_sync_repo import build_scenario, diverge_base_only, make_certified_sync_merge
    from base_sync_topologies import checkout_detached
    from deterministic_gate import FailureClass

    s = build_scenario(tmp_path)
    diverge_base_only(s)
    h0 = make_certified_sync_merge(s)
    diverge_base_only(s)
    h1 = make_certified_sync_merge(s)
    checkout_detached(s, h0)
    monkeypatch.setattr(base_sync_oracle, "_oracle_code_dir", lambda: s.repo_dir)

    config = {
        "review": {
            "expects_copilot": False, "require_human_approval": False,
            "approval_survives_safe_base_sync": True,
        },
        "ci": {"expects_github_checks": False},
    }
    r = {
        "comments_fn": lambda _u: [_c(_digest_for(h0))],
        "self_login_fn": lambda: AUTHOR,
        "carry_repo_root": str(s.repo_dir),
        "derive_base_ref_fn": lambda _u: s.base_ref,
    }
    predicates, roster_entries = gate_roster.build_predicates_and_roster(
        pr_url=PR, rollup=[], failure_class=FailureClass.INDETERMINATE,
        threads=[], mergeable="MERGEABLE", head_oid=h1, config=config, r=r,
        copilot_runners=None, running_live=False, shared_dir=None,
    )
    proof_entries = [e for e in roster_entries if e.name == "review_proof_on_head"]
    assert len(proof_entries) == 1
    assert proof_entries[0].status == "INDETERMINATE"
    assert "; carry:" in proof_entries[0].detail
