"""Tests for the repo config key plan_audit.test_helpers (design local-sized-tasks, Task 2.2).

The key is an array of non-empty strings: a valid config survives
repo_config_load.prune_invalid whole with no warnings, an empty-string item and a
non-list value each warn for `plan_audit.test_helpers`, and the shipped schema
agrees with the prune (jsonschema parity).
Run with: python3 -m pytest skills/_shared/test_repo_config_test_helpers_key.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import repo_config_load as rcl  # noqa: E402

SCHEMA = json.loads(
    (Path(__file__).resolve().parent / "repo-config.schema.json").read_text(encoding="utf-8")
)

GOOD = {"schema_version": 1, "plan_audit": {"test_helpers": ["my_fixture"]}}
EMPTY_ITEM = {"schema_version": 1, "plan_audit": {"test_helpers": [""]}}
NOT_A_LIST = {"schema_version": 1, "plan_audit": {"test_helpers": "my_fixture"}}


# --- prune_invalid ------------------------------------------------------------

def test_valid_test_helpers_survives_whole():
    got, warns = rcl.prune_invalid(dict(GOOD), SCHEMA)
    assert got == GOOD
    assert warns == []


@pytest.mark.parametrize("cfg", [EMPTY_ITEM, NOT_A_LIST])
def test_bad_test_helpers_warns_with_the_dotted_key(cfg):
    _, warns = rcl.prune_invalid(dict(cfg), SCHEMA)
    assert any("plan_audit.test_helpers" in w for w in warns)


# --- jsonschema parity --------------------------------------------------------

def test_schema_validates_the_key_as_jsonschema_does_the_prune():
    jsonschema = pytest.importorskip("jsonschema")
    validator = jsonschema.Draft202012Validator(SCHEMA)
    jsonschema.Draft202012Validator.check_schema(SCHEMA)
    assert validator.is_valid(GOOD)
    assert not validator.is_valid(EMPTY_ITEM)
    assert not validator.is_valid(NOT_A_LIST)
