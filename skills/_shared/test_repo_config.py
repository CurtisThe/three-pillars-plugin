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


# --- ci subsection (self-hosted-ci-runner: no-GitHub-CI opt-out) ---

def test_ci_subsection_validates(validator):
    cfg = _complete_config()
    cfg["ci"] = {"expects_github_checks": False}
    validator.validate(cfg)


def test_ci_rejects_unknown_key(validator):
    cfg = _complete_config()
    cfg["ci"] = {"bogus": 1}
    with pytest.raises(ValidationError):
        validator.validate(cfg)


def test_ci_expects_github_checks_must_be_bool(validator):
    cfg = _complete_config()
    cfg["ci"] = {"expects_github_checks": "no"}
    with pytest.raises(ValidationError):
        validator.validate(cfg)


def test_config_without_ci_still_validates(validator):
    # backward compat: a config with no `ci` subsection is valid (default applies in code)
    cfg = _complete_config()
    assert "ci" not in cfg
    validator.validate(cfg)


def test_this_repo_opts_out_of_github_ci(validator):
    # This repo runs CI locally — its committed config must opt out and stay schema-valid.
    repo_cfg_path = Path(__file__).resolve().parents[2] / ".three-pillars" / "config.json"
    cfg = json.loads(repo_cfg_path.read_text())
    validator.validate(cfg)
    assert cfg.get("ci", {}).get("expects_github_checks") is False


# --- review subsection (Copilot-optional two-stable terminal) ---

def test_review_subsection_validates(validator):
    cfg = _complete_config()
    cfg["review"] = {"expects_copilot": False}
    validator.validate(cfg)


def test_review_rejects_unknown_key(validator):
    cfg = _complete_config()
    cfg["review"] = {"bogus": 1}
    with pytest.raises(ValidationError):
        validator.validate(cfg)


def test_review_expects_copilot_must_be_bool(validator):
    cfg = _complete_config()
    cfg["review"] = {"expects_copilot": "no"}
    with pytest.raises(ValidationError):
        validator.validate(cfg)


def test_config_without_review_still_validates(validator):
    # backward compat: a config with no `review` subsection is valid (default true in code)
    cfg = _complete_config()
    assert "review" not in cfg
    validator.validate(cfg)


def test_this_repo_opts_out_of_copilot(validator):
    # This account has no Copilot entitlement — its committed config must declare it so
    # the tp-pr-iterate loop converges on the /code-review arm instead of cap-exhausting.
    repo_cfg_path = Path(__file__).resolve().parents[2] / ".three-pillars" / "config.json"
    cfg = json.loads(repo_cfg_path.read_text())
    validator.validate(cfg)
    assert cfg.get("review", {}).get("expects_copilot") is False


# --- fleet subsection (worktree-isolation-guards tunable) ---

def test_fleet_subsection_validates(validator):
    cfg = _complete_config()
    cfg["fleet"] = {"diff_balloon_factor": 5}
    validator.validate(cfg)


def test_fleet_rejects_unknown_key(validator):
    cfg = _complete_config()
    cfg["fleet"] = {"diff_balloon_factor": 5, "bogus": True}
    with pytest.raises(ValidationError):
        validator.validate(cfg)


# --- review.require_human_approval + automation_identities (human-approval merge gate) ---

def test_require_human_approval_keys(schema):
    """Task 4.1 — the schema's review object must declare require_human_approval
    (boolean, default-true via description) and automation_identities (array of strings)."""
    review_props = schema["properties"]["review"]["properties"]

    assert "require_human_approval" in review_props, (
        "review must declare require_human_approval"
    )
    assert review_props["require_human_approval"]["type"] == "boolean"
    # default-true semantics are documented in the description (the code reads it strict-default)
    assert "default" in review_props["require_human_approval"]["description"].lower()

    assert "automation_identities" in review_props, (
        "review must declare automation_identities"
    )
    assert review_props["automation_identities"]["type"] == "array"
    assert review_props["automation_identities"]["items"]["type"] == "string"


def test_review_require_human_approval_validates(validator):
    cfg = _complete_config()
    cfg["review"] = {"expects_copilot": False, "require_human_approval": True}
    validator.validate(cfg)
    cfg["review"] = {"require_human_approval": False}
    validator.validate(cfg)


def test_review_require_human_approval_must_be_bool(validator):
    cfg = _complete_config()
    cfg["review"] = {"require_human_approval": "yes"}
    with pytest.raises(ValidationError):
        validator.validate(cfg)


def test_fleet_diff_balloon_factor_must_be_number(validator):
    cfg = _complete_config()
    cfg["fleet"] = {"diff_balloon_factor": "five"}
    with pytest.raises(ValidationError):
        validator.validate(cfg)


def test_review_automation_identities_validates(validator):
    cfg = _complete_config()
    cfg["review"] = {"automation_identities": ["svc-ci", "release-bot"]}
    validator.validate(cfg)


def test_review_automation_identities_must_be_string_array(validator):
    cfg = _complete_config()
    cfg["review"] = {"automation_identities": [1, 2]}
    with pytest.raises(ValidationError):
        validator.validate(cfg)


def test_config_without_fleet_still_validates(validator):
    # backward compat: a config with no `fleet` subsection is valid
    cfg = _complete_config()
    assert "fleet" not in cfg
    validator.validate(cfg)


def test_this_repo_declares_require_human_approval(validator):
    # This repo opts into the strict human-approval predicate explicitly.
    repo_cfg_path = Path(__file__).resolve().parents[2] / ".three-pillars" / "config.json"
    cfg = json.loads(repo_cfg_path.read_text())
    validator.validate(cfg)
    assert cfg.get("review", {}).get("require_human_approval") is True


# --- worktree_immunization subsection (worktree-residue-gc-and-bootstrap) ---

def test_worktree_immunization_subsection_validates(validator):
    """Schema accepts a full worktree_immunization block."""
    cfg = _complete_config()
    cfg["worktree_immunization"] = {
        "offered_at": "2026-06-12T10:00:00Z",
        "applied_at": "2026-06-12T10:01:00Z",
        "declined": False,
    }
    validator.validate(cfg)


def test_worktree_immunization_accepts_null_applied_at(validator):
    """Schema accepts null applied_at (not yet applied)."""
    cfg = _complete_config()
    cfg["worktree_immunization"] = {
        "offered_at": "2026-06-12T10:00:00Z",
        "applied_at": None,
        "declined": False,
    }
    validator.validate(cfg)


def test_worktree_immunization_declined_true_validates(validator):
    """Schema accepts declined=True with null applied_at."""
    cfg = _complete_config()
    cfg["worktree_immunization"] = {
        "offered_at": "2026-06-12T10:00:00Z",
        "applied_at": None,
        "declined": True,
    }
    validator.validate(cfg)


def test_worktree_immunization_rejects_unknown_keys(validator):
    """additionalProperties: false prevents unknown keys in the block."""
    cfg = _complete_config()
    cfg["worktree_immunization"] = {
        "offered_at": "2026-06-12T10:00:00Z",
        "applied_at": None,
        "declined": False,
        "extra_key": "boom",
    }
    with pytest.raises(ValidationError):
        validator.validate(cfg)


def test_config_without_worktree_immunization_still_validates(validator):
    """Backward compat: a config with no worktree_immunization block is valid."""
    cfg = _complete_config()
    assert "worktree_immunization" not in cfg
    validator.validate(cfg)


def test_worktree_immunization_declined_must_be_bool(validator):
    """Schema rejects non-boolean declined value."""
    cfg = _complete_config()
    cfg["worktree_immunization"] = {
        "offered_at": "2026-06-12T10:00:00Z",
        "applied_at": None,
        "declined": "yes",
    }
    with pytest.raises(ValidationError):
        validator.validate(cfg)
