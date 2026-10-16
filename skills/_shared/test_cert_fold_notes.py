"""Tests for cert_fold._claim_finding's certification-note category.

design: review-convergence (Task 12.3; detailed-design-phase-check.md §F2). A
`not-binding` / `false-red` claim, and an `unverified` claim whose reasons are all
claim-shape (`invalid:*`, `guard-is-subject`), fold to a note finding
(`category: "certification-note"`, `severity: "minor"`), never the
`certification-unverified` finalizer path. Every other `unverified` claim keeps
today's `certification-unverified` finding.

The verdict fold follows the same rule: a claim-shape-only `unverified` claim folds
exactly like a `not-binding` claim, so the folded verdict is never `unverified` and
the orchestrator never escalates `certification-unverified` for a malformed claim.
Every other `unverified` claim still folds `unverified`.
"""

from __future__ import annotations

import pytest

from cert_fold import fold

NOTE = "certification-note"
UNVERIFIED = "certification-unverified"


def envelope(verdict="pass", status="pass", **over) -> dict:
    env = {"schema": "tp-run-full-design/audit-return/v1", "slot": "impl-audit",
           "status": status, "summary": "audited", "verdict": verdict, "findings": []}
    env.update(over)
    return env


def result(cid: str, status: str, reasons: list[str], name="impl.claims.json") -> dict:
    claim = {"id": cid, "status": status, "reasons": list(reasons),
             "evidence": {"red": [], "green": []}}
    return {"complete": True, "name": name, "sha": "a" * 40, "disposition": "verdict",
            "file_reasons": [], "claims": [claim], "statuses": [status],
            "orphans": [], "tree_mutated": False}


def _only_finding(out: dict) -> dict:
    assert len(out["findings"]) == 1
    return out["findings"][0]


@pytest.mark.parametrize("status", ["not-binding", "false-red"])
def test_failing_claim_is_a_minor_note(status):
    finding = _only_finding(fold(envelope(), [result("c1", status, ["why"])], []))
    assert finding["category"] == NOTE
    assert finding["severity"] == "minor"
    assert "impl.claims.json [cert:c1]" in finding["description"]
    assert status in finding["description"]


@pytest.mark.parametrize("reasons", [["invalid:guard"], ["guard-is-subject"],
                                     ["invalid:argv", "guard-is-subject"]])
def test_claim_shape_only_unverified_is_a_minor_note(reasons):
    finding = _only_finding(fold(envelope(), [result("c1", "unverified", reasons)], []))
    assert finding["category"] == NOTE
    assert finding["severity"] == "minor"
    assert "impl.claims.json [cert:c1]" in finding["description"]
    for reason in reasons:
        assert reason in finding["description"]


@pytest.mark.parametrize("reasons", [["red-crash"], ["invalid:guard", "red-crash"], []])
def test_other_unverified_keeps_certification_unverified(reasons):
    finding = _only_finding(fold(envelope(), [result("c1", "unverified", reasons)], []))
    assert finding["category"] == UNVERIFIED
    assert "severity" not in finding


@pytest.mark.parametrize("reasons", [["invalid:subjects"], ["guard-is-subject"]])
def test_claim_shape_only_unverified_folds_verdict_like_not_binding(reasons):
    out = fold(envelope(), [result("c1", "unverified", reasons)], [])
    assert out["verdict"] != "unverified"
    assert out["verdict"] == fold(
        envelope(), [result("c1", "not-binding", reasons)], [])["verdict"]
    # the certification entry itself still records the claim as it came back
    assert [(c["id"], c["status"]) for c in out["certifications"]] == [("c1", "unverified")]


@pytest.mark.parametrize("reasons", [["red-crash"], ["invalid:guard", "red-crash"]])
def test_other_unverified_still_folds_verdict_unverified(reasons):
    out = fold(envelope(), [result("c1", "unverified", reasons)], [])
    assert out["verdict"] == "unverified"


def test_guard_claim_with_no_result_keeps_certification_unverified():
    claims = [{"id": "g1", "guard": "skills/_shared/test_x.py::test_y", "property": "p",
               "parameters": []}]
    out = fold(envelope(guard_claims=claims), [], [])
    finding = _only_finding(out)
    assert finding["category"] == UNVERIFIED
    assert "no-result" in finding["description"]
    assert "severity" not in finding
