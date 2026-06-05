"""Tests for parse_tier_return — extracts and validates a dispatched tier
subagent's structured return envelope from a free-form text reply.

Mirrors test_parse_candidate_response.py: last-fenced-block extraction, the
three typed errors, status passthrough, return-clipping (only the parsed dict
survives), and parameterization across the generator/audit/handoff schemas.
"""

import json
from pathlib import Path

import pytest

from parse_tier_return import (
    NoReturnBlockError,
    SchemaValidationError,
    UnknownSchemaVersionError,
    parse_tier_return,
)

SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "schemas"
GENERATOR = SCHEMAS_DIR / "generator-return.v1.json"
AUDIT = SCHEMAS_DIR / "audit-return.v1.json"
HANDOFF = SCHEMAS_DIR / "handoff.v1.json"


def _generator_payload() -> dict:
    return {
        "schema": "tp-run-full-design/generator-return/v1",
        "slot": "design",
        "status": "pass",
        "summary": "wrote design.md",
        "artifact_paths": ["three-pillars-docs/tp-designs/x/design.md"],
    }


def _audit_payload() -> dict:
    return {
        "schema": "tp-run-full-design/audit-return/v1",
        "slot": "design-audit",
        "status": "needs-work",
        "summary": "audited design.md",
        "verdict": "needs-work",
        "findings": [
            {
                "confidence": "high",
                "category": "INCONSISTENT",
                "description": "field X drifts",
                "suggested_fix": "rename X to Y",
            }
        ],
    }


def _handoff_payload() -> dict:
    return {
        "schema": "tp-run-full-design/handoff/v1",
        "slot": "plan-audit",
        "attempt": 2,
        "partial_state": "rounds 1-2 done",
        "next_action": "resume round 3",
        "files_to_continue_with": ["three-pillars-docs/tp-designs/x/plan.md"],
        "remaining_budget_estimate": 120000,
    }


def _wrap(payload_text: str) -> str:
    return f"Here is my tier return:\n\n```json\n{payload_text}\n```\n\nDone."


# --------------------------------------------------------------------------- #
# Happy path per schema class
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "payload_fn,schema_path",
    [
        (_generator_payload, GENERATOR),
        (_audit_payload, AUDIT),
        (_handoff_payload, HANDOFF),
    ],
)
def test_valid_return_per_schema(payload_fn, schema_path):
    payload = payload_fn()
    result = parse_tier_return(_wrap(json.dumps(payload)), schema_path)
    assert isinstance(result, dict)
    assert result["schema"] == payload["schema"]


def test_status_passthrough():
    result = parse_tier_return(_wrap(json.dumps(_audit_payload())), AUDIT)
    assert result["status"] == "needs-work"


def test_return_clipping_discards_scratch():
    # The parser returns ONLY the validated dict — the surrounding scratch text
    # is gone (this is what lets the orchestrator clip the raw reply).
    payload = _generator_payload()
    text = "lots of reasoning scratch...\n" + _wrap(json.dumps(payload))
    result = parse_tier_return(text, GENERATOR)
    assert result == payload
    assert "scratch" not in json.dumps(result)


# --------------------------------------------------------------------------- #
# Error modes
# --------------------------------------------------------------------------- #
def test_no_fenced_block_raises():
    with pytest.raises(NoReturnBlockError):
        parse_tier_return("no structured block here", GENERATOR)


def test_malformed_json_raises_schema_validation_error():
    text = "Here:\n```json\n{not valid json,,,}\n```\n"
    with pytest.raises(SchemaValidationError) as excinfo:
        parse_tier_return(text, GENERATOR)
    assert isinstance(excinfo.value.__cause__, json.JSONDecodeError)


def test_unknown_schema_version_raises():
    payload = _generator_payload()
    payload["schema"] = "tp-run-full-design/generator-return/v999"
    with pytest.raises(UnknownSchemaVersionError):
        parse_tier_return(_wrap(json.dumps(payload)), GENERATOR)


def test_wrong_schema_class_raises_unknown_version():
    # An audit payload validated against the generator schema is the wrong class.
    with pytest.raises(UnknownSchemaVersionError):
        parse_tier_return(_wrap(json.dumps(_audit_payload())), GENERATOR)


def test_missing_required_field_raises_schema_validation_error():
    payload = _generator_payload()
    del payload["artifact_paths"]
    with pytest.raises(SchemaValidationError):
        parse_tier_return(_wrap(json.dumps(payload)), GENERATOR)


def test_base_field_violation_raises_schema_validation_error():
    # Proves allOf base is enforced through the parser, not just the schema test.
    payload = _generator_payload()
    payload["status"] = "not-a-real-status"
    with pytest.raises(SchemaValidationError):
        parse_tier_return(_wrap(json.dumps(payload)), GENERATOR)


def test_multiple_blocks_takes_last():
    scratch = {"schema": "scratch", "note": "ignore"}
    final = _generator_payload()
    text = (
        "scratch first:\n"
        f"```json\n{json.dumps(scratch)}\n```\n"
        "real answer:\n"
        f"```json\n{json.dumps(final)}\n```\n"
    )
    result = parse_tier_return(text, GENERATOR)
    assert result["artifact_paths"] == final["artifact_paths"]


def test_handoff_embedded_block():
    # A handoff checkpoint is stored at .handoffs/{slot}-{attempt}-{N}.md as a
    # markdown body with the handoff envelope embedded in a fenced json block.
    # parse_tier_return must extract + validate that embedded block straight from
    # the committed worklist file's contents, with surrounding prose/headings.
    payload = _handoff_payload()
    body = (
        "# Handoff — plan-audit attempt 2, checkpoint 3\n\n"
        "## Partial state\n"
        "Rounds 1-2 of the plan audit are complete; round 3 (council\n"
        "deliberation) has not started. Findings so far are written back into\n"
        "plan.md.\n\n"
        "## Resume from\n"
        "Re-dispatch the plan-audit slot pointed at the files below.\n\n"
        "```json\n"
        f"{json.dumps(payload, indent=2)}\n"
        "```\n"
    )
    result = parse_tier_return(body, HANDOFF)
    assert result == payload
    assert result["schema"] == "tp-run-full-design/handoff/v1"
    assert result["next_action"] == "resume round 3"
    assert result["files_to_continue_with"] == [
        "three-pillars-docs/tp-designs/x/plan.md"
    ]


def test_uppercase_json_fence_is_parsed():
    # LLMs vary the fence language tag's casing; an uppercase ```JSON block must
    # still be extracted (FENCED_JSON_RE is case-insensitive).
    payload = _generator_payload()
    text = "scratch\n```JSON\n" + json.dumps(payload) + "\n```\n"
    result = parse_tier_return(text, GENERATOR)
    assert result["slot"] == payload["slot"]
