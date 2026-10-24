"""Tests for the **Growth** line jdi_plan.render derives from `estimated-lines`."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import jdi_plan  # noqa: E402


def _design(tmp_path: Path, extra: str) -> Path:
    d = tmp_path / "fixture"
    d.mkdir()
    (d / "design.md").write_text(
        "---\nweight-class: just-do-it\nslug: fixture\n" + extra + "---\n\n"
        "# fixture — design\n\n## Problem\n\nA small thing.\n\n"
        "## Scope\n\n- `skills/foo/bar.py`\n\n"
        "## Behaviors\n\nIt works.\n\n## Done when\n\nIt passes.\n",
        encoding="utf-8")
    return d


def test_numeric_estimate_renders_growth_after_targets(tmp_path):
    out = jdi_plan.render(str(_design(tmp_path, "estimated-lines: 60\n")), str(tmp_path))
    lines = out.splitlines()
    assert "**Growth**: +60" in lines
    assert lines[lines.index("**Growth**: +60") - 1].startswith("**Targets**:")


def test_missing_estimate_renders_no_growth(tmp_path):
    out = jdi_plan.render(str(_design(tmp_path, "")), str(tmp_path))
    assert "**Growth**" not in out


def test_non_numeric_estimate_renders_no_growth(tmp_path):
    out = jdi_plan.render(str(_design(tmp_path, "estimated-lines: lots\n")), str(tmp_path))
    assert "**Growth**" not in out


def test_render_is_idempotent(tmp_path):
    d = _design(tmp_path, "estimated-lines: 60\n")
    assert jdi_plan.write(str(d), str(tmp_path))[1].startswith("jdi-plan: wrote")
    assert jdi_plan.write(str(d), str(tmp_path))[1].startswith("jdi-plan: unchanged")
