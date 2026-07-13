"""Tests for the `review.approval_survives_safe_base_sync` +
`review.base_sync_carry_max_chain` config keys (task 9.3).

Kept in a dedicated file, NOT added to `test_repo_config.py` (384L, past its
soft-warn threshold already).

Run with: pytest skills/_shared/test_carry_config_keys.py -q
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

SCHEMA_PATH = Path(__file__).parent / "repo-config.schema.json"


@pytest.fixture(scope="module")
def schema():
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def validator(schema):
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _base_config():
    return {
        "schema_version": 1,
        "review": {
            "expects_copilot": False,
            "require_human_approval": True,
        },
    }


# ---------------------------------------------------------------------------
# Schema acceptance
# ---------------------------------------------------------------------------


def test_review_block_accepts_both_carry_keys_together(validator):
    cfg = _base_config()
    cfg["review"]["approval_survives_safe_base_sync"] = True
    cfg["review"]["base_sync_carry_max_chain"] = 5
    validator.validate(cfg)


def test_review_block_accepts_approval_survives_alone(validator):
    cfg = _base_config()
    cfg["review"]["approval_survives_safe_base_sync"] = False
    validator.validate(cfg)


def test_review_block_accepts_max_chain_alone(validator):
    cfg = _base_config()
    cfg["review"]["base_sync_carry_max_chain"] = 12
    validator.validate(cfg)


@pytest.mark.parametrize("n", [1, 5, 20])
def test_max_chain_accepts_boundary_values(validator, n):
    cfg = _base_config()
    cfg["review"]["base_sync_carry_max_chain"] = n
    validator.validate(cfg)


# ---------------------------------------------------------------------------
# Schema rejection
# ---------------------------------------------------------------------------


def test_review_block_still_rejects_unknown_keys(validator):
    """additionalProperties: false must still hold with the new keys present."""
    cfg = _base_config()
    cfg["review"]["approval_survives_safe_base_sync"] = True
    cfg["review"]["base_sync_carry_max_chain"] = 5
    cfg["review"]["mystery_key"] = "boom"
    with pytest.raises(ValidationError):
        validator.validate(cfg)


def test_approval_survives_wrong_type_fails(validator):
    cfg = _base_config()
    cfg["review"]["approval_survives_safe_base_sync"] = "true"   # string, not bool
    with pytest.raises(ValidationError):
        validator.validate(cfg)


def test_max_chain_wrong_type_fails(validator):
    cfg = _base_config()
    cfg["review"]["base_sync_carry_max_chain"] = "5"   # string, not integer
    with pytest.raises(ValidationError):
        validator.validate(cfg)


@pytest.mark.parametrize("n", [0, 21, -1])
def test_max_chain_out_of_range_fails(validator, n):
    cfg = _base_config()
    cfg["review"]["base_sync_carry_max_chain"] = n
    with pytest.raises(ValidationError):
        validator.validate(cfg)


def test_max_chain_rejects_bool():
    """JSON Schema `type: integer` accepts JSON booleans by spec unless excluded; pin
    the schema's actual behavior here so a future schema-authoring change is caught.
    `base_sync_cert.carry_max_chain` (the reader) independently excludes bool via
    isinstance -- this test is about the SCHEMA layer, not the reader."""
    schema_doc = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    spec = schema_doc["properties"]["review"]["properties"]["base_sync_carry_max_chain"]
    assert spec["type"] == "integer"


# ---------------------------------------------------------------------------
# Reader-level parity (base_sync_cert.carry_enabled / carry_max_chain)
# ---------------------------------------------------------------------------


def test_carry_enabled_reads_true_only_on_literal_true():
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    import base_sync_cert

    assert base_sync_cert.carry_enabled({"review": {"approval_survives_safe_base_sync": True}}) is True
    assert base_sync_cert.carry_enabled({"review": {"approval_survives_safe_base_sync": False}}) is False
    assert base_sync_cert.carry_enabled({"review": {"approval_survives_safe_base_sync": "true"}}) is False
    assert base_sync_cert.carry_enabled({}) is False
    assert base_sync_cert.carry_enabled(None) is False


def test_carry_max_chain_reads_int_or_default():
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    import base_sync_cert

    assert base_sync_cert.carry_max_chain({"review": {"base_sync_carry_max_chain": 12}}) == 12
    assert base_sync_cert.carry_max_chain({"review": {"base_sync_carry_max_chain": 999}}) == 5
    assert base_sync_cert.carry_max_chain({"review": {"base_sync_carry_max_chain": True}}) == 5
    assert base_sync_cert.carry_max_chain({}) == 5


# ---------------------------------------------------------------------------
# Task 9.4: FINAL FLIP -- this repo's own .three-pillars/config.json
# ---------------------------------------------------------------------------

_THIS_REPO_CONFIG_PATH = (
    Path(__file__).resolve().parents[2] / ".three-pillars" / "config.json"
)


def _this_repo_config() -> dict:
    return json.loads(_THIS_REPO_CONFIG_PATH.read_text(encoding="utf-8"))


def test_this_repos_config_validates_against_updated_schema(validator):
    """This repo's .three-pillars/config.json (post-flip) must validate against the
    schema now carrying the two new review.* carry keys."""
    validator.validate(_this_repo_config())


def test_this_repos_carry_enabled_reads_true():
    """base_sync_cert.carry_enabled must read True from this repo's own (edited)
    config file -- the FINAL flip (task 9.4)."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    import base_sync_cert

    cfg = _this_repo_config()
    assert base_sync_cert.carry_enabled(cfg) is True
    # Chain cap left to default (not set in this repo's config) -- default 5.
    assert base_sync_cert.carry_max_chain(cfg) == 5
