"""Tests for the round-tail envelope schema and round_scratch.tail_check.

design: iterate-convergence-budget (Task 6.2)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parent))

import round_scratch as rs  # noqa: E402

SCHEMA = Path(__file__).resolve().parent.parent / "schemas" / "round-tail.v1.json"


def _good():
    return {"schema": "tp-pr-iterate/round-tail/v1", "round": 3, "head_reviewed": "a" * 40,
            "head_after": "b" * 40,
            "tally": {"P": 1, "X": 0, "T": 2, "C": 0, "blocking": 1, "degraded": 0},
            "downgraded": 1, "notes": 2, "action": "fix", "fix_commit": "b" * 40,
            "terminal": None, "converged": False,
            "budget": {"iteration": 3, "round_cap": 6, "signal": None, "holding": []},
            "summary": "fixed one"}


def _schema():
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


def test_schema_is_valid_2020_12():
    Draft202012Validator.check_schema(_schema())


def test_schema_all_required_no_additional():
    s = _schema()
    assert s["additionalProperties"] is False
    assert set(s["required"]) == set(s["properties"])
    for nested in ("tally", "budget"):
        sub = s["properties"][nested]
        assert sub["additionalProperties"] is False
        assert set(sub["required"]) == set(sub["properties"])


def test_good_envelope_valid_both_validators():
    assert not list(Draft202012Validator(_schema()).iter_errors(_good()))
    assert rs.envelope_errors(_good()) == []


@pytest.mark.parametrize("mutate", [
    lambda e: e.pop("summary"),
    lambda e: e.update(extra=1),
    lambda e: e.update(action="merge"),
    lambda e: e.update(round=True),
    lambda e: e.update(round=0),
    lambda e: e.update(converged="no"),
    lambda e: e.update(schema="candidate.v1"),
    lambda e: e["tally"].pop("C"),
    lambda e: e["budget"].update(holding=[1]),
    lambda e: e.update(summary="x" * 401),
])
def test_bad_envelope_rejected_by_both(mutate):
    env = _good()
    mutate(env)
    assert list(Draft202012Validator(_schema()).iter_errors(env))
    assert rs.envelope_errors(env)


def _round(tmp_path, env):
    r = tmp_path / "r1"
    (r / "tail").mkdir(parents=True)
    if env is not None:
        text = env if isinstance(env, str) else json.dumps(env)
        (r / "tail" / "envelope.json").write_text(text, encoding="utf-8")
    return r


def test_tail_check_ok(tmp_path):
    assert rs.tail_check(_round(tmp_path, _good())) is None


@pytest.mark.parametrize("env", [None, "{not json", {"schema": "x"}])
def test_tail_check_failed(tmp_path, env):
    assert rs.tail_check(_round(tmp_path, env)) == {"terminal": "needs-human-attention",
                                                     "reason": "tail-failed"}
