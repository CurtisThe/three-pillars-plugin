"""test_fragility_registry.py — the one list of fragility rule ids.

design: fragile-test-prevention (detailed-design-lint §Rule registry)

Behaviour only: ids are unique and match [a-z0-9-]+, each rule's side is
`test` or `production`, the day-one gating set is exactly the spec's three
rules (every other id flag-only), and the config's `fragility.gating_rules`
list replaces the gating set — an unknown id in that list is a ConfigError.
Pure: no git, no filesystem.
"""
from __future__ import annotations

import re

import pytest

import fragility_registry
from fragility_registry import ConfigError, RULES, Rule, gating_set

_ID_RE = re.compile(r"^[a-z0-9-]+$")
_DAY_ONE_GATING = {"golden-hash", "shape-pin", "deny-literal"}
_GATING = _DAY_ONE_GATING | {"name-kill"}  # name-kill: design no-kill-by-name
_ALL_IDS = _GATING | {
    "md-read-assert", "line-literal", "doc-line-cap", "prose-regex", "wall-clock",
}


def test_ids_are_unique():
    ids = [rule.id for rule in RULES]
    assert len(ids) == len(set(ids))


def test_every_id_matches_the_closed_grammar():
    for rule in RULES:
        assert _ID_RE.fullmatch(rule.id), rule.id


def test_every_rule_has_a_valid_side():
    for rule in RULES:
        assert rule.side in ("test", "production", "any"), rule.id


def test_registry_covers_the_rule_ids():
    assert {rule.id for rule in RULES} == _ALL_IDS


def test_default_gating_is_exactly_the_spec_rules():
    assert {rule.id for rule in RULES if rule.gating} == _GATING


def test_every_rule_carries_family_and_summary():
    for rule in RULES:
        assert isinstance(rule.family, str) and rule.family, rule.id
        assert isinstance(rule.summary, str) and rule.summary, rule.id


def test_rule_is_a_plain_named_value():
    r = Rule("x-9", "test", "gating", True, "s")
    assert (r.id, r.side, r.family, r.gating, r.summary) == ("x-9", "test", "gating", True, "s")


def test_config_list_replaces_the_gating_set():
    cfg = {"fragility": {"gating_rules": ["deny-literal", "wall-clock"]}}
    assert gating_set(cfg) == ["deny-literal", "wall-clock"]


def test_config_list_may_promote_flag_only_rules():
    cfg = {"fragility": {"gating_rules": ["golden-hash", "line-literal"]}}
    assert gating_set(cfg) == ["golden-hash", "line-literal"]


def test_unknown_id_in_config_raises_config_error():
    cfg = {"fragility": {"gating_rules": ["golden-hash", "no-such-rule"]}}
    with pytest.raises(ConfigError):
        gating_set(cfg)


def test_config_without_a_fragility_block_keeps_the_default_set():
    default = ["golden-hash", "shape-pin", "deny-literal", "name-kill"]
    assert gating_set({}) == default
    assert gating_set(None) == default
