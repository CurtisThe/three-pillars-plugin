"""Tests for design_run_backend.py — the design-run backend selector.

design: main-thread-direct-backend (Task 1.4, S4). `resolve` answers which
backend a design-run window starts on (the `--direct` flag, then the repo's
`design_run_backend` key, else today's `route`). The role that goes in front of
`claude` for a `direct` launch is `design_run_role`'s (launch-role-precedence), and
`seat_assignment` is gone. The schema check is the jsonschema one (`importorskip`);
the prune check goes through the real loader against the shipped schema.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_SHARED = Path(__file__).resolve().parent
sys.path.insert(0, str(_SHARED))

import design_run_backend as drb  # noqa: E402
import repo_config_load as rcl  # noqa: E402

SCHEMA = json.loads((_SHARED / "repo-config.schema.json").read_text(encoding="utf-8"))
DOC = _SHARED / "repo-config.md"


def test_vocabulary():
    assert drb.BACKENDS == ("route", "direct")
    assert drb.DEFAULT_BACKEND == "route"


def test_the_role_assignment_moved_to_design_run_role():
    for gone in ("seat_assignment", "SEAT_ROLE_ENV", "SEAT_ROLE"):
        assert not hasattr(drb, gone)


@pytest.mark.parametrize("cfg,direct,want", [
    ({}, False, "route"),
    ({"design_run_backend": "direct"}, False, "direct"),
    ({}, True, "direct"),
    ({"design_run_backend": "route"}, False, "route"),
    ({"design_run_backend": "route"}, True, "direct"),
    ({"design_run_backend": "hybrid"}, False, "route"),  # the loader prunes it
    ({"design_run_backend": True}, False, "route"),
    ({"models": {"design_run": "opus"}}, False, "route"),  # not the model key
    (None, False, "route"),
])
def test_resolve(cfg, direct, want):
    assert drb.resolve(cfg, direct=direct) == want


def test_resolve_returns_a_declared_backend():
    for cfg in ({}, {"design_run_backend": "hybrid"}, {"design_run_backend": "direct"}):
        for direct in (False, True):
            assert drb.resolve(cfg, direct=direct) in drb.BACKENDS


def test_a_bad_config_value_is_pruned_and_falls_back_to_route():
    pruned, warnings = rcl.prune_invalid(
        {"schema_version": 1, "design_run_backend": "hybrid"}, SCHEMA)
    assert "design_run_backend" not in pruned
    assert any("design_run_backend" in w for w in warnings)
    assert drb.resolve(pruned, direct=False) == "route"


@pytest.fixture(scope="module")
def validator():
    jsonschema = pytest.importorskip("jsonschema")
    v = jsonschema.Draft202012Validator(SCHEMA)
    jsonschema.Draft202012Validator.check_schema(SCHEMA)
    return v


@pytest.mark.parametrize("value", ["route", "direct"])
def test_schema_accepts_the_backends(validator, value):
    validator.validate({"schema_version": 1, "design_run_backend": value})


@pytest.mark.parametrize("value", ["hybrid", "DIRECT", True, 1, None, ["direct"]])
def test_schema_rejects_anything_else(validator, value):
    jsonschema = pytest.importorskip("jsonschema")
    with pytest.raises(jsonschema.ValidationError):
        validator.validate({"schema_version": 1, "design_run_backend": value})


def test_schema_key_is_a_top_level_sibling_of_models():
    props = SCHEMA["properties"]
    assert props["design_run_backend"]["type"] == "string"
    assert props["design_run_backend"]["enum"] == list(drb.BACKENDS)
    assert props["design_run_backend"].get("default") == "route"
    assert "models" in props and "design_run" in props["models"]["properties"]


def test_doc_names_the_key_its_values_and_the_gate():
    doc = DOC.read_text(encoding="utf-8")
    assert "design_run_backend" in doc
    for value in drb.BACKENDS:
        assert f'"{value}"' in doc
    assert "decisions.md" in doc
