"""Two-step validation of the /council --orchestrator round-bundle return (§6, F2).

Step 1: validate the *bundle* wrapper via parse_tier_return against
council-round-bundle.v1.json — the wrapper carries its own schema const, so it
passes parse_tier_return's class-guard.

Step 2: validate each bundle["outputs"][i] against the per-round schema
(council-round1.v1 for round 1, council-round2.v1 for round 2) directly with a
jsonschema.Draft7Validator + the schemas-dir registry — the dict is already in
hand, so there is no second fenced-block extraction.

Also pins the positive class-guard: passing a bare round1/round2 envelope reply
to parse_tier_return against the matching round schema returns the dict without
raising. And the negative: passing the bundle wrapper reply to the round1 schema
raises UnknownSchemaVersionError (the wrapper carries the bundle const, not the
round const — the original F2 mismatch).

Production wiring is SKILL.md prose (Phase 4); parse_tier_return.py is byte-
unchanged — this test encodes the contract and is the regression guard.
"""

import json
from pathlib import Path

import jsonschema
import pytest
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT7

from parse_tier_return import parse_tier_return, UnknownSchemaVersionError

SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "schemas"
ROUND1 = SCHEMAS_DIR / "council-round1.v1.json"
ROUND2 = SCHEMAS_DIR / "council-round2.v1.json"
ROUND_BUNDLE = SCHEMAS_DIR / "council-round-bundle.v1.json"


def _registry() -> Registry:
    resources = []
    for p in SCHEMAS_DIR.glob("*.json"):
        schema = json.loads(p.read_text())
        if "$id" in schema:
            resources.append(
                (schema["$id"], Resource.from_contents(schema, default_specification=DRAFT7))
            )
    return Registry().with_resources(resources)


def _round1_envelope() -> dict:
    return {
        "schema": "tp-run-full-design/council-round1/v1",
        "member": "council-torvalds",
        "verdict": "pass-with-notes",
        "confidence": "high",
        "findings": [
            {
                "confidence": "medium",
                "category": "INCONSISTENT",
                "description": "task 2 field name drifts",
                "suggested_fix": "rename to match design",
            }
        ],
        "argument_summary": "Mostly sound; one drift in task 2.",
    }


def _round2_envelope() -> dict:
    return {
        "schema": "tp-run-full-design/council-round2/v1",
        "member": "council-ada",
        "position_held": "held",
        "counter_argument": "torvalds's finding 0 is valid; the rename is unintentional.",
        "challenged_finding_indices": [0],
    }


def _bundle(round_n: int, outputs: list[dict]) -> dict:
    return {
        "schema": "tp-run-full-design/council-round-bundle/v1",
        "round": round_n,
        "members": ["council-torvalds", "council-ada", "council-feynman"],
        "outputs": outputs,
    }


def _as_reply(obj: dict) -> str:
    return f"Here is my deliberation result.\n\n```json\n{json.dumps(obj)}\n```\n"


def _validate_member(out: dict, round_n: int) -> None:
    schema_path = ROUND1 if round_n == 1 else ROUND2
    schema = json.loads(schema_path.read_text())
    validator = jsonschema.Draft7Validator(schema, registry=_registry())
    error = jsonschema.exceptions.best_match(validator.iter_errors(out))
    if error is not None:
        raise jsonschema.exceptions.ValidationError(error.message)


# --------------------------------------------------------------------------- #
# PA1 — positive class-guard, round 1 and round 2 envelopes
# --------------------------------------------------------------------------- #
def test_pa1_round1_envelope_parses():
    reply = _as_reply(_round1_envelope())
    out = parse_tier_return(reply, ROUND1)
    assert out["schema"] == "tp-run-full-design/council-round1/v1"


def test_pa1_round2_envelope_parses():
    reply = _as_reply(_round2_envelope())
    out = parse_tier_return(reply, ROUND2)
    assert out["schema"] == "tp-run-full-design/council-round2/v1"


# --------------------------------------------------------------------------- #
# (1) bundle positive
# --------------------------------------------------------------------------- #
def test_bundle_positive_validates():
    bundle = _bundle(1, [_round1_envelope(), _round1_envelope(), _round1_envelope()])
    reply = _as_reply(bundle)
    out = parse_tier_return(reply, ROUND_BUNDLE)
    assert out["schema"] == "tp-run-full-design/council-round-bundle/v1"
    assert out["round"] == 1
    assert len(out["outputs"]) == 3


# --------------------------------------------------------------------------- #
# (2) wrapper-vs-round negative (F2)
# --------------------------------------------------------------------------- #
def test_bundle_against_round1_schema_raises():
    bundle = _bundle(1, [_round1_envelope()])
    reply = _as_reply(bundle)
    with pytest.raises(UnknownSchemaVersionError):
        parse_tier_return(reply, ROUND1)


# --------------------------------------------------------------------------- #
# (3) second-loop validation — each output validates against the round-N schema
# --------------------------------------------------------------------------- #
def test_second_loop_round1_outputs_validate():
    bundle = parse_tier_return(
        _as_reply(_bundle(1, [_round1_envelope(), _round1_envelope()])), ROUND_BUNDLE
    )
    for out in bundle["outputs"]:
        _validate_member(out, bundle["round"])  # must not raise


def test_second_loop_round2_outputs_validate():
    bundle = parse_tier_return(
        _as_reply(_bundle(2, [_round2_envelope(), _round2_envelope()])), ROUND_BUNDLE
    )
    assert bundle["round"] == 2
    for out in bundle["outputs"]:
        _validate_member(out, bundle["round"])  # must not raise


# --------------------------------------------------------------------------- #
# (4) second-loop negative — bundle parses but a member output is malformed
# --------------------------------------------------------------------------- #
def test_second_loop_negative_malformed_member():
    malformed = _round1_envelope()
    del malformed["findings"][0]["confidence"]  # F3 violation
    bundle = parse_tier_return(_as_reply(_bundle(1, [malformed])), ROUND_BUNDLE)
    # The bundle itself still parsed (outputs typed loosely as object)...
    assert bundle["round"] == 1
    # ...but the second-step per-member validation rejects the malformed output.
    with pytest.raises(jsonschema.exceptions.ValidationError):
        _validate_member(bundle["outputs"][0], bundle["round"])
