"""test_finding_fields_schema.py — audit-return.v1.json's findings[] gain the two
optional enums, `origin` and `fragility_class`.

design: fragile-test-prevention (detailed-design.md, `finding_fields.normalize`
section) — task 9.2: the schema's two optional enums on `findings[]` items equal
the registries in `finding_fields.py`; a finding without them still validates,
and one with an unknown value is rejected.

Oracle: ``schema``, ``example``. The enum-equality check reads the schema with
``json.load`` and always runs. The validate / reject cases need the third-party
jsonschema validator and each ``importorskip``s it inside its own test function.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import finding_fields  # noqa: E402

SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "tp-run-full-design" / "schemas"
SCHEMA_PATH = SCHEMAS_DIR / "audit-return.v1.json"


def _schema() -> dict:
    with SCHEMA_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def _registry():
    referencing = pytest.importorskip("referencing")
    from referencing.jsonschema import DRAFT7

    resources = []
    for p in SCHEMAS_DIR.glob("*.json"):
        schema = json.loads(p.read_text(encoding="utf-8"))
        if "$id" in schema:
            resources.append(
                (schema["$id"], referencing.Resource.from_contents(schema, default_specification=DRAFT7))
            )
    return referencing.Registry().with_resources(resources)


def _finding_props() -> dict:
    return _schema()["properties"]["findings"]["items"]["properties"]


def _base_finding() -> dict:
    return {
        "confidence": "high",
        "category": "structure",
        "description": "something",
        "suggested_fix": "fix it",
    }


# --- schema shape (json.load; always run) -----------------------------------------


def test_origin_enum_equals_the_registry():
    spec = _finding_props()["origin"]
    assert spec["type"] == "string"
    assert set(spec["enum"]) == set(finding_fields.ORIGINS)


def test_fragility_class_enum_equals_the_registry():
    spec = _finding_props()["fragility_class"]
    assert spec["type"] == "string"
    assert set(spec["enum"]) == set(finding_fields.FRAGILITY_CLASSES)


# --- jsonschema (importorskip inside each test) ------------------------------------


def _validator():
    jsonschema = pytest.importorskip("jsonschema")
    schema = _schema()
    return jsonschema.Draft7Validator(schema, registry=_registry())


def test_finding_without_the_optional_fields_still_validates():
    finding = _base_finding()
    envelope = {
        "schema": "tp-run-full-design/audit-return/v1",
        "slot": "design-audit",
        "status": "pass",
        "summary": "ok",
        "verdict": "pass",
        "findings": [finding],
    }
    errors = [
        e
        for e in _validator().iter_errors(envelope)
        if list(e.absolute_path) == ["findings", 0]
    ]
    assert errors == []


def test_finding_with_a_known_origin_and_fragility_class_validates():
    finding = _base_finding()
    finding["origin"] = finding_fields.ORIGINS[0]
    finding["fragility_class"] = finding_fields.FRAGILITY_CLASSES[0]
    envelope = {
        "schema": "tp-run-full-design/audit-return/v1",
        "slot": "design-audit",
        "status": "pass",
        "summary": "ok",
        "verdict": "pass",
        "findings": [finding],
    }
    errors = [
        e
        for e in _validator().iter_errors(envelope)
        if list(e.absolute_path) == ["findings", 0]
    ]
    assert errors == []


def test_finding_with_an_unknown_origin_is_rejected():
    finding = _base_finding()
    finding["origin"] = "not-a-real-origin"
    envelope = {
        "schema": "tp-run-full-design/audit-return/v1",
        "slot": "design-audit",
        "status": "pass",
        "summary": "ok",
        "verdict": "pass",
        "findings": [finding],
    }
    errors = [
        e
        for e in _validator().iter_errors(envelope)
        if list(e.absolute_path) == ["findings", 0, "origin"]
    ]
    assert len(errors) == 1
    assert errors[0].validator == "enum"


def test_finding_with_an_unknown_fragility_class_is_rejected():
    finding = _base_finding()
    finding["fragility_class"] = "not-a-real-class"
    envelope = {
        "schema": "tp-run-full-design/audit-return/v1",
        "slot": "design-audit",
        "status": "pass",
        "summary": "ok",
        "verdict": "pass",
        "findings": [finding],
    }
    errors = [
        e
        for e in _validator().iter_errors(envelope)
        if list(e.absolute_path) == ["findings", 0, "fragility_class"]
    ]
    assert len(errors) == 1
    assert errors[0].validator == "enum"
