"""Tests for cert_fold.fold's guard-claims coverage rule.

design: audit-pass-does-not-bind (impl-audit J1). The synth's `guard_claims[]` are
certified from `certifications/records/<x>.claims.json`, a path only the orchestrator
writes (claimant-check refuses it in a candidate). A result lost in scratch (a name
collision, a dropped `--result`) used to leave its claims out of the fold with the
verdict still PASS; now every envelope guard claim with no `certifications` entry from
a `records/` result folds `unverified` (reason `no-result`).
"""

from __future__ import annotations

from cert_fold import fold
from test_cert_fold import _validate, envelope, result

SYNTH = "records/impl-audit.claims.json"


def claims(*ids) -> list[dict]:
    return [{"id": cid, "guard": "skills/_shared/test_x.py::test_y", "property": "p",
             "parameters": []} for cid in ids]


def test_every_guard_claim_certified_passes():
    out = fold(envelope("pass", guard_claims=claims("c1", "c2")),
               [result(("c1", "binds"), ("c2", "binds"), name=SYNTH)], [])
    assert out["verdict"] == "pass" and len(out["certifications"]) == 2


def test_a_guard_claim_with_no_result_folds_unverified():
    out = fold(envelope("pass", guard_claims=claims("c1", "c2")),
               [result(("c1", "binds"), name=SYNTH)], [])
    assert out["verdict"] == "unverified" and out["status"] == "needs-work"
    missing = [c for c in out["certifications"] if c["id"] == "c2"]
    assert [(c["status"], c["reasons"]) for c in missing] == [("unverified", ["no-result"])]
    assert any("[cert:c2]" in f["description"] for f in out["findings"])
    _validate(out)


def test_guard_claims_and_no_results_at_all_fold_unverified():
    out = fold(envelope("pass", guard_claims=claims("c1")), [], [])
    assert out["verdict"] == "unverified"


def test_an_id_less_guard_claim_is_never_covered():
    bad = [{"guard": "skills/_shared/test_x.py", "property": "p", "parameters": []}]
    out = fold(envelope("pass", guard_claims=bad), [result(("None", "binds"), name=SYNTH)], [])
    assert out["verdict"] == "unverified"


def test_a_candidate_file_with_the_same_id_does_not_cover_a_guard_claim():
    """The collision J1 reproduced: a candidate's top-level file stands in for the synth's."""
    out = fold(envelope("pass", guard_claims=claims("c1")),
               [result(("c1", "binds"), name="records-impl-audit.claims.json")], [])
    assert out["verdict"] == "unverified"


def test_no_guard_claims_is_unchanged():
    out = fold(envelope("pass"), [result(("c1", "binds"))], [])
    assert out["verdict"] == "pass" and len(out["certifications"]) == 1
