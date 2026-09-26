"""Tests for the light-aware --mode build precondition in pipeline_modes.py."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pipeline_modes import check_preconditions, required_artifacts  # noqa: E402

_MODES_MD = Path(__file__).resolve().parent.parent / "pipeline-modes.md"


def _light_dir(tmp_path: Path) -> str:
    for name in ("design.md", "plan.md"):
        (tmp_path / name).write_text("x\n", encoding="utf-8")
    return str(tmp_path)


def test_build_light_drops_detailed_design():
    assert required_artifacts("build", weight_class="light") == ("design.md", "plan.md")


def test_build_default_full_unchanged():
    assert required_artifacts("build") == ("design.md", "detailed-design.md", "plan.md")


def test_plan_light_unchanged():
    assert required_artifacts("plan", weight_class="light") == required_artifacts("plan")
    assert "detailed-design.md" in required_artifacts("plan", weight_class="light")


def test_check_build_light_passes(tmp_path):
    assert check_preconditions("build", _light_dir(tmp_path), weight_class="light") == []


def test_check_build_full_refused(tmp_path):
    assert check_preconditions("build", _light_dir(tmp_path)) == ["detailed-design.md"]


@pytest.mark.parametrize("wc", ["bogus", "", None, "LIGHTISH"])
def test_unknown_weight_class_fails_safe(tmp_path, wc):
    assert required_artifacts("build", weight_class=wc) == required_artifacts("build")
    assert check_preconditions("build", _light_dir(tmp_path), weight_class=wc) == [
        "detailed-design.md"
    ]


def test_pipeline_modes_md_documents_light_build():
    text = _MODES_MD.read_text(encoding="utf-8")
    rows = [
        ln for ln in text.splitlines()
        if "build" in ln and "light" in ln and "design.md" in ln and "plan.md" in ln
    ]
    assert rows, "pipeline-modes.md must document the light + build precondition"
