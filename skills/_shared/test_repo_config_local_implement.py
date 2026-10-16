"""Tests for the `local_implement` block in repo-config.schema.json.

design: local-implement-and-review (Task 3.1). Split from `test_repo_config.py`
per the file-size caps.
"""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

SCHEMA_PATH = Path(__file__).parent / "repo-config.schema.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

FULL_BLOCK = {
    "enabled": True,
    "model": "haiku",
    "fallback_model": "sonnet",
    "full_design": False,
    "escalate": True,
    "max_retries": 2,
    "max_files": 3,
    "attempt_wall_clock_s": 1200,
    "registry_files": [],
}


def test_attempt_wall_clock_s_schema_entry(validator):
    import local_implement_config as lic
    props = SCHEMA["properties"]["local_implement"]["properties"]
    assert props["attempt_wall_clock_s"] == {"type": "integer", "minimum": 60,
                                             "default": 1200}
    assert props["attempt_wall_clock_s"]["default"] == lic.DEFAULTS["attempt_wall_clock_s"]
    validator.validate(_cfg({"attempt_wall_clock_s": 60}))
    for bad in (30, True, "20m"):
        with pytest.raises(ValidationError):
            validator.validate(_cfg({"attempt_wall_clock_s": bad}))


@pytest.fixture(scope="module")
def validator():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _cfg(block):
    return {"schema_version": 1, "local_implement": block}


def test_schema_accepts_block(validator):
    validator.validate(_cfg(dict(FULL_BLOCK)))
    validator.validate(_cfg({}))  # every key is optional: defaults fill the rest
    validator.validate(_cfg({"enabled": True}))


def test_default_run_flag_validates(validator):
    for ok in ("on", "off"):
        validator.validate(_cfg(dict(FULL_BLOCK, default_run_flag=ok)))
    for bad in ("yes", True, ""):
        with pytest.raises(ValidationError):
            validator.validate(_cfg(dict(FULL_BLOCK, default_run_flag=bad)))


def test_loader_accepts_default_run_flag(tmp_path):
    # local_implement_config.load must not raise on the new key (design:
    # jdi-run-defaults) — the launcher's --local default reads it.
    import local_implement_config as lic
    d = tmp_path / ".three-pillars"
    d.mkdir()
    (d / "config.json").write_text(json.dumps(
        _cfg({"enabled": True, "full_design": True, "default_run_flag": "on"})),
        encoding="utf-8")
    assert lic.load(tmp_path)["default_run_flag"] == "on"
    with pytest.raises(ValueError):
        (d / "config.json").write_text(json.dumps(
            _cfg({"default_run_flag": "yes"})), encoding="utf-8")
        lic.load(tmp_path)


def test_cheap_tier_default_run_flag_accepts_off(validator):
    # The cheap-tier side of the same default-flag work: "off" is now a value.
    for ok in ("on", "ab", "off"):
        validator.validate({"schema_version": 1,
                            "cheap_tier": {"default_run_flag": ok}})
    for bad in ("yes", True):
        with pytest.raises(ValidationError):
            validator.validate({"schema_version": 1,
                                "cheap_tier": {"default_run_flag": bad}})


def test_schema_rejects_unknown_key(validator):
    with pytest.raises(ValidationError):
        validator.validate(_cfg(dict(FULL_BLOCK, unknown_key=1)))
    for key, bad in (("enabled", "yes"), ("full_design", 1), ("escalate", None),
                     ("model", ""), ("fallback_model", 3), ("max_retries", -1),
                     ("max_retries", 1.5), ("max_files", 0), ("max_files", True),
                     ("attempt_wall_clock_s", 30), ("attempt_wall_clock_s", True),
                     ("attempt_wall_clock_s", "20m"), ("registry_files", "a.py"),
                     ("registry_files", [1]), ("registry_files", [""])):
        with pytest.raises(ValidationError):
            validator.validate(_cfg(dict(FULL_BLOCK, **{key: bad})))
    with pytest.raises(ValidationError):
        validator.validate(_cfg(["not", "an", "object"]))
