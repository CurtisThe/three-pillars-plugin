"""Tests for escape_ledger.row (design local-role-routing, task 3.1)."""
from __future__ import annotations

import pytest

import escape_ledger
import role_engine


def _args():
    return ("review_finder", "local", "d", "round-1", "security#0",
            "kept", "opus-check", "logic")


def test_dispositions_constant():
    assert escape_ledger.DISPOSITIONS == ("kept", "dropped", "downgraded", "opus-added")


def test_roles_is_engine_roles():
    assert escape_ledger.ROLES is role_engine.ENGINE_ROLES


def test_row_has_exactly_eight_keys():
    r = escape_ledger.row(*_args())
    assert set(r) == {"role", "engine", "design", "step", "finding_id",
                      "disposition", "caught_by", "defect_class"}
    assert r["role"] == "review_finder" and r["defect_class"] == "logic"


def test_bad_role_raises():
    a = list(_args())
    a[0] = "synthesizer"
    with pytest.raises(ValueError):
        escape_ledger.row(*a)


def test_bad_disposition_raises():
    a = list(_args())
    a[5] = "ignored"
    with pytest.raises(ValueError):
        escape_ledger.row(*a)


def test_served_sonnet_busy_adds_ninth_key():
    r = escape_ledger.row(*_args(), served="sonnet-busy")
    assert len(r) == 9 and r["served"] == "sonnet-busy"
    assert escape_ledger.SERVED == ("sonnet-busy",)


def test_served_bogus_raises():
    with pytest.raises(ValueError):
        escape_ledger.row(*_args(), served="bogus")
