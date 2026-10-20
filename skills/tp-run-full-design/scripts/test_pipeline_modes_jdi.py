"""Tests for the just-do-it-aware --mode build precondition in pipeline_modes.py.

A just-do-it design has no detailed-design.md and no plan-audit; its plan is
generated mechanically, so a JDI + build run needs design.md on disk and
nothing else.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pipeline_modes import check_preconditions, required_artifacts  # noqa: E402

_JDI = "just-do-it"


def test_build_jdi_needs_only_design_md():
    assert required_artifacts("build", weight_class=_JDI) == ("design.md",)


def test_plan_jdi_matches_full_value():
    assert required_artifacts("plan", weight_class=_JDI) == required_artifacts("plan")
    assert required_artifacts("plan", weight_class=_JDI) == (
        "design.md",
        "detailed-design.md",
    )


def test_check_build_jdi_passes_with_design_md_only(tmp_path):
    (tmp_path / "design.md").write_text("x\n", encoding="utf-8")
    assert check_preconditions("build", str(tmp_path), weight_class=_JDI) == []


def test_check_build_jdi_reports_design_md_when_absent(tmp_path):
    assert check_preconditions("build", str(tmp_path), weight_class=_JDI) == ["design.md"]
