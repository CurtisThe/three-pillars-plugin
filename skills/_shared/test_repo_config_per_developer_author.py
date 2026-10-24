"""Tests for `github.per_developer_author` in repo-config.schema.json.

design: per-developer-automation-account, Task 1.1 (behaviours 5 and 7, config prune)

The key is an enum `"off" | "self"`. The stdlib prune keeps both values with no warning and
drops anything else with one warning naming the key, so a bad value reads as `off` at the gate.

Run with: pytest skills/_shared/test_repo_config_per_developer_author.py -q
"""
import json
from pathlib import Path

import pytest

import repo_config_load as rcl

SCHEMA = json.loads(
    (Path(__file__).parent / "repo-config.schema.json").read_text(encoding="utf-8"))


def _config(value):
    return {"schema_version": 1, "github": {"per_developer_author": value}}


@pytest.mark.parametrize("value", ["self", "off"])
def test_a_valid_value_is_kept_with_no_warning(value):
    pruned, warnings = rcl.prune_invalid(_config(value), SCHEMA)
    assert pruned["github"]["per_developer_author"] == value
    assert warnings == []


@pytest.mark.parametrize("value", ["own-bot", True])
def test_an_invalid_value_is_dropped_with_one_warning_naming_the_key(value):
    pruned, warnings = rcl.prune_invalid(_config(value), SCHEMA)
    assert "per_developer_author" not in pruned.get("github", {})
    assert len([w for w in warnings if "github.per_developer_author" in w]) == 1
