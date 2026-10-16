"""test_repo_config_fragility_keys.py — the config schema declares the fragility gate's keys.

design: fragile-test-prevention (detailed-design-stages.md Part C4, the schema bullet):
`fragility: {merge_predicate: bool (default true), strict: bool (default false),
gating_rules: [string]}` and `review.proof_dir: string`.

Oracle: ``schema``. The key checks read the schema with ``json.load`` and always run, as do
the stdlib `repo_config_load.prune_invalid` checks; only the jsonschema validate / reject
cases need the third-party validator, and each skips inside its own test when it is absent.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import repo_config_load as rcl  # noqa: E402

SCHEMA_PATH = Path(__file__).resolve().parent / "repo-config.schema.json"


def _schema() -> dict:
    with SCHEMA_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def _props(block: str) -> dict:
    return _schema()["properties"][block]["properties"]


def _config() -> dict:
    return {"schema_version": 1,
            "fragility": {"merge_predicate": False, "strict": True,
                          "gating_rules": ["golden-hash"]},
            "review": {"proof_dir": "/srv/review-proof"}}


# --- the declared keys (json.load; always run) -----------------------------------------

@pytest.mark.parametrize("key,default", [("merge_predicate", True), ("strict", False)])
def test_the_fragility_booleans_are_declared_with_their_defaults(key, default):
    spec = _props("fragility")[key]
    assert spec["type"] == "boolean"
    assert spec["default"] is default


def test_fragility_gating_rules_is_a_string_array():
    spec = _props("fragility")["gating_rules"]
    assert spec["type"] == "array"
    assert spec["items"] == {"type": "string"}


def test_review_proof_dir_is_a_string():
    assert _props("review")["proof_dir"]["type"] == "string"


def test_the_fragility_block_is_closed():
    assert _schema()["properties"]["fragility"]["additionalProperties"] is False


# --- the shipped stdlib validator (always run) -----------------------------------------

def test_prune_keeps_every_new_key():
    pruned, warnings = rcl.prune_invalid(_config(), _schema())
    assert warnings == []
    assert pruned == _config()


def test_prune_drops_an_unknown_fragility_key():
    cfg = _config()
    cfg["fragility"]["loud"] = True
    pruned, warnings = rcl.prune_invalid(cfg, _schema())
    assert "loud" not in pruned["fragility"]
    assert pruned["fragility"]["merge_predicate"] is False
    assert len(warnings) == 1


# --- jsonschema (importorskip inside each test) ----------------------------------------

def _validator():
    jsonschema = pytest.importorskip("jsonschema")
    schema = _schema()
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


def test_jsonschema_accepts_the_new_keys():
    assert list(_validator().iter_errors(_config())) == []


def test_jsonschema_rejects_an_unknown_fragility_key():
    cfg = _config()
    cfg["fragility"]["loud"] = True
    errors = list(_validator().iter_errors(cfg))
    assert [e.validator for e in errors] == ["additionalProperties"]
    assert list(errors[0].absolute_path) == ["fragility"]


@pytest.mark.parametrize("block,key,value", [
    ("fragility", "merge_predicate", "yes"),
    ("review", "proof_dir", 5),
])
def test_jsonschema_rejects_a_wrong_type(block, key, value):
    cfg = _config()
    cfg[block][key] = value
    errors = list(_validator().iter_errors(cfg))
    assert [list(e.absolute_path) for e in errors] == [[block, key]]
