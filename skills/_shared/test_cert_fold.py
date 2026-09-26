"""Tests for cert_fold.fold — strip, base, join, findings, status.

design: audit-pass-does-not-bind (Task 4.4; detailed-design.md §Interfaces [F2][E][R3];
N1, P4, P5). The fold is called once per audit return with every verdict-disposition
certify result and the phrase-scan hits; its output is the post-fold envelope the
orchestrator branches on, so it must validate against audit-return v1.
"""

from __future__ import annotations

import copy
import itertools
import json
from pathlib import Path

import jsonschema
import pytest
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT7

from cert_fold import ENVELOPE_VERDICT, VERDICT_FROM_ENVELOPE, fold

SCHEMAS = Path(__file__).resolve().parent.parent / "tp-run-full-design" / "schemas"


def _validate(env: dict) -> None:
    resources = []
    for p in SCHEMAS.glob("*.json"):
        schema = json.loads(p.read_text(encoding="utf-8"))
        if "$id" in schema:
            resources.append((schema["$id"],
                              Resource.from_contents(schema, default_specification=DRAFT7)))
    audit = json.loads((SCHEMAS / "audit-return.v1.json").read_text(encoding="utf-8"))
    validator = jsonschema.Draft7Validator(audit, registry=Registry().with_resources(resources))
    validator.validate(env)


FINDING = {"confidence": "medium", "category": "fidelity",
           "description": "phase 2 skipped a test", "suggested_fix": "add it"}


def envelope(verdict="pass", status="pass", findings=None, **over) -> dict:
    if findings is None:
        findings = [dict(FINDING)] if verdict == "needs-work" else []
    env = {"schema": "tp-run-full-design/audit-return/v1", "slot": "impl-audit",
           "status": status, "summary": "audited", "verdict": verdict, "findings": findings}
    env.update(over)
    return env


def result(*pairs, name="impl.claims.json", disposition="verdict") -> dict:
    claims = [{"id": cid, "status": st, "reasons": [] if st == "binds" else [f"why-{cid}"],
               "evidence": {"red": [], "green": []}} for cid, st in pairs]
    return {"complete": True, "name": name, "sha": "a" * 40, "disposition": disposition,
            "file_reasons": [], "claims": claims, "statuses": [st for _, st in pairs],
            "orphans": [], "tree_mutated": False}


def hit(matched=False, text="the guard binds", field="summary") -> dict:
    return {"text": text, "field": field, "matched": matched}


def _cats(env: dict) -> list[str]:
    return [f["category"] for f in env["findings"]]


# --- verdict case mapping --------------------------------------------------- #
def test_mapping_is_an_explicit_inverse():
    assert {v: k for k, v in ENVELOPE_VERDICT.items()} == VERDICT_FROM_ENVELOPE
    assert VERDICT_FROM_ENVELOPE["pass-with-notes"] == "PASS WITH NOTES"
    assert VERDICT_FROM_ENVELOPE["known-bypass"] == "KNOWN BYPASS"


@pytest.mark.parametrize("verdict,status", [("pass", "pass"), ("pass-with-notes", "pass"),
                                            ("needs-work", "needs-work")])
def test_each_model_verdict_maps_through(verdict, status):
    out = fold(envelope(verdict, status), [], [])
    assert out["verdict"] == verdict and out["status"] == status
    assert out["certification_base"] == VERDICT_FROM_ENVELOPE[verdict]
    _validate(out)


@pytest.mark.parametrize("verdict", ["unverified", "known-bypass"])
def test_model_supplied_certification_verdict_is_unverified(verdict):
    out = fold(envelope(verdict), [], [])
    assert out["verdict"] == "unverified"
    assert out["certification_base"] == "UNVERIFIED"
    asserted = [f for f in out["findings"] if f["category"] == "certification-unverified"]
    assert len(asserted) == 1 and "model-asserted" in asserted[0]["description"]
    assert out["uncertified_phrases"] == [
        {"text": verdict, "field": "verdict", "reason": "model-asserted"}]
    assert out["status"] == "needs-work"
    _validate(out)


def test_pass_plus_known_bypass_across_two_files():
    results = [result(("c1", "binds")),
               result(("c1", "known-bypass"), ("c2", "binds"), name="phase-2.claims.json")]
    out = fold(envelope("pass"), results, [])
    assert out["verdict"] == "known-bypass" and out["status"] == "pass"
    assert not any("model-asserted" in f["description"] for f in out["findings"])
    assert out["uncertified_phrases"] == []
    keys = [(c["file"], c["id"]) for c in out["certifications"]]
    assert keys == [("impl.claims.json", "c1"), ("phase-2.claims.json", "c1"),
                    ("phase-2.claims.json", "c2")]
    _validate(out)


# --- strip ------------------------------------------------------------------ #
def test_model_supplied_certification_fields_are_stripped():
    env = envelope("pass", certifications=[{"file": "f", "id": "x", "status": "binds"}],
                   uncertified_phrases=[{"text": "t", "field": "summary"}],
                   certification_base="NEEDS WORK")
    out = fold(env, [result(("c1", "binds"))], [])
    assert out["certifications"] == [
        {"file": "impl.claims.json", "id": "c1", "status": "binds", "reasons": []}]
    assert out["uncertified_phrases"] == []
    assert out["certification_base"] == "PASS"
    assert out["verdict"] == "pass"


def test_input_envelope_not_mutated():
    env = envelope("known-bypass", certifications=[])
    before = copy.deepcopy(env)
    fold(env, [result(("c1", "not-binding"))], [hit()])
    assert env == before


def test_ledger_results_never_enter():
    res = result(("c1", "not-binding"), name="sweep-01.claims.json", disposition="ledger")
    out = fold(envelope("pass"), [res], [])
    assert out["verdict"] == "pass" and out["certifications"] == [] and out["findings"] == []


def test_verdict_guards_promote_only_ledger_claims_on_a_listed_guard_path():
    """F12 [R9]: `verdict_guards` = repo paths this candidate changed (`git diff --name-only`)."""
    res = result(("s1", "false-red"), ("s2", "not-binding"), ("s3", "binds"),
                 name="sweep-01.claims.json", disposition="ledger")
    for claim, guard in zip(res["claims"], ["a/test_a.py::t", "b/test_b.py", "a/test_a.py"]):
        claim["guard"] = guard
    out = fold(envelope("pass"), [res], [], verdict_guards={"a/test_a.py"})
    assert [c["id"] for c in out["certifications"]] == ["s1", "s3"]
    assert out["verdict"] == "needs-work"
    assert fold(envelope("pass"), [res], [], verdict_guards=set())["certifications"] == []


@pytest.mark.parametrize("guard,changed", [
    ("./a/test_a.py::t", "a/test_a.py"), ("a/./test_a.py", "a/test_a.py"),
    ("a//test_a.py", "a/test_a.py"),
    ("a/test_a.py::t", "./a/b/../test_a.py")])  # K4: the diff side is normalised too
def test_a_non_normalised_guard_on_a_changed_path_is_still_promoted(guard, changed):
    """G1 [R9]: the guard path is compared in `certify_argv.norm` form, as the poles read it."""
    res = result(("s1", "not-binding"), name="sweep-01.claims.json", disposition="ledger")
    res["claims"][0]["guard"] = guard
    out = fold(envelope("pass"), [res], [], verdict_guards={changed})
    assert [c["id"] for c in out["certifications"]] == ["s1"] and out["verdict"] == "needs-work"


@pytest.mark.parametrize("over", [
    {"name": "impl.claims.json"}, {"name": "records/self.claims.json"},
    {"file_reasons": ["disposition-name"]}, {"file_reasons": None}])
def test_only_a_clean_sweep_named_ledger_result_is_dropped(over):
    """F1: `disposition: ledger` alone never drops a result; the name and file reasons decide."""
    res = result(("c1", "unverified"), name="sweep-01.claims.json", disposition="ledger")
    res.update(over)
    if res["file_reasons"] is None:
        del res["file_reasons"]
    out = fold(envelope("pass"), [res], [])
    assert out["verdict"] == "unverified" and [c["id"] for c in out["certifications"]] == ["c1"]


def test_a_duplicate_file_and_id_is_rejected_not_overwritten():
    """F5: a later `binds` must never erase an earlier `not-binding` under the same key."""
    first = result(("c1", "not-binding"))
    with pytest.raises(ValueError):
        fold(envelope("pass"), [first, result(("c1", "binds"))], [])
    # the control: the same two results under distinct files fold fine
    out = fold(envelope("pass"), [first, result(("c1", "binds"), name="records/impl.claims.json")],
               [])
    assert out["verdict"] == "needs-work" and len(out["certifications"]) == 2


# --- P5: only unmatched hits count ------------------------------------------ #
def test_matched_hit_changes_nothing():
    out = fold(envelope("pass"), [], [hit(matched=True)])
    assert out["verdict"] == "pass" and out["uncertified_phrases"] == []
    assert out["findings"] == [] and out["status"] == "pass"


def test_each_counted_hit_adds_one_unverified():
    hits = [hit(text="guards bind", field="summary"), hit(matched=True),
            hit(text="non-vacuous", field="findings[0].description")]
    out = fold(envelope("pass-with-notes", findings=[dict(FINDING, confidence="high")]), [], hits)
    assert out["verdict"] == "unverified" and out["status"] == "needs-work"
    assert out["uncertified_phrases"] == [{"text": "guards bind", "field": "summary"},
                                          {"text": "non-vacuous",
                                           "field": "findings[0].description"}]
    assert _cats(out).count("certification-unverified") == 2
    _validate(out)


# --- findings per claim ----------------------------------------------------- #
def test_one_finding_per_failing_or_unverified_claim():
    res = result(("c1", "not-binding"), ("c2", "false-red"), ("c3", "unverified"),
                 ("c4", "binds"), ("c5", "known-bypass"))
    out = fold(envelope("pass"), [res], [])
    assert out["verdict"] == "needs-work" and out["status"] == "needs-work"
    assert _cats(out) == ["certification", "certification", "certification-unverified"]
    assert "c1" in out["findings"][0]["description"]
    assert "c3" in out["findings"][2]["description"]
    _validate(out)


def test_existing_findings_are_kept_first():
    out = fold(envelope("needs-work", "needs-work"), [result(("c1", "false-red"))], [])
    assert out["findings"][0] == FINDING and _cats(out) == ["fidelity", "certification"]


def test_unverified_claim_alone_gives_unverified():
    out = fold(envelope("pass"), [result(("c1", "unverified"))], [])
    assert out["verdict"] == "unverified" and out["status"] == "needs-work"
    _validate(out)


# --- B12 identity ------------------------------------------------------------ #
@pytest.mark.parametrize("verdict,status", [
    ("pass", "pass"), ("pass-with-notes", "pass"), ("needs-work", "needs-work"),
    ("pass", "errored"), ("needs-work", "handoff-pending"),
])
def test_no_results_no_hits_is_identity(verdict, status):
    env = envelope(verdict, status)
    out = fold(env, [], [])
    assert (out["verdict"], out["status"]) == (verdict, status)
    assert out["findings"] == env["findings"]


# --- N1 / P4: the full 4 x 5 status matrix ---------------------------------- #
FOLDED = {  # folded verdict -> (model verdict, results) that produce it
    "PASS": ("pass", []),
    "PASS WITH NOTES": ("pass-with-notes", []),
    "KNOWN BYPASS": ("pass", [result(("c1", "known-bypass"))]),
    "NEEDS WORK": ("pass", [result(("c1", "not-binding"))]),
    "UNVERIFIED": ("pass", [result(("c1", "unverified"))]),
}
EXPECTED_STATUS = {
    "errored": dict.fromkeys(FOLDED, "errored"),
    "handoff-pending": dict.fromkeys(FOLDED, "handoff-pending"),
    "needs-work": dict.fromkeys(FOLDED, "needs-work"),
    "pass": {"PASS": "pass", "PASS WITH NOTES": "pass", "KNOWN BYPASS": "pass",
             "NEEDS WORK": "needs-work", "UNVERIFIED": "needs-work"},
}


@pytest.mark.parametrize("status,folded", list(itertools.product(EXPECTED_STATUS, FOLDED)))
def test_status_matrix(status, folded):
    model_verdict, results = FOLDED[folded]
    out = fold(envelope(model_verdict, status), copy.deepcopy(results), [])
    assert out["verdict"] == ENVELOPE_VERDICT[folded]
    assert out["status"] == EXPECTED_STATUS[status][folded]
    _validate(out)


def test_needs_work_status_with_model_needs_work_verdict_folding_to_unverified():
    env = envelope("needs-work", "needs-work")
    out = fold(env, [], [hit()])
    assert out["verdict"] == "needs-work" and out["status"] == "needs-work"


# --- bad input -------------------------------------------------------------- #
@pytest.mark.parametrize("over", [{"verdict": "PASS"}, {"verdict": "Pass-With-Notes"},
                                  {"verdict": "blocked"}, {"status": "done"}])
def test_unknown_verdict_or_status_raises_value_error(over):
    with pytest.raises(ValueError):
        fold(envelope(**over), [], [])
