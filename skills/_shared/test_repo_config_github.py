"""Tests for the `github` block in repo-config.schema.json — pr-author-bot-account.

Split from `test_repo_config.py` (already at 384/500 lines) per the
file-size-caps convention: new github-specific schema tests live here.

Run with: pytest skills/_shared/test_repo_config_github.py -q
"""

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
    return {"schema_version": 1}


def _full_github_block():
    return {
        "pr_author_account": "CurtisTheBot",
        "used_for": "all-prs",
        "review_requests": ["CurtisThe"],
        "verified_at": "2026-07-03T00:00:00Z",
        "offered_at": "2026-07-03T00:00:00Z",
        "declined": False,
    }


def test_github_block_full_shape_validates(validator):
    cfg = _base_config()
    cfg["github"] = _full_github_block()
    validator.validate(cfg)


def test_github_block_null_account_validates(validator):
    cfg = _base_config()
    cfg["github"] = {
        "pr_author_account": None,
        "used_for": None,
        "review_requests": [],
        "verified_at": None,
        "offered_at": None,
        "declined": False,
    }
    validator.validate(cfg)


def test_github_used_for_rejects_unknown_value(validator):
    cfg = _base_config()
    block = _full_github_block()
    block["used_for"] = "sometimes"
    cfg["github"] = block
    with pytest.raises(ValidationError):
        validator.validate(cfg)


def test_github_used_for_accepts_autonomous_only(validator):
    cfg = _base_config()
    block = _full_github_block()
    block["used_for"] = "autonomous-only"
    cfg["github"] = block
    validator.validate(cfg)


def test_github_block_rejects_unknown_key(validator):
    cfg = _base_config()
    block = _full_github_block()
    block["bogus"] = True
    cfg["github"] = block
    with pytest.raises(ValidationError):
        validator.validate(cfg)


def test_github_review_requests_must_be_string_array(validator):
    cfg = _base_config()
    block = _full_github_block()
    block["review_requests"] = [1, 2]
    cfg["github"] = block
    with pytest.raises(ValidationError):
        validator.validate(cfg)


def test_config_without_github_still_validates(validator):
    cfg = _base_config()
    assert "github" not in cfg
    validator.validate(cfg)


def test_github_description_names_username_vs_credential_split(schema):
    """The block's description must name the username-committable /
    credential-never-here split (design.md security posture)."""
    desc = schema["properties"]["github"].get("description", "").lower()
    assert "username" in desc or "non-secret" in desc, (
        "github block description must name the committable username"
    )
    assert "keyring" in desc or "credential" in desc, (
        "github block description must name the credential-never-here rule"
    )


# --- Task 5.1: this-repo dogfood invariants ---------------------------------


def test_this_repo_github_block_is_automation_membered(validator):
    """UNCONDITIONAL — this repo must dogfood the pr-author bot account:
    github.pr_author_account non-null AND its lowercase form is present in
    review.automation_identities. Genuinely RED until Task 5.1's config edit
    lands (no skip guard — this pins the dogfood)."""
    repo_cfg_path = Path(__file__).resolve().parents[2] / ".three-pillars" / "config.json"
    cfg = json.loads(repo_cfg_path.read_text(encoding="utf-8"))
    validator.validate(cfg)

    account = cfg.get("github", {}).get("pr_author_account")
    assert account, "this repo's config.json must set github.pr_author_account"

    automation_identities = cfg.get("review", {}).get("automation_identities", [])
    assert account.lower() in automation_identities, (
        f"{account.lower()!r} must be present in review.automation_identities"
    )


def test_downstream_clone_github_block_generic_guard(validator):
    """Generic guard for downstream clones (not this-repo-specific): if a
    `github` block exists in the committed config, its account is
    automation-membered. Skip-if-absent."""
    repo_cfg_path = Path(__file__).resolve().parents[2] / ".three-pillars" / "config.json"
    cfg = json.loads(repo_cfg_path.read_text(encoding="utf-8"))
    validator.validate(cfg)

    github_block = cfg.get("github")
    if not github_block:
        pytest.skip("no github block present in this config")

    account = github_block.get("pr_author_account")
    if not account:
        pytest.skip("github block present but pr_author_account is null")

    automation_identities = cfg.get("review", {}).get("automation_identities", [])
    assert account.lower() in automation_identities, (
        "a configured pr_author_account must be present in review.automation_identities"
    )
