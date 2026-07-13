"""Schema tests for candidate.v1.json — the worker's structured response contract."""
import copy
import json
from pathlib import Path

import jsonschema
import pytest

SCHEMA_PATH = Path(__file__).parent.parent / "schemas" / "candidate.v1.json"


def _load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _valid_example() -> dict:
    return {
        "schema": "tp-run-full-design/candidate/v1",
        "candidate_id": "single",
        "branch": "candidate/my-slug/single",
        "sha": "a1b2c3d4e5f6071829304a5b6c7d8e9f0a1b2c3d",
        "summary": "Implemented the thing; tests pass.",
        "test_results": {"passed": 12, "failed": 0, "skipped": 0, "raw": "12 passed"},
        "telemetry": {"duration_ms": 4200, "tokens_used": 18500, "tool_calls": 47},
    }


def _validate(instance: dict) -> None:
    jsonschema.validate(instance=instance, schema=_load_schema())


def test_a_valid_example_validates_clean() -> None:
    _validate(_valid_example())


def test_b_missing_required_sha_raises() -> None:
    bad = _valid_example()
    del bad["sha"]
    with pytest.raises(jsonschema.ValidationError):
        _validate(bad)


def test_c_sha_not_40_hex_chars_raises() -> None:
    bad = _valid_example()
    bad["sha"] = "deadbeef"
    with pytest.raises(jsonschema.ValidationError):
        _validate(bad)


def test_d_branch_not_matching_pattern_raises() -> None:
    bad = _valid_example()
    bad["branch"] = "feature/my-slug"
    with pytest.raises(jsonschema.ValidationError):
        _validate(bad)


def test_e_test_results_passed_negative_raises() -> None:
    bad = copy.deepcopy(_valid_example())
    bad["test_results"]["passed"] = -1
    with pytest.raises(jsonschema.ValidationError):
        _validate(bad)


def test_f_telemetry_tokens_used_null_validates_clean() -> None:
    # Nested-agent workers cannot observe their own token usage; null is the
    # sentinel for "unknown." Schema accepts integer-or-null per known issue L10.
    ok = copy.deepcopy(_valid_example())
    ok["telemetry"]["tokens_used"] = None
    _validate(ok)


def test_g_telemetry_duration_ms_null_raises() -> None:
    # duration_ms and tool_calls are still integer-only — workers can always
    # observe wall-clock and their own tool invocations. The L10 relaxation is
    # narrowly scoped to tokens_used, which is the only genuinely unobservable
    # metric from inside a nested Agent context.
    bad = copy.deepcopy(_valid_example())
    bad["telemetry"]["duration_ms"] = None
    with pytest.raises(jsonschema.ValidationError):
        _validate(bad)


def test_h_telemetry_tool_calls_null_raises() -> None:
    bad = copy.deepcopy(_valid_example())
    bad["telemetry"]["tool_calls"] = None
    with pytest.raises(jsonschema.ValidationError):
        _validate(bad)
