"""Tests for `pdw.guards` and `review.angles` in repo-config.schema.json.

design: iterate-convergence-budget (Task 3.2). Split from `test_repo_config.py`
per the file-size caps.
"""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

SCHEMA_PATH = Path(__file__).parent / "repo-config.schema.json"


@pytest.fixture(scope="module")
def validator():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _guards(**kw):
    return {"schema_version": 1, "pdw": {"guards": kw}}


def test_pdw_guards_accepts_budget_keys(validator):
    validator.validate(_guards(round_cap=6, growth_multiplier=1.5, test_code_ratio=3.0,
                               ratio_floor_lines=100, wall_clock_sec=14400, k_consecutive=3))


def test_pdw_guards_still_accepts_deprecated_diff_growth_multiplier(validator):
    validator.validate(_guards(diff_growth_multiplier=3))


@pytest.mark.parametrize("key,bad", [
    ("round_cap", 0), ("round_cap", 1.5), ("growth_multiplier", 1), ("growth_multiplier", 0.5),
    ("test_code_ratio", 0), ("ratio_floor_lines", -1), ("ratio_floor_lines", 2.5),
    ("wall_clock_sec", 0),
])
def test_pdw_guards_bounds(validator, key, bad):
    with pytest.raises(ValidationError):
        validator.validate(_guards(**{key: bad}))


def test_review_angles_shape(validator):
    angle = {"name": "correctness", "prompt": "p", "role": "confirmer", "model": "opus"}
    validator.validate({"schema_version": 1, "review": {"angles": [angle]}})
    for broken in ({k: v for k, v in angle.items() if k != "model"},
                   dict(angle, extra=1)):
        with pytest.raises(ValidationError):
            validator.validate({"schema_version": 1, "review": {"angles": [broken]}})
