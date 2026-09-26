"""audit-return v1, extended in place with the certification fields.

design: audit-pass-does-not-bind (Task 4.2; N9, N11, P12). Lives in `_shared`
so the merge-gate lane collects it. Old envelopes still validate (B12); the new
verdicts and optional fields are accepted; `verdict: unverified` needs a
non-empty `certifications` or `uncertified_phrases` (the post-fold envelope).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import jsonschema
import pytest
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT7

import cert_fold

SCHEMAS = Path(__file__).resolve().parent.parent / "tp-run-full-design" / "schemas"
AUDIT = SCHEMAS / "audit-return.v1.json"


def _registry() -> Registry:
    resources = []
    for p in SCHEMAS.glob("*.json"):
        schema = json.loads(p.read_text(encoding="utf-8"))
        if "$id" in schema:
            resources.append((schema["$id"],
                              Resource.from_contents(schema, default_specification=DRAFT7)))
    return Registry().with_resources(resources)


def _is_valid(instance: dict) -> bool:
    schema = json.loads(AUDIT.read_text(encoding="utf-8"))
    return jsonschema.Draft7Validator(schema, registry=_registry()).is_valid(instance)


FINDING = {"confidence": "medium", "category": "fidelity",
           "description": "phase 2 skipped a test", "suggested_fix": "add it"}


def _env(**over) -> dict:
    env = {"schema": "tp-run-full-design/audit-return/v1", "slot": "impl-audit",
           "status": "pass", "summary": "audited", "verdict": "pass", "findings": []}
    env.update(over)
    return env


CERT = {"file": "impl.claims.json", "id": "c1", "status": "unverified", "reasons": ["no-record"]}
PHRASE = {"text": "the guard binds", "field": "summary"}


# --- B12: old envelopes unchanged ------------------------------------------ #
@pytest.mark.parametrize("env", [
    _env(),
    _env(verdict="pass-with-notes", findings=[dict(FINDING, confidence="high")]),
    _env(verdict="needs-work", status="needs-work", findings=[FINDING]),
    _env(status="errored"),
    _env(status="handoff-pending", verdict="needs-work", findings=[FINDING]),
])
def test_old_envelopes_still_validate(env):
    assert _is_valid(env)


def test_old_needs_work_rule_kept():
    assert not _is_valid(_env(verdict="needs-work", findings=[]))


def test_schema_const_unchanged():
    assert not _is_valid(_env(schema="tp-run-full-design/audit-return/v2"))
    schema = json.loads(AUDIT.read_text(encoding="utf-8"))
    assert schema["properties"]["schema"] == {"const": "tp-run-full-design/audit-return/v1"}


def test_unknown_verdict_rejected():
    assert not _is_valid(_env(verdict="blocked"))


# --- new verdicts + optional fields ----------------------------------------- #
def test_known_bypass_accepted():
    assert _is_valid(_env(verdict="known-bypass"))


def test_unverified_accepted_with_certifications():
    assert _is_valid(_env(verdict="unverified", status="needs-work", certifications=[CERT]))


def test_optional_certification_fields_accepted():
    env = _env(
        guard_claims=[{"id": "c1", "guard": "skills/_shared/test_x.py::test_y",
                       "property": "rejects an empty list", "parameters": ["items"],
                       "subjects": ["skills/_shared/x.py"]}],
        guards_certified="- [cert:c1] test_x.py::test_y binds (record on file)",
        certifications=[dict(CERT, status="binds", reasons=[])],
        uncertified_phrases=[dict(PHRASE, reason="model-asserted")],
        certification_base="PASS",
    )
    assert _is_valid(env)


@pytest.mark.parametrize("claim", [
    {"id": "c1", "guard": "g.py", "property": "p"},
    {"id": "c1", "guard": "g.py", "property": "p", "parameters": ["x"], "status": "binds"},
    {"id": "c1", "guard": "g.py", "property": "p", "parameters": [3]},
    {"id": "c1", "guard": "g.py", "property": "p", "parameters": ["x"], "subjects": []},
    {"id": "c1", "guard": "g.py", "property": "p", "parameters": ["x"], "subjects": [""]},
])
def test_guard_claims_have_claim_shape(claim):
    assert not _is_valid(_env(guard_claims=[claim]))


@pytest.mark.parametrize("phrase", [{"text": "binds"}, {"field": "summary"},
                                    {"text": 1, "field": "summary"}])
def test_uncertified_phrase_shape(phrase):
    assert not _is_valid(_env(uncertified_phrases=[phrase]))


def test_certification_entry_status_enum():
    assert not _is_valid(_env(certifications=[dict(CERT, status="maybe")]))
    for status in ("binds", "not-binding", "false-red", "unverified", "known-bypass"):
        assert _is_valid(_env(certifications=[dict(CERT, status=status)]))


def test_certification_base_enum():
    assert not _is_valid(_env(certification_base="pass"))
    assert _is_valid(_env(certification_base="KNOWN BYPASS"))


# --- N9 / P12: unverified needs a non-empty certifications | phrases ------- #
_ABSENT = object()


@pytest.mark.parametrize("certs,phrases", [
    (_ABSENT, _ABSENT), ([], _ABSENT), (_ABSENT, []), ([], []),
])
def test_unverified_empty_or_absent_rejected(certs, phrases):
    env = _env(verdict="unverified", status="needs-work")
    if certs is not _ABSENT:
        env["certifications"] = certs
    if phrases is not _ABSENT:
        env["uncertified_phrases"] = phrases
    assert not _is_valid(env)


@pytest.mark.parametrize("certs,phrases", [
    ([CERT], _ABSENT), (_ABSENT, [PHRASE]), ([CERT], []), ([], [PHRASE]), ([CERT], [PHRASE]),
])
def test_unverified_either_non_empty_valid(certs, phrases):
    env = _env(verdict="unverified", status="needs-work")
    if certs is not _ABSENT:
        env["certifications"] = copy.deepcopy(certs)
    if phrases is not _ABSENT:
        env["uncertified_phrases"] = copy.deepcopy(phrases)
    assert _is_valid(env)


@pytest.mark.parametrize("verdict", ["unverified", "known-bypass"])
def test_the_rule_governs_the_post_fold_envelope(verdict):
    """N9: a model's bare `unverified` fails the rule; the fold's output of it satisfies it."""
    raw = _env(verdict=verdict, status="needs-work")
    folded = cert_fold.fold(raw, [], [])
    assert folded["verdict"] == "unverified"
    assert not _is_valid(dict(raw, verdict="unverified")) and _is_valid(folded)
