"""Tests for model_policy — the `models` config reader, validator and alias map.

design: consumer-repo-parity (Task 7.1). `model_for` returns the validated
config value or the Opus-first defaults; `validate_models` drops a `design_run`
value outside its vocabulary (an alias or `claude-…` id, optionally `[1m]`) with a warning; `agent_alias` maps aliases and
`claude-<family>-…` ids (normalised) to the Agent enum, and anything else
(a local model, an old-style id) to None. No role accepts `inherit`; there is
no `audit` role.
Run with: python3 -m pytest skills/_shared/test_model_policy.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import model_policy as mp  # noqa: E402


# --- the vocabulary ----------------------------------------------------------

def test_agent_aliases_are_the_q2_call_time_enum():
    assert mp.AGENT_ALIASES == ("opus", "sonnet", "haiku", "fable")


def test_roles_excluding_audit():
    assert mp.ROLES == ("review", "fix", "classifier", "design_run")
    assert "audit" not in mp.ROLES


def test_defaults_are_opus_first():
    # design_run carries the 1M-context suffix (seat ruling 13): a bare `opus`
    # behind the claude-hybrid router gets 200k and compacts on turn one.
    assert mp.DEFAULTS == {
        "review": "opus",
        "fix": "opus",
        "classifier": "sonnet",
        "design_run": "sonnet[1m]",
    }


# --- model_for ---------------------------------------------------------------

def test_model_for_without_config_gives_defaults():
    assert mp.model_for("review", None) == "opus"
    assert mp.model_for("fix", {}) == "opus"
    assert mp.model_for("classifier", {"models": {}}) == "sonnet"
    assert mp.model_for("design_run", None) == "sonnet[1m]"


def test_model_for_returns_config_value_when_set():
    cfg = {"models": {"review": "sonnet"}}
    assert mp.model_for("review", cfg) == "sonnet"


def test_model_for_defaults_for_keys_not_set():
    cfg = {"models": {"review": "sonnet"}}
    assert mp.model_for("fix", cfg) == "opus"
    assert mp.model_for("classifier", cfg) == "sonnet"


def test_model_for_survives_a_schema_pruned_inherit():
    # load_repo_config pruned `review: inherit` away — the role is gone from
    # the block, so the default stands.
    cfg = {"models": {}}
    assert mp.model_for("review", cfg) == "opus"


def test_model_for_drops_a_raw_inherit_value():
    # A config that bypassed the schema still never yields `inherit`.
    cfg = {"models": {"review": "inherit"}}
    assert mp.model_for("review", cfg) == "opus"


def test_model_for_has_no_audit_role():
    with pytest.raises((ValueError, KeyError)):
        mp.model_for("audit", {})


# --- validate_models ---------------------------------------------------------

def test_validate_models_keeps_legal_values_and_warns_once_per_drop():
    block = {
        "review": "opus",
        "fix": "opus",
        "classifier": "sonnet",
        "design_run": "claude-opus-4-8",
    }
    out, warns = mp.validate_models(block)
    assert out == block and warns == []


def test_validate_models_keeps_fable_and_claude_family_ids():
    out, warns = mp.validate_models({"design_run": "fable"})
    assert out == {"design_run": "fable"} and warns == []
    out, warns = mp.validate_models({"design_run": "claude-fable-x"})
    assert out == {"design_run": "claude-fable-x"} and warns == []


def test_validate_models_drops_gpt5_and_inherit_with_one_warning_each():
    out, warns = mp.validate_models({"design_run": "gpt-5"})
    assert "design_run" not in out
    assert len(warns) == 1 and "design_run" in warns[0]
    out, warns = mp.validate_models({"design_run": "inherit"})
    assert "design_run" not in out
    assert len(warns) == 1 and "design_run" in warns[0]


def test_validate_models_drops_out_of_enum_agent_roles():
    out, warns = mp.validate_models({"classifier": "gpt-5"})
    assert "classifier" not in out and len(warns) == 1


def test_validate_models_accepts_a_non_dict_block():
    out, warns = mp.validate_models(None)
    assert out == {} and isinstance(warns, list)
    out, warns = mp.validate_models("opus")
    assert out == {} and isinstance(warns, list)


def test_validate_models_does_not_mutate_its_input():
    block = {"design_run": "gpt-5", "review": "opus"}
    mp.validate_models(block)
    assert block == {"design_run": "gpt-5", "review": "opus"}


# --- agent_alias -------------------------------------------------------------

@pytest.mark.parametrize(
    ("model", "alias"),
    [
        ("opus", "opus"),
        ("sonnet", "sonnet"),
        ("haiku", "haiku"),
        ("fable", "fable"),
        ("claude-opus-4-1", "opus"),
        ("claude-fable-x", "fable"),
        ("claude-sonnet-4-6", "sonnet"),
        ("claude-haiku-4-5", "haiku"),
        ("Opus", "opus"),
        ("Claude-Haiku-4-5", "haiku"),
        ("  opus  ", "opus"),
        # a trailing `[…]` context suffix is dropped (the one family normaliser)
        ("opus[1m]", "opus"),
        ("claude-opus-4-8[1m]", "opus"),
        ("Sonnet[1m]", "sonnet"),
    ],
)
def test_agent_alias_maps_aliases_and_claude_family_ids(model, alias):
    assert mp.agent_alias(model) == alias


@pytest.mark.parametrize(
    "model",
    [
        "qwen-coder",
        "claude-3-opus-20240229",
        "claude-opus",
        "gpt-5",
        "",
        None,
        "qwen-coder[1m]",
        "[1m]",
    ],
)
def test_agent_alias_returns_none_for_other_ids(model):
    assert mp.agent_alias(model) is None
