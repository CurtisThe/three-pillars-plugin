"""Tests for build_synth_prompt busy_members (local-role-routing 4.4)."""

from pathlib import Path

import pytest

from build_synth_prompt import build_synth_prompt

DOC = Path(__file__).resolve().parents[2] / "council" / "strata-members.md"


def _args():
    r1 = [{"member": "council-ada", "verdict": "pass-with-notes", "findings": []}]
    return (["a.md"], r1, None, "plan-audit")


def test_busy_line_names_exactly_given_members():
    out = build_synth_prompt(*_args(), member_engine="local", busy_members=["council-ada", "council-bo"])
    lines = [ln for ln in out.splitlines() if ln.startswith("Sonnet-served (slot busy):")]
    assert lines == ["Sonnet-served (slot busy): council-ada, council-bo"]


def test_no_busy_members_output_unchanged():
    base = build_synth_prompt(*_args(), member_engine="local")
    assert build_synth_prompt(*_args(), member_engine="local", busy_members=[]) == base
    assert "Sonnet-served (slot busy)" not in base


def test_opus_with_busy_members_raises():
    with pytest.raises(ValueError):
        build_synth_prompt(*_args(), member_engine="opus", busy_members=["council-ada"])


def test_opus_empty_busy_unchanged():
    assert build_synth_prompt(*_args(), busy_members=()) == build_synth_prompt(*_args())


@pytest.mark.parametrize("token", ["busy_members", "fallback-busy", "--decisions", "escape-ledger.ndjson"])
def test_doc_contains(token):
    assert token in DOC.read_text(encoding="utf-8")
