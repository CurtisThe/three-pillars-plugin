"""Structural (grep) tests for the review-integrity-enforcement convergence contract.

Task 3.1: the byproduct-only + bounded-retry + not-converged/escalate contract has ONE
substantive home (`tp-pr-iterate/proof-of-review.md`) plus minimal pointers in the two
driver SKILL.md files, and the "two enforced call sites" wording names `run_round.py` as
the live loop terminal (Finding 5). New file (test_pr_iterate_skill_md.py is near cap).
"""
from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
PROOF_DOC = _ROOT / "tp-pr-iterate" / "proof-of-review.md"
PR_ITERATE_SKILL = _ROOT / "tp-pr-iterate" / "SKILL.md"
TIER7_SKILL = _ROOT / "tp-run-full-design" / "SKILL.md"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_proof_doc_has_byproduct_only_rule() -> None:
    body = _read(PROOF_DOC)
    assert "Convergence action contract" in body
    assert "Byproduct-only" in body, (
        "proof-of-review.md must state convergence is emitted only as a byproduct of a "
        "two-stable terminal, never as independent narration"
    )
    assert "byproduct" in body.lower() and "converged=true" in body


def test_proof_doc_has_bounded_retry_and_escalate() -> None:
    body = _read(PROOF_DOC)
    assert "Bounded re-run" in body
    assert "degraded_review_retries" in body, (
        "proof-of-review.md must name the mechanical retry counter"
    )
    assert "not_converged_reason" in body
    assert "not-converged" in body and "escalate" in body.lower()


def test_proof_doc_names_shared_predicate_delegation() -> None:
    body = _read(PROOF_DOC)
    assert "convergence_proof.non_degraded_proof_on_head" in body
    assert "pred_review_proof_on_head" in body
    assert "no second implementation" in body.lower()


def test_two_enforced_call_sites_names_run_round_py() -> None:
    """Finding 5: site 1 must name run_round.py as the live loop terminal, with run_loop
    as the tested in-process twin — not imply run_loop is the live enforcement path."""
    body = _read(PROOF_DOC)
    idx = body.find("## The two enforced call sites")
    assert idx != -1, "the 'two enforced call sites' section must exist"
    section = body[idx:idx + 900]
    assert "run_round.py" in section, (
        "site 1 of 'the two enforced call sites' must name run_round.py as the live "
        "loop terminal"
    )
    assert "tested in-process twin" in section, (
        "site 1 must describe loop_driver.run_loop as the tested in-process twin "
        "(run_loop has no live caller)"
    )


def test_tp_pr_iterate_skill_points_at_retry_contract() -> None:
    body = _read(PR_ITERATE_SKILL)
    # net-neutral pointer folded into the blocked-terminal prose
    assert "proof-of-review.md" in body
    assert "Bounded re-run / not-converged" in body


def test_tier7_skill_points_at_convergence_contract() -> None:
    body = _read(TIER7_SKILL)
    assert "review-integrity-enforcement" in body
    assert "not_converged_reason" in body
    assert "degraded_review_retries" in body
    assert "Convergence action contract" in body, (
        "Tier-7 SKILL.md must point at proof-of-review.md's Convergence action contract"
    )


def test_proof_doc_still_under_cap() -> None:
    src = _read(PROOF_DOC)
    lines = src.count("\n") + 1
    assert lines <= 500, f"proof-of-review.md is {lines} lines (cap=500)"
    assert len(src) <= 50000
