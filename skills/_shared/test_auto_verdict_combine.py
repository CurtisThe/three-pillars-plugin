"""Tests for auto_verdict.combine_verdict — the certification verdict join.

design: audit-pass-does-not-bind (Task 4.1; detailed-design.md §Interfaces [E]).
Total order: NEEDS WORK(1) > UNVERIFIED(2) > KNOWN BYPASS(0) > PASS WITH NOTES(0)
> PASS(0). `compute_verdict` is untouched (its own tests live elsewhere).
"""

from __future__ import annotations

import itertools

import pytest

from auto_verdict import combine_verdict, compute_verdict

BASES = ["PASS", "PASS WITH NOTES", "KNOWN BYPASS", "UNVERIFIED", "NEEDS WORK"]
CODES = {"PASS": 0, "PASS WITH NOTES": 0, "KNOWN BYPASS": 0, "UNVERIFIED": 2, "NEEDS WORK": 1}
STATUS_VERDICT = {"binds": "PASS", "known-bypass": "KNOWN BYPASS", "unverified": "UNVERIFIED",
                  "not-binding": "NEEDS WORK", "false-red": "NEEDS WORK"}
RANK = {v: i for i, v in enumerate(BASES)}


@pytest.mark.parametrize("base", BASES)
def test_empty_statuses_is_identity(base):
    assert combine_verdict(base, []) == (base, CODES[base])


@pytest.mark.parametrize("base,status", list(itertools.product(BASES, STATUS_VERDICT)))
def test_base_by_status_is_the_join(base, status):
    mapped = STATUS_VERDICT[status]
    expected = base if RANK[base] >= RANK[mapped] else mapped
    assert combine_verdict(base, [status]) == (expected, CODES[expected])


def test_order_pins():
    assert combine_verdict("PASS", ["unverified", "not-binding"]) == ("NEEDS WORK", 1)
    assert combine_verdict("UNVERIFIED", ["known-bypass"]) == ("UNVERIFIED", 2)
    assert combine_verdict("PASS WITH NOTES", ["known-bypass"]) == ("KNOWN BYPASS", 0)
    assert combine_verdict("KNOWN BYPASS", ["binds"]) == ("KNOWN BYPASS", 0)
    assert combine_verdict("PASS", ["binds", "binds"]) == ("PASS", 0)


@pytest.mark.parametrize("base", ["pass", "Pass", "FAIL", "", "needs-work"])
def test_unknown_base_raises(base):
    with pytest.raises(ValueError):
        combine_verdict(base, [])


@pytest.mark.parametrize("status", ["BINDS", "pass", "", "errored", "unknown"])
def test_unknown_status_raises(status):
    with pytest.raises(ValueError):
        combine_verdict("PASS", ["binds", status])


def test_commutative_over_permutations():
    statuses = ["binds", "known-bypass", "unverified", "false-red"]
    for base in BASES:
        results = {combine_verdict(base, list(p)) for p in itertools.permutations(statuses)}
        assert len(results) == 1


def test_idempotent():
    for base in BASES:
        for status in STATUS_VERDICT:
            once = combine_verdict(base, [status])
            assert combine_verdict(base, [status, status]) == once
            assert combine_verdict(once[0], [status]) == once


def test_compute_verdict_unchanged():
    assert compute_verdict([]) == ("PASS", 0)
    assert compute_verdict(["High"]) == ("PASS WITH NOTES", 0)
    assert compute_verdict(["High", "Low"]) == ("NEEDS WORK", 1)
    with pytest.raises(ValueError):
        compute_verdict(["high"])
