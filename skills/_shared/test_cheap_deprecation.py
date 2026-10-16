"""test_cheap_deprecation.py — deprecation notes for the retired cheap-tier switches.

design: one-cheap-engine
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cheap_deprecation  # noqa: E402

CASES = [
    ({}, "on", False, "--cheap-tier"),
    ({}, "ab", False, "--cheap-tier=ab"),
    ({}, None, True, "--no-cheap-tier"),
    ({"cheap_tier": {"default_run_flag": "on"}}, None, False, "cheap_tier.default_run_flag"),
    ({"role_engines": {"review": "strata"}}, None, False, "role_engines"),
]


def test_clean_input_has_no_notes():
    assert cheap_deprecation.notes({}, cheap_tier=None, no_cheap_tier=False) == []
    cfg = {"role_engines": {}, "cheap_tier": {}}
    assert cheap_deprecation.notes(cfg, cheap_tier=None, no_cheap_tier=False) == []


@pytest.mark.parametrize("cfg,ct,no,name", CASES)
def test_each_switch_gives_one_line(cfg, ct, no, name):
    out = cheap_deprecation.notes(cfg, cheap_tier=ct, no_cheap_tier=no)
    assert len(out) == 1
    assert out[0].startswith("deprecated:")
    assert name in out[0]
    assert "changes nothing" in out[0]


def test_ab_mode_is_named():
    out = cheap_deprecation.notes({}, cheap_tier="ab", no_cheap_tier=False)
    assert len(out) == 1 and "ab" in out[0]


def test_all_switches_together_one_line_each():
    cfg = {"role_engines": {"a": "x"}, "cheap_tier": {"default_run_flag": "ab"}}
    out = cheap_deprecation.notes(cfg, cheap_tier="ab", no_cheap_tier=True)
    assert len(out) == 4
    assert all(line.startswith("deprecated:") for line in out)
