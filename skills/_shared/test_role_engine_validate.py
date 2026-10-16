"""Tests for role_engine — the role → engine registry and validator.

design: local-role-routing (Task 1.1). The four engine roles (explainer-agent Task 7.1
adds `explainer`) are named ONCE, in `model_policy.ENGINE_ROLES`; `role_engine`
re-exports that same tuple object.
`validate` keeps legal `role_engines` entries and drops each out-of-vocabulary
role or engine with one warning, following `model_policy.validate_models`'
drop-and-warn pattern. A non-dict block is `({}, [])`.
Run with: TMPDIR=/home/curtis/t python3 -m pytest -n 4 skills/_shared/test_role_engine_validate.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import model_policy as mp  # noqa: E402
import role_engine as re_  # noqa: E402


# --- the vocabulary ---------------------------------------------------------

def test_engine_roles_are_named_once_in_model_policy():
    assert mp.ENGINE_ROLES == ("council_member", "review_finder", "context_scout", "explainer")


def test_role_engine_reexports_the_same_tuple_object():
    assert re_.ENGINE_ROLES is mp.ENGINE_ROLES


def test_engine_vocabulary_and_config_key():
    assert re_.ENGINES == ("local", "opus")
    assert re_.SONNET_ROW_EFFORT == "high"
    assert re_.CONFIG_KEY == "role_engines"


# --- validate: legal entries kept -------------------------------------------

def test_validate_keeps_legal_entries_with_no_warnings():
    block = {"council_member": "local", "review_finder": "opus"}
    assert re_.validate(block) == (block, [])


# --- validate: drops with one warning each ----------------------------------

def test_validate_drops_unknown_role_with_one_warning():
    kept, warnings = re_.validate({"synthesizer": "local"})
    assert kept == {}
    assert len(warnings) == 1
    assert "synthesizer" in warnings[0]


def test_validate_drops_out_of_vocabulary_engine_with_one_warning():
    kept, warnings = re_.validate({"council_member": "sonnet"})
    assert kept == {}
    assert len(warnings) == 1
    assert "council_member" in warnings[0]
    assert "sonnet" in warnings[0]


def test_validate_mixed_block_keeps_the_good_drops_the_bad_once():
    kept, warnings = re_.validate({"council_member": "local", "synthesizer": "opus"})
    assert kept == {"council_member": "local"}
    assert len(warnings) == 1
    assert "synthesizer" in warnings[0]


# --- validate: non-dict block -----------------------------------------------

def test_validate_non_dict_block_returns_empty():
    assert re_.validate("local") == ({}, [])
    assert re_.validate(None) == ({}, [])
