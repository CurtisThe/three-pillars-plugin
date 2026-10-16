"""Tests for the fable_notice move out of model_policy (design: review-convergence 8.1).

`fable_notice` and its helper `_append_fable_entry` live in their own module
`skills/_shared/fable_notice.py`; `model_policy` keeps only the model policy and
defines neither. The three design-run callers (run_supervisor, fleet_plan,
launch_design_run) reach the notice through the new module.
Run with: python3 -m pytest skills/_shared/test_fable_notice_move.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fable_notice  # noqa: E402
import model_policy  # noqa: E402

SH = Path(__file__).resolve().parent


def _caller(relpath: str) -> Path:
    """One skill's script under skills/*/scripts/ — resolved by glob so this
    shipped file never spells a pro-exclusive skill dir name literally (the
    release leak guard greps every shipped text file for those names)."""
    hits = sorted(SH.parent.glob("*/" + relpath))
    assert len(hits) == 1, f"{relpath}: expected exactly one match, got {hits}"
    return hits[0]


CALLERS = (
    _caller("scripts/run_supervisor.py"),
    _caller("scripts/fleet_plan.py"),
    SH / "launch_design_run.py",
)


def test_fable_notice_is_importable_from_the_new_module():
    assert callable(fable_notice.fable_notice)
    assert fable_notice.fable_notice.__module__ == "fable_notice"


def test_model_policy_no_longer_defines_the_fable_helpers():
    assert not hasattr(model_policy, "fable_notice")
    assert not hasattr(model_policy, "_append_fable_entry")


def test_model_policy_source_has_no_fable_definitions():
    source = (SH / "model_policy.py").read_text(encoding="utf-8")
    assert "def fable_notice" not in source
    assert "def _append_fable_entry" not in source


def test_callers_import_and_call_the_new_module():
    for path in CALLERS:
        source = path.read_text(encoding="utf-8")
        assert "fable_notice.fable_notice(" in source, path
        assert "model_policy.fable_notice(" not in source, path
