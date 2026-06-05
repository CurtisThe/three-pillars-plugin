"""Tests for tp-pr-iterate JSON schemas (v1).

These tests cover schema well-formedness and a few structural invariants
that the iterate-state / classified-comment schemas must satisfy:

* Both schemas must be valid JSON Schema 2020-12 documents.
* The iterate-state schema uses ``phase`` (not ``state``) as the
  enum-bearing field — see design.md Mi3.
* The iterate-state schema declares ``original_diff_lines`` (integer-typed)
  and ``last_loop_sha`` (nullable string) — see design-audit C2/C3.
"""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "schemas"
ITERATE_STATE_PATH = SCHEMAS_DIR / "iterate-state.v1.json"
CLASSIFIED_COMMENT_PATH = SCHEMAS_DIR / "classified-comment.v1.json"
NORMALIZED_FINDING_PATH = SCHEMAS_DIR / "normalized-finding.v1.json"


def _load(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def test_normalized_finding_schema_valid():
    """Enh.1: the dual-source normalized-finding schema is a valid 2020-12 doc."""
    schema = _load(NORMALIZED_FINDING_PATH)
    Draft202012Validator.check_schema(schema)


def test_normalized_finding_roundtrip_copilot():
    """A normalize_copilot() output validates against the schema."""
    import sys

    sys.path.insert(0, str(Path(__file__).parent))
    import review_merge  # noqa: E402

    out = review_merge.normalize_copilot(
        {"comment_id": 7, "thread_id": "RT_x", "path": "a.py",
         "line_range": [1, 2], "body": "x", "verdict": "structural"}
    )
    Draft202012Validator(_load(NORMALIZED_FINDING_PATH)).validate(out)


def test_iterate_state_schema_valid():
    schema = _load(ITERATE_STATE_PATH)
    Draft202012Validator.check_schema(schema)


def test_classified_comment_schema_valid():
    schema = _load(CLASSIFIED_COMMENT_PATH)
    Draft202012Validator.check_schema(schema)


def test_iterate_state_uses_phase_not_state_field():
    """Per design Mi3, the loop's lifecycle field is named ``phase``."""
    schema = _load(ITERATE_STATE_PATH)
    props = schema["properties"]
    assert "phase" in props, "iterate-state must declare a 'phase' property"
    assert "state" not in props, (
        "iterate-state must not declare a 'state' property (use 'phase' per Mi3)"
    )


def test_iterate_state_has_original_diff_lines_and_last_loop_sha():
    """Per design-audit C2/C3, both fields must be declared with the right shape."""
    schema = _load(ITERATE_STATE_PATH)
    props = schema["properties"]

    # C2: original_diff_lines must exist and accept integers.
    assert "original_diff_lines" in props, (
        "iterate-state must declare 'original_diff_lines' (audit C2)"
    )
    odl_type = props["original_diff_lines"].get("type")
    if isinstance(odl_type, list):
        assert "integer" in odl_type, (
            "original_diff_lines must allow integer values (audit C2)"
        )
    else:
        assert odl_type == "integer", (
            "original_diff_lines must be typed as integer (audit C2)"
        )

    # C3: last_loop_sha must exist and allow string or null.
    assert "last_loop_sha" in props, (
        "iterate-state must declare 'last_loop_sha' (audit C3)"
    )
    lls_type = props["last_loop_sha"].get("type")
    assert isinstance(lls_type, list), (
        "last_loop_sha must accept null in addition to string (audit C3)"
    )
    assert "string" in lls_type and "null" in lls_type, (
        "last_loop_sha type must include both 'string' and 'null' (audit C3)"
    )


def test_iterate_state_accepts_two_stable_fields():
    """Enh.1: iterate-state validates with resolved/seen thread ids + termination_reason."""
    schema = _load(ITERATE_STATE_PATH)
    instance = {
        "phase": "awaiting-human-review",
        "iteration": 3,
        "max_iterations": 8,
        "max_wall_clock_sec": 14400,
        "started_at": "2026-06-03T00:00:00Z",
        "transitions": [],
        "resolved_thread_ids": ["RT_1", "RT_2"],
        "seen_thread_ids": ["RT_1", "RT_2"],
        "termination_reason": "two-stable",
    }
    Draft202012Validator(schema).validate(instance)
