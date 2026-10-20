"""Tests for design_run_command.resume_command — verbatim argv resume builder."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import design_run_command as drc  # noqa: E402


FULL_TAIL = (
    "my-slug --mode build --skip-design --local --max-attempts 2"
    " --max-tokens 900000 --max-wall-clock 7200"
    " --pr-reviewers copilot-pull-request-reviewer[bot],alice --no-review --no-iterate"
    " --pickup-skill tp-pickup-jira --task-id JIRA-12 --fast-audit"
)


def test_resume_command_every_flag_intact():
    result = drc.resume_command(FULL_TAIL, "implement")
    assert result == f"/tp-run-full-design {FULL_TAIL} --resume-stage implement"
    assert result.count("--resume-stage") == 1
    assert "copilot-pull-request-reviewer[bot],alice" in result
    for flag in ("--mode", "--skip-design", "--local", "--max-attempts",
                 "--max-tokens", "--max-wall-clock", "--pr-reviewers",
                 "--no-review", "--no-iterate", "--pickup-skill",
                 "--task-id", "--fast-audit"):
        assert flag in result


def test_resume_command_replaces_middling_stage():
    tail = (
        "my-slug --mode build --skip-design --local --max-attempts 2"
        " --resume-stage plan --max-tokens 900000 --no-review"
    )
    result = drc.resume_command(tail, "review")
    assert result == (
        "/tp-run-full-design my-slug --mode build --skip-design --local"
        " --max-attempts 2 --max-tokens 900000 --no-review --resume-stage review"
    )
    assert result.count("--resume-stage") == 1
    assert result.endswith(" --resume-stage review")
    assert "plan" not in result


def test_resume_command_removes_equals_form():
    tail = "my-slug --local --resume-stage=plan --max-attempts 2"
    result = drc.resume_command(tail, "implement")
    assert result == (
        "/tp-run-full-design my-slug --local --max-attempts 2"
        " --resume-stage implement"
    )
    assert result.count("--resume-stage") == 1


@pytest.mark.parametrize("stage", ["design", "build", "", "Plan"])
def test_resume_command_bad_stage(stage):
    with pytest.raises(ValueError):
        drc.resume_command("my-slug", stage)


def test_resume_command_empty_tail_after_removal():
    with pytest.raises(ValueError):
        drc.resume_command("--resume-stage plan", "implement")


def test_slash_command_unchanged():
    assert drc.slash_command("my-slug", mode="build", skip_design=True, local=True) == (
        "/tp-run-full-design my-slug --mode build --skip-design --local"
    )


def test_module_within_line_cap():
    lines = Path(drc.__file__).read_text(encoding="utf-8").splitlines()
    assert len(lines) <= 252
