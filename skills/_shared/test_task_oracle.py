"""test_task_oracle.py — the plan **Oracle** grammar and its pairing rule.

design: fragile-test-prevention (detailed-design-stages Part A)

Behaviour only: each Oracle type alone is ok, an unknown type / a duplicate / an
empty item / a pairing type without example is malformed with an error naming the
item, `none` is ok but only against `Targets: none`, and a canonical render
round-trips. The tables iterate `ORACLE_TYPES`, so a new type is covered the
moment the registry gains one. Pure: no git, no filesystem.
"""
from __future__ import annotations

import itertools

import pytest

import task_oracle

A = "pkg/test_a.py"

# The pairing types (property / metamorphic) need an accompanying `example`
# (the design's pairing rule), so "each type alone is ok" holds for the rest.
_NON_PAIRING = [t for t in task_oracle.ORACLE_TYPES if t not in task_oracle.PAIRING_TYPES]


@pytest.mark.parametrize("t", _NON_PAIRING)
def test_each_type_alone_is_ok(t):
    got = task_oracle.parse_oracle(t)
    assert (got["kind"], got["types"], got["errors"]) == ("ok", [t], [])


def test_two_types_in_any_order_are_ok():
    for field in ("example, property", "property, example"):
        got = task_oracle.parse_oracle(field)
        assert (got["kind"], sorted(got["types"]), got["errors"]) == (
            "ok", ["example", "property"], [])


def test_none_is_ok():
    got = task_oracle.parse_oracle("none")
    assert (got["kind"], got["types"], got["errors"]) == ("ok", [], [])


def test_absent_field_is_missing():
    got = task_oracle.parse_oracle(None)
    assert (got["kind"], got["types"], got["errors"]) == ("missing", [], [])


@pytest.mark.parametrize("field,wanted", [
    ("flaky", "'flaky'"),                  # unknown type, naming it
    ("example, example", "'example'"),     # duplicate, naming it
    ("example, , property", "''"),         # an empty item, naming it
    ("", "''"),                            # present but empty, naming it
])
def test_malformed_fields_are_malformed_and_name_the_item(field, wanted):
    got = task_oracle.parse_oracle(field)
    assert got["kind"] == "malformed"
    assert any(wanted in e for e in got["errors"])


@pytest.mark.parametrize("t", task_oracle.PAIRING_TYPES)
def test_pairing_type_without_example_is_malformed_and_names_it(t):
    got = task_oracle.parse_oracle(t)
    assert got["kind"] == "malformed"
    assert any(t in e and "example" in e for e in got["errors"])


def test_pairing_type_with_example_is_ok():
    for t in task_oracle.PAIRING_TYPES:
        got = task_oracle.parse_oracle(f"{t}, example")
        assert got["kind"] == "ok" and got["errors"] == [], t


def test_pair_refuses_oracle_none_with_real_targets():
    assert task_oracle.validate_pair(
        task_oracle.parse_oracle("none"), f"`{A}::test_x`")
    assert task_oracle.validate_pair(
        task_oracle.parse_oracle("none"), None)


def test_pair_allows_oracle_none_with_targets_none():
    assert task_oracle.validate_pair(
        task_oracle.parse_oracle("none"), "none") == []


def test_pair_silently_passes_a_real_oracle():
    for t in task_oracle.ORACLE_TYPES:
        field = t if t == "example" else f"example, {t}"
        assert task_oracle.validate_pair(
            task_oracle.parse_oracle(field), f"`{A}::test_x`") == []


def test_render_is_canonical_text():
    assert task_oracle.render_oracle(task_oracle.parse_oracle("none")) == "none"
    assert task_oracle.render_oracle(
        task_oracle.parse_oracle("property, example")) == "example, property"


def test_render_round_trips_over_all_type_subsets():
    for r in range(1, len(task_oracle.ORACLE_TYPES) + 1):
        for combo in itertools.combinations(task_oracle.ORACLE_TYPES, r):
            parsed = task_oracle.parse_oracle(", ".join(combo))
            again = task_oracle.parse_oracle(task_oracle.render_oracle(parsed))
            assert again["types"] == parsed["types"], combo
