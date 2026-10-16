"""Tests for repo_config_load.prune_invalid — the keyword subset and jsonschema typing.

design: consumer-repo-parity (Task 1.1). The walk supports exactly the keyword
subset the shipped schema uses; typing is jsonschema's (draft 2020-12), not
Python's; the walk is post-order, so a node that fails after its children are
pruned is dropped whole — one warning per removal.
Run with: python3 -m pytest skills/_shared/test_repo_config_prune.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import repo_config_load as rcl  # noqa: E402

SCHEMA = json.loads(
    (Path(__file__).resolve().parent / "repo-config.schema.json").read_text(encoding="utf-8")
)
ANNOTATIONS = ("description", "default", "title", "$id", "$schema")


def prefix(path: str) -> str:
    """The stable prefix of a drop warning for `path`, whatever its reason."""
    return f"config: dropped {path} ("


# --- type: a name and a list with null ---------------------------------------

def test_type_name_prunes_only_failing_key():
    schema = {"type": "object", "properties": {"a": {"type": "integer"}, "b": {"type": "string"}}}
    assert rcl.prune_invalid({"a": 1, "b": "x"}, schema) == ({"a": 1, "b": "x"}, [])
    got, warns = rcl.prune_invalid({"a": "no", "b": "x"}, schema)
    assert got == {"b": "x"}
    assert len(warns) == 1 and warns[0].startswith(prefix("a"))


def test_type_list_with_null_accepts_both_and_drops_else():
    schema = {"type": "object", "properties": {"v": {"type": ["string", "null"]}}}
    assert rcl.prune_invalid({"v": None}, schema) == ({"v": None}, [])
    assert rcl.prune_invalid({"v": "x"}, schema) == ({"v": "x"}, [])
    got, warns = rcl.prune_invalid({"v": 3}, schema)
    assert got == {} and len(warns) == 1


def test_type_name_applies_to_array_items():
    schema = {"type": "array", "items": {"type": "integer"}}
    assert rcl.prune_invalid([1, 2], schema) == ([1, 2], [])
    got, warns = rcl.prune_invalid([1, "two"], schema)
    assert got == [1] and len(warns) == 1 and warns[0].startswith(prefix("1"))


# --- properties / additionalProperties / required -----------------------------

def test_properties_prunes_each_failing_child():
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}, "bad": {"type": "integer"}}}
    got, warns = rcl.prune_invalid({"ok": True, "bad": "no"}, schema)
    assert got == {"ok": True}
    assert len(warns) == 1 and warns[0].startswith(prefix("bad"))


def test_additional_properties_false_removes_unknown_key():
    schema = {"type": "object", "additionalProperties": False, "properties": {"good": {"type": "string"}}}
    got, warns = rcl.prune_invalid({"good": "x", "unknown_key": 1}, schema)
    assert got == {"good": "x"} and warns == ["config: dropped unknown_key (unknown key)"]


def test_required_failure_drops_whole_node():
    schema = {"type": "object", "required": ["a", "b"],
              "properties": {"a": {"type": "string"}, "b": {"type": "integer"}}}
    got, warns = rcl.prune_invalid({"a": "x"}, schema)
    assert got == {}
    assert len(warns) == 1 and warns[0].startswith("config: dropped ") and "missing" in warns[0]


def test_required_satisfied_keeps_node():
    schema = {"type": "object", "required": ["a"], "properties": {"a": {"type": "string"}}}
    assert rcl.prune_invalid({"a": "x"}, schema) == ({"a": "x"}, [])


# --- enum / const -------------------------------------------------------------

def test_enum_keeps_member_and_drops_other():
    schema = {"type": "object", "properties": {
        "runner": {"enum": ["pytest", "other"]}, "junk": {"enum": ["a"]}}}
    got, warns = rcl.prune_invalid({"runner": "pytest", "junk": "zzz"}, schema)
    assert got == {"runner": "pytest"}
    assert len(warns) == 1 and warns[0].startswith(prefix("junk"))


def test_const_keeps_match_and_drops_mismatch():
    schema = {"type": "object", "properties": {"sv": {"const": 1}, "off": {"const": "x"}}}
    got, warns = rcl.prune_invalid({"sv": 1, "off": "y"}, schema)
    assert got == {"sv": 1} and len(warns) == 1 and warns[0].startswith(prefix("off"))


# --- numeric bounds (numbers only) --------------------------------------------

def test_minimum_maximum_enforced_on_numbers():
    schema = {"type": "object", "properties": {"n": {"type": "integer", "minimum": 1, "maximum": 20}}}
    for ok in (1, 6.0, 20, 20.0):
        assert rcl.prune_invalid({"n": ok}, schema) == ({"n": ok}, []), ok
    for bad in (0, 21, 0.5, 21.0):
        got, warns = rcl.prune_invalid({"n": bad}, schema)
        assert got == {} and len(warns) == 1, bad


def test_exclusive_minimum_rejects_equal_value():
    schema = {"type": "object", "properties": {"m": {"type": "number", "exclusiveMinimum": 1}}}
    got, warns = rcl.prune_invalid({"m": 1.0}, schema)
    assert got == {} and len(warns) == 1
    assert rcl.prune_invalid({"m": 1.5}, schema) == ({"m": 1.5}, [])


# --- minLength (strings only, ignored on null) ---------------------------------

def test_min_length_applies_to_strings_only():
    schema = {"type": "object", "properties": {"name": {"type": "string", "minLength": 1}}}
    got, warns = rcl.prune_invalid({"name": ""}, schema)
    assert got == {} and len(warns) == 1
    assert rcl.prune_invalid({"name": "a"}, schema) == ({"name": "a"}, [])
    null_schema = {"type": "object", "properties": {"name": {"type": ["string", "null"], "minLength": 1}}}
    assert rcl.prune_invalid({"name": None}, null_schema) == ({"name": None}, [])


# --- items drops one bad array item alone ---------------------------------------

def test_items_drops_only_the_bad_array_item():
    schema = {"type": "array", "items": {"type": "string"}}
    got, warns = rcl.prune_invalid(["a", 1, "b"], schema)
    assert got == ["a", "b"] and len(warns) == 1 and warns[0].startswith(prefix("1"))


# --- jsonschema typing: bools and integral floats -------------------------------

def test_bool_is_never_integer_or_number():
    got, warns = rcl.prune_invalid({"n": True}, {"type": "object", "properties": {"n": {"type": "integer"}}})
    assert got == {} and len(warns) == 1 and warns[0].startswith(prefix("n"))
    got, warns = rcl.prune_invalid({"n": False}, {"type": "object", "properties": {"n": {"type": "number"}}})
    assert got == {} and len(warns) == 1


def test_real_schema_base_sync_carry_max_chain_typing():
    got, warns = rcl.prune_invalid(
        {"schema_version": 1, "review": {"base_sync_carry_max_chain": True}}, SCHEMA)
    assert "review" in got and "base_sync_carry_max_chain" not in got["review"]
    assert len(warns) == 1 and warns[0].startswith(prefix("review.base_sync_carry_max_chain"))


def test_integral_float_is_an_integer():
    got, warns = rcl.prune_invalid(
        {"schema_version": 1, "review": {"base_sync_carry_max_chain": 6.0}}, SCHEMA)
    assert got["review"]["base_sync_carry_max_chain"] == 6.0 and warns == []


def test_enum_and_const_compare_bool_to_bool_only():
    schema = {"type": "object", "properties": {"e": {"enum": [True]}, "c": {"const": False}}}
    got, warns = rcl.prune_invalid({"e": 1, "c": 0}, schema)
    assert got == {} and len(warns) == 2
    assert rcl.prune_invalid({"e": True, "c": False}, schema) == ({"e": True, "c": False}, [])


def test_enum_and_const_compare_numbers_by_value():
    schema = {"type": "object", "properties": {"e": {"enum": [1]}, "c": {"const": 1.0}}}
    assert rcl.prune_invalid({"e": 1.0, "c": 1}, schema) == ({"e": 1.0, "c": 1}, [])
    got, warns = rcl.prune_invalid({"e": True, "c": True}, schema)
    assert got == {} and len(warns) == 2


# --- post-order: a required key lost by pruning drops the whole node -----------

_ANGLE = {
    "type": "object", "additionalProperties": False,
    "required": ["name", "prompt", "role", "model"],
    "properties": {
        "name": {"type": "string", "minLength": 1},
        "prompt": {"type": "string"},
        "role": {"enum": ["confirmer", "finder"]},
        "model": {"enum": ["opus", "sonnet", "haiku", "fable"]},
    },
}
_PO_SCHEMA = {
    "type": "object", "required": ["schema_version"],
    "properties": {
        "schema_version": {"const": 1},
        "review": {"type": "object", "additionalProperties": False,
                   "properties": {"angles": {"type": "array", "items": _ANGLE}}},
    },
}


def test_angle_post_order_drops_bad_item_pure_dict():
    bad = {"name": "a", "prompt": "p", "role": "confirmer", "model": "inherit"}
    got, warns = rcl.prune_invalid({"schema_version": 1, "review": {"angles": [bad]}}, _PO_SCHEMA)
    assert got["review"]["angles"] == []
    assert len(warns) == 2
    assert warns[0].startswith(prefix("review.angles.0.model"))
    assert warns[1].startswith(prefix("review.angles.0"))


def test_angle_real_schema_required_breaks():
    bad = {"name": 123, "prompt": "p", "role": "confirmer", "model": "opus"}
    good = {"name": "perf", "prompt": "p", "role": "finder", "model": "sonnet"}
    got, warns = rcl.prune_invalid({"schema_version": 1, "review": {"angles": [bad, good]}}, SCHEMA)
    assert got["review"]["angles"] == [good]
    assert len(warns) == 2
    assert warns[0].startswith(prefix("review.angles.0.name"))
    assert warns[1].startswith(prefix("review.angles.0"))


def test_valid_angles_kept_unchanged():
    good = [
        {"name": "arch", "prompt": "p", "role": "confirmer", "model": "opus"},
        {"name": "perf", "prompt": "p", "role": "finder", "model": "sonnet"},
    ]
    got, warns = rcl.prune_invalid({"schema_version": 1, "review": {"angles": good}}, SCHEMA)
    assert got["review"]["angles"] == good and warns == []


# --- schema_version is fatal ----------------------------------------------------

def test_schema_version_missing_is_fatal():
    got, warns = rcl.prune_invalid({"review": {"expects_copilot": False}}, SCHEMA)
    assert got == {}
    assert len(warns) == 1 and "schema_version" in warns[0] and "ignored" in warns[0]


def test_schema_version_true_is_fatal():
    got, warns = rcl.prune_invalid({"schema_version": True}, SCHEMA)
    assert got == {} and len(warns) == 1 and "schema_version" in warns[0]


def test_schema_version_2_is_fatal():
    got, warns = rcl.prune_invalid({"schema_version": 2}, SCHEMA)
    assert got == {} and len(warns) == 1 and "schema_version" in warns[0]


def test_schema_version_1_0_accepted():
    got, warns = rcl.prune_invalid({"schema_version": 1.0}, SCHEMA)
    assert got == {"schema_version": 1.0} and warns == []


def test_schema_version_kept_when_valid():
    got, warns = rcl.prune_invalid({"schema_version": 1, "review": {"expects_copilot": False}}, SCHEMA)
    assert got == {"schema_version": 1, "review": {"expects_copilot": False}} and warns == []


# --- annotation keywords are ignored --------------------------------------------

def test_annotation_keywords_ignored():
    schema = {
        "description": "d", "default": {"a": 99}, "title": "t",
        "$id": "x", "$schema": "https://json-schema.org/draft/2020-12/schema",
        "properties": {"a": {"type": "integer", "description": "d2", "default": 3}},
    }
    assert rcl.prune_invalid({"a": 1}, schema) == ({"a": 1}, [])


def test_supported_keywords_constant_covers_the_subset():
    supported = set(rcl.SUPPORTED_KEYWORDS)
    needed = {"type", "properties", "additionalProperties", "required", "enum",
              "const", "minimum", "maximum", "exclusiveMinimum", "minLength", "items"}
    assert needed <= supported and not (set(ANNOTATIONS) & supported)


# --- the real schema stays inside the subset -------------------------------------

def test_real_schema_uses_no_keyword_outside_the_subset():
    def walk(node):
        if not isinstance(node, dict):
            return
        for key, value in node.items():
            if key in ANNOTATIONS:
                continue
            assert key in rcl.SUPPORTED_KEYWORDS, f"schema uses keyword {key!r} outside the subset"
            if key == "properties":
                for subschema in value.values():
                    walk(subschema)
            elif key == "items":
                walk(value)

    walk(SCHEMA)


# --- stdlib-only module -----------------------------------------------------------

def test_repo_config_load_is_stdlib_only():
    src = (Path(__file__).resolve().parent / "repo_config_load.py").read_text(encoding="utf-8")
    for line in src.splitlines():
        for m in (re.match(r"\s*import\s+([A-Za-z_][A-Za-z0-9_]*)", line),
                  re.match(r"\s*from\s+([A-Za-z_][A-Za-z0-9_]*)", line)):
            if m:
                assert m.group(1) in sys.stdlib_module_names, f"non-stdlib import: {line.strip()}"
