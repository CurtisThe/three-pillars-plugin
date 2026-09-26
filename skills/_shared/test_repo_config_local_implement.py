"""Tests for the `local_implement` block in repo-config.schema.json.

design: local-implement-and-review (Task 3.1). Split from `test_repo_config.py`
per the file-size caps.
"""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

SCHEMA_PATH = Path(__file__).parent / "repo-config.schema.json"

FULL_BLOCK = {
    "enabled": True,
    "model": "haiku",
    "fallback_model": "sonnet",
    "full_design": False,
    "escalate": True,
    "max_retries": 2,
    "max_files": 3,
}


@pytest.fixture(scope="module")
def validator():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _cfg(block):
    return {"schema_version": 1, "local_implement": block}


def test_schema_accepts_block(validator):
    validator.validate(_cfg(dict(FULL_BLOCK)))
    validator.validate(_cfg({}))  # every key is optional: defaults fill the rest
    validator.validate(_cfg({"enabled": True}))


def test_schema_rejects_unknown_key(validator):
    with pytest.raises(ValidationError):
        validator.validate(_cfg(dict(FULL_BLOCK, unknown_key=1)))
    for key, bad in (("enabled", "yes"), ("full_design", 1), ("escalate", None),
                     ("model", ""), ("fallback_model", 3), ("max_retries", -1),
                     ("max_retries", 1.5), ("max_files", 0), ("max_files", True)):
        with pytest.raises(ValidationError):
            validator.validate(_cfg(dict(FULL_BLOCK, **{key: bad})))
    with pytest.raises(ValidationError):
        validator.validate(_cfg(["not", "an", "object"]))
