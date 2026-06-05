"""Tests for repo-config.schema.json — JSON Schema invariants for .three-pillars/config.json.

Run with: pytest skills/_shared/test_repo_config.py -q
"""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

SCHEMA_PATH = Path(__file__).parent / "repo-config.schema.json"


@pytest.fixture(scope="module")
def schema():
    return json.loads(SCHEMA_PATH.read_text())


@pytest.fixture(scope="module")
def validator(schema):
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _complete_config():
    return {
        "schema_version": 1,
        "migration": {
            "completed_at": "2026-05-16T05:30:00Z",
            "from_layout": "docs+tdd",
        },
        "branch_protection": {
            "offered_at": "2026-05-16T05:30:00Z",
            "applied_at": "2026-05-16T05:30:00Z",
            "declined": False,
            "profile": "team-pr-1approval-noforce",
        },
    }


def test_schema_validates_complete_config(validator):
    validator.validate(_complete_config())


def test_schema_rejects_missing_schema_version(validator):
    cfg = _complete_config()
    del cfg["schema_version"]
    with pytest.raises(ValidationError):
        validator.validate(cfg)


def test_schema_rejects_unknown_top_level_keys(validator):
    cfg = _complete_config()
    cfg["unknown_key"] = "boom"
    with pytest.raises(ValidationError):
        validator.validate(cfg)


def test_schema_rejects_unknown_keys_inside_migration(validator):
    cfg = _complete_config()
    cfg["migration"]["mystery"] = "x"
    with pytest.raises(ValidationError):
        validator.validate(cfg)


def test_schema_rejects_unknown_keys_inside_branch_protection(validator):
    cfg = _complete_config()
    cfg["branch_protection"]["extra"] = True
    with pytest.raises(ValidationError):
        validator.validate(cfg)


def test_migration_from_layout_accepts_known_values_only(validator):
    cfg = _complete_config()
    cfg["migration"]["from_layout"] = "docs+tdd"
    validator.validate(cfg)
    cfg["migration"]["from_layout"] = None
    validator.validate(cfg)
    cfg["migration"]["from_layout"] = "future-layout"
    with pytest.raises(ValidationError):
        validator.validate(cfg)


def test_branch_protection_declined_defaults_false(schema):
    spec = schema["properties"]["branch_protection"]["properties"]["declined"]
    assert spec.get("default") is False
    assert spec["type"] == "boolean"


def test_branch_protection_profile_constrained_to_known_set(validator):
    cfg = _complete_config()
    cfg["branch_protection"]["profile"] = "team-pr-1approval-noforce"
    validator.validate(cfg)
    cfg["branch_protection"]["profile"] = None
    validator.validate(cfg)
    cfg["branch_protection"]["profile"] = "solo-no-protection"
    with pytest.raises(ValidationError):
        validator.validate(cfg)


def test_schema_version_2_or_higher_rejected_as_unsupported(validator):
    cfg = _complete_config()
    cfg["schema_version"] = 2
    with pytest.raises(ValidationError):
        validator.validate(cfg)
    cfg["schema_version"] = 0
    with pytest.raises(ValidationError):
        validator.validate(cfg)


# -------- Task 1.4: pdw subsection (parallel-design-worktrees) --------

def test_pdw_subsection_validates_complete_config(validator):
    cfg = {
        "schema_version": 1,
        "pdw": {
            "guards": {"diff_growth_multiplier": 3, "k_consecutive": 3},
            "comment_url_allowlist": [],
            "runner_backend": {"type": "claude"},
        },
    }
    validator.validate(cfg)


def test_pdw_rejects_unknown_property(validator):
    cfg = {
        "schema_version": 1,
        "pdw": {
            "guards": {"diff_growth_multiplier": 3, "k_consecutive": 3},
            "comment_url_allowlist": [],
            "runner_backend": {"type": "claude"},
            "rogue_field": True,
        },
    }
    with pytest.raises(ValidationError):
        validator.validate(cfg)


def test_pdw_runner_backend_type_constrained_to_claude(validator):
    """Unknown `pdw.runner_backend.type` values fail at validation, not at
    runtime via `run_supervisor._wrap_slash`'s NotImplementedError."""
    cfg = {
        "schema_version": 1,
        "pdw": {
            "guards": {"diff_growth_multiplier": 3, "k_consecutive": 3},
            "comment_url_allowlist": [],
            "runner_backend": {"type": "claude"},
        },
    }
    validator.validate(cfg)  # baseline passes

    cfg["pdw"]["runner_backend"]["type"] = "bedrock"
    with pytest.raises(ValidationError):
        validator.validate(cfg)
