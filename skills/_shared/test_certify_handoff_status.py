"""certify_handoff status gate (#162).

A certifier's records handoff is refused outright unless the return carries a
known, pass status: a missing status or an unknown status value makes the
whole handoff unverified (reason REASON), while a known pass status proceeds to
the records byte/count check.

design: fragile-test-prevention (Task 15.8).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from certify_handoff import REASON, check_handoff

RECORDS = [{"id": "c1", "rationale": "near-miss"}, {"id": "c2", "rationale": "absence"}]
RAW = json.dumps(RECORDS).encode("utf-8")
SHA = hashlib.sha256(RAW).hexdigest()


def _valid(status: str | None = "pass") -> dict:
    env = {
        "schema": "tp-run-full-design/certifier-return/v1",
        "status": status,
        "claims_file": "three-pillars-docs/tp-designs/x/certifications/impl.claims.json",
        "records_file": "/scratch/cert123/records.json",
        "records_sha256": SHA,
        "record_count": len(RECORDS),
        "repair_log": [{"id": "c1", "attempts": 1, "last_reasons": ["invalid:argv"]}],
        "unauthored": [{"id": "c3", "reason": "guard-absent"}],
    }
    if status is None:
        del env["status"]
    return env


def _copy(tmp_path: Path) -> Path:
    path = tmp_path / "records.json"
    path.write_bytes(RAW)
    return path


def test_pass_status_is_accepted(tmp_path):
    """A known pass status proceeds to the records check and is accepted."""
    assert check_handoff(_valid("pass"), _copy(tmp_path)) == []


def test_missing_status_is_refused(tmp_path):
    """A return with no status key at all is refused."""
    assert check_handoff(_valid(None), _copy(tmp_path)) == [REASON]


@pytest.mark.parametrize("unknown", ["errored", "needs-work", "PASS", "Pass", "", None])
def test_unknown_status_is_refused(tmp_path, unknown):
    """A status value that is not the pass status is refused."""
    env = _valid("pass")
    env["status"] = unknown
    assert check_handoff(env, _copy(tmp_path)) == [REASON]
