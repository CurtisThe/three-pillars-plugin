"""certifier-return v1 schema + the caller-side records handoff check.

design: audit-pass-does-not-bind (Task 4.3; detailed-design.md §Interfaces [A][R12]).
The certifier never commits and never inlines records: it names a records
file (absolute path in its own scratch) plus sha256 and count. The caller
copies the file and `certify_handoff.check_handoff` re-checks the bytes.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import jsonschema
import pytest

from certify_handoff import check_handoff

SCHEMA = (Path(__file__).resolve().parent.parent / "tp-run-full-design" / "schemas"
          / "certifier-return.v1.json")
RECORDS = [{"id": "c1", "rationale": "near-miss"}, {"id": "c2", "rationale": "absence"}]
RAW = json.dumps(RECORDS).encode("utf-8")
SHA = hashlib.sha256(RAW).hexdigest()


def _valid(**over) -> dict:
    env = {
        "schema": "tp-run-full-design/certifier-return/v1",
        "status": "pass",
        "claims_file": "three-pillars-docs/tp-designs/x/certifications/impl.claims.json",
        "records_file": "/scratch/cert123/records.json",
        "records_sha256": SHA,
        "record_count": 2,
        "repair_log": [{"id": "c1", "attempts": 1, "last_reasons": ["invalid:argv"]}],
        "unauthored": [{"id": "c3", "reason": "guard-absent"}],
    }
    env.update(over)
    return env


def _is_valid(env: dict) -> bool:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    return jsonschema.Draft7Validator(schema).is_valid(env)


def test_valid_envelope():
    assert _is_valid(_valid())
    assert _is_valid(_valid(repair_log=[], unauthored=[]))


def test_errored_envelope_needs_no_records_file():
    env = _valid(status="errored")
    for key in ("records_file", "records_sha256", "record_count"):
        del env[key]
    assert _is_valid(env)


@pytest.mark.parametrize("key", ["schema", "status", "claims_file", "records_file",
                                 "records_sha256", "record_count", "repair_log", "unauthored"])
def test_pass_envelope_requires_each_field(key):
    env = _valid()
    del env[key]
    assert not _is_valid(env)


@pytest.mark.parametrize("over", [
    {"status": "needs-work"}, {"schema": "tp-run-full-design/certifier-return/v2"},
    {"records_file": "records.json"}, {"records_file": "./scratch/records.json"},
    {"records_sha256": "abc"}, {"records_sha256": SHA.upper()}, {"record_count": -1},
    {"record_count": "2"}, {"repair_log": [{"id": "c1", "attempts": 1}]},
    {"unauthored": [{"id": "c3"}]},
])
def test_bad_field_values_rejected(over):
    assert not _is_valid(_valid(**over))


@pytest.mark.parametrize("key,value", [
    ("records", RECORDS), ("mode", "dry-run"), ("commit_sha", "a" * 40),
])
def test_inline_records_mode_commit_sha_rejected(key, value):
    assert not _is_valid(_valid(**{key: value}))


# --- check_handoff ---------------------------------------------------------- #
def _copy(tmp_path: Path, raw: bytes = RAW) -> Path:
    path = tmp_path / "records.json"
    path.write_bytes(raw)
    return path


def test_handoff_ok(tmp_path):
    assert check_handoff(_valid(), _copy(tmp_path)) == []


def test_handoff_sha_mismatch(tmp_path):
    path = _copy(tmp_path, RAW + b" ")
    assert check_handoff(_valid(), path) == ["records-handoff"]


def test_handoff_count_mismatch(tmp_path):
    assert check_handoff(_valid(record_count=3), _copy(tmp_path)) == ["records-handoff"]


def test_handoff_missing_file(tmp_path):
    assert check_handoff(_valid(), tmp_path / "absent.json") == ["records-handoff"]


@pytest.mark.parametrize("raw", [b"not json", b'{"id": "c1"}'])
def test_handoff_bytes_not_a_json_array(tmp_path, raw):
    env = _valid(records_sha256=hashlib.sha256(raw).hexdigest(), record_count=1)
    assert check_handoff(env, _copy(tmp_path, raw)) == ["records-handoff"]


@pytest.mark.parametrize("over", [{"records_sha256": None}, {"record_count": None},
                                  {"status": "errored"}])
def test_handoff_envelope_without_a_usable_handoff(tmp_path, over):
    assert check_handoff(_valid(**over), _copy(tmp_path)) == ["records-handoff"]
