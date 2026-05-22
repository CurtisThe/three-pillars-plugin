"""Tests for parse_candidate_response — extracts and validates a worker
agent's structured candidate.v1 response from a free-form text reply."""

import json

import pytest

from parse_candidate_response import (
    NoCandidateBlockError,
    SchemaValidationError,
    UnknownSchemaVersionError,
    parse_candidate_response,
)


def _valid_payload() -> dict:
    return {
        "schema": "tp-run-full-design/candidate/v1",
        "candidate_id": "c-001",
        "branch": "candidate/design-x/worker-a",
        "sha": "a" * 40,
        "summary": "added foo",
        "test_results": {"passed": 3, "failed": 0, "skipped": 0, "raw": "..."},
        "telemetry": {"duration_ms": 100, "tokens_used": 200, "tool_calls": 5},
    }


def _wrap(payload_text: str) -> str:
    return f"Here's my candidate:\n\n```json\n{payload_text}\n```\n\nDone."


def test_valid_response_returns_typed_dict():
    text = _wrap(json.dumps(_valid_payload()))
    result = parse_candidate_response(text)
    assert isinstance(result, dict)
    assert result["candidate_id"] == "c-001"
    assert result["schema"] == "tp-run-full-design/candidate/v1"
    assert result["test_results"]["passed"] == 3


def test_no_fenced_json_block_raises_no_candidate_block_error():
    text = "I thought about it but produced nothing structured."
    with pytest.raises(NoCandidateBlockError):
        parse_candidate_response(text)


def test_missing_required_field_raises_schema_validation_error():
    payload = _valid_payload()
    del payload["candidate_id"]
    text = _wrap(json.dumps(payload))
    with pytest.raises(SchemaValidationError):
        parse_candidate_response(text)


def test_unknown_schema_version_raises_unknown_schema_version_error():
    payload = _valid_payload()
    payload["schema"] = "tp-run-full-design/candidate/v999"
    text = _wrap(json.dumps(payload))
    with pytest.raises(UnknownSchemaVersionError):
        parse_candidate_response(text)


def test_multiple_fenced_blocks_takes_last_one():
    scratch = {"schema": "scratch", "note": "ignore me"}
    final = _valid_payload()
    text = (
        "First a scratchpad:\n"
        f"```json\n{json.dumps(scratch)}\n```\n"
        "Now the real answer:\n"
        f"```json\n{json.dumps(final)}\n```\n"
    )
    result = parse_candidate_response(text)
    assert result["candidate_id"] == final["candidate_id"]


def test_malformed_json_raises_schema_validation_error_wrapping_jsondecode():
    text = "Here:\n```json\n{not valid json,,,}\n```\n"
    with pytest.raises(SchemaValidationError) as excinfo:
        parse_candidate_response(text)
    cause = excinfo.value.__cause__
    assert isinstance(cause, json.JSONDecodeError)
