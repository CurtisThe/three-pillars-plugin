"""Tests for cheap_engine.local_mode — TP_LOCAL_MODE (design: one-cheap-engine 1.2)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cheap_engine as ce  # noqa: E402


def test_unset_is_fallback():
    assert ce.local_mode({}) == ("fallback", [])
    assert ce.local_mode({"TP_LOCAL_MODE": ""}) == ("fallback", [])


def test_given_values_pass_through():
    assert ce.local_mode({"TP_LOCAL_MODE": "fallback"})[0] == "fallback"
    assert ce.local_mode({"TP_LOCAL_MODE": "wait"})[0] == "wait"


def test_exclusive_is_wait():
    assert ce.local_mode({"TP_LOCAL_MODE": "exclusive"}) == ("wait", [])


def test_unknown_logs_one_line_and_falls_back():
    mode, notes = ce.local_mode({"TP_LOCAL_MODE": "bogus"})
    assert mode == "fallback"
    assert len(notes) == 1 and "bogus" in notes[0]


def test_values_are_the_fixed_contract():
    assert ce.MODES == ("fallback", "wait", "exclusive")
