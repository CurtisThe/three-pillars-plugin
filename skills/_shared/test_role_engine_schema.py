"""Tests for the `role_engines` block in repo-config.schema.json + its doc.

design: local-role-routing (Task 1.4). The schema names the same vocabulary
`role_engine.py` owns: exactly the `ENGINE_ROLES` keys, each with the `ENGINES`
values, `additionalProperties: false` like every other block. The doc names the
block, the two engines and the module that resolves them.
Run with: TMPDIR=/home/curtis/t python3 -m pytest -n 4 skills/_shared/test_role_engine_schema.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_SHARED = Path(__file__).resolve().parent
sys.path.insert(0, str(_SHARED))

import role_engine as re_  # noqa: E402

SCHEMA_PATH = _SHARED / "repo-config.schema.json"
DOC_PATH = _SHARED / "repo-config.md"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _block():
    """The top-level `role_engines` schema node."""
    return SCHEMA["properties"][re_.CONFIG_KEY]


def _cfg(block):
    return {"schema_version": 1, re_.CONFIG_KEY: block}


def test_block_shape_matches_role_engine_vocabulary():
    block = _block()
    assert block["type"] == "object"
    assert block["additionalProperties"] is False
    assert set(block["properties"]) == set(re_.ENGINE_ROLES)
    for role in re_.ENGINE_ROLES:
        prop = block["properties"][role]
        assert prop["type"] == "string"
        assert prop["enum"] == list(re_.ENGINES)


def test_block_is_a_sibling_of_local_implement():
    # The block sits next to `local_implement` in the same top-level property
    # list, so the two cheap-tier knobs stay discoverable together.
    names = list(SCHEMA["properties"])
    assert names.index(re_.CONFIG_KEY) in (
        names.index("local_implement") + 1,
        names.index("local_implement") - 1,
    )


@pytest.fixture(scope="module")
def validator():
    jsonschema = pytest.importorskip("jsonschema")
    v = jsonschema.Draft202012Validator(SCHEMA)
    jsonschema.Draft202012Validator.check_schema(SCHEMA)
    return v


def test_validator_accepts_legal_blocks(validator):
    for role in re_.ENGINE_ROLES:
        for engine in re_.ENGINES:
            validator.validate(_cfg({role: engine}))
    validator.validate(_cfg({}))
    validator.validate(_cfg({r: "local" for r in re_.ENGINE_ROLES}))


def test_validator_rejects_bad_keys_and_values(validator):
    jsonschema = pytest.importorskip("jsonschema")
    for bad in ({"synthesizer": "local"}, {"review_finder": "sonnet"},
                {"review_finder": "LOCAL"}, {"context_scout": True},
                {"council_member": 0}):
        with pytest.raises(jsonschema.ValidationError):
            validator.validate(_cfg(bad))
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(_cfg(["not", "an", "object"]))


def test_doc_names_the_block_and_the_resolver():
    doc = DOC_PATH.read_text(encoding="utf-8")
    assert re_.CONFIG_KEY in doc
    assert "skills/_shared/role_engine.py" in doc
    for role in re_.ENGINE_ROLES:
        assert role in doc
    for engine in re_.ENGINES:
        assert f"`{engine}`" in doc
