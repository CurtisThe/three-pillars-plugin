"""Tests for validate_design_floor.py — Shape A validator gate for /tp-design --auto.

Covers v1 of the design-floor schema (documented in skills/_shared/auto-mode.md
under "Shape A — Validator gate"; see also detailed-design.md in
three-pillars-docs/completed-tp-designs/design-pipeline-auto-mode/ for the
historical design that motivated the schema):

  Required sections (## headings):
    - ## Problem
    - ## Vision alignment
    - ## Scope, with non-empty ### In scope subsection
    - ## Behaviors
    - ## Constraints

  Optional sections (warn, do not block):
    - ## Dependencies
    - ## Entities
    - ## Open Questions

  Content rule: each required section must contain at least one line of
  >= 20 non-whitespace characters that does NOT match ^\\.\\.\\.+$ or ^TBD\\b.

On BLOCKED the validator exits 1 with a JSON verdict on stderr. Every
assertion below checks result.stderr, never result.stdout — the channel
contract is part of the interface and must be honoured by the validator.

Run with: pytest skills/_shared/test_validate_design_floor.py -q
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent / "validate_design_floor.py"


def _well_formed_sections() -> dict[str, str]:
    """All required and optional sections with non-placeholder bodies above the 20-char floor."""
    return {
        "Problem": (
            "The TDD pipeline has no autonomous mode that an orchestrator can drive "
            "end-to-end without a human in the loop."
        ),
        "Vision alignment": (
            "Advances floor, not ceiling — autonomous runs let humans focus on the "
            "decisions the orchestrator cannot make safely."
        ),
        "Scope": (
            "### In scope\n"
            "Retrofit `--auto` onto seven design-pipeline skills; generalize the "
            "shared auto-mode convention; ship a deterministic floor validator.\n\n"
            "### Out of scope\n"
            "The orchestrator itself is a separate design."
        ),
        "Behaviors": (
            "Each `--auto` skill replaces user prompts with self-assessment and "
            "appends a decisions.md entry per `auto-mode.md`."
        ),
        "Constraints": (
            "One pattern per skill shape (validator / generator / audit). "
            "No new external dependencies; stdlib-only helpers."
        ),
        "Dependencies": "Existing skills/_shared/auto-mode.md (generalized, not replaced).",
        "Entities": (
            "Auto-mode skill, decisions log, design-floor schema, finding-severity classifier."
        ),
        "Open Questions": (
            "Retry cap for /tp-phase-implement --auto and whether MISALIGNMENT "
            "dispatch needs a per-skill override."
        ),
    }


def _build_design_md(
    tmp_path: Path,
    sections: dict[str, str] | None = None,
    title: str = "test-design",
    frontmatter: dict[str, str] | None = None,
) -> Path:
    """Write a design.md from the given section dict and return the design dir.

    ``frontmatter`` (optional) is written as a leading ``---`` block, e.g.
    ``{"floor": "2"}``.
    """
    if sections is None:
        sections = _well_formed_sections()
    design_dir = tmp_path / "design"
    design_dir.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    if frontmatter:
        lines.append("---")
        lines.extend(f"{key}: {value}" for key, value in frontmatter.items())
        lines.append("---")
        lines.append("")
    lines.extend([f"# {title}", ""])
    for heading, body in sections.items():
        lines.append(f"## {heading}")
        lines.append("")
        lines.append(body)
        lines.append("")
    (design_dir / "design.md").write_text("\n".join(lines))
    return design_dir


def _run(design_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(design_dir)],
        capture_output=True,
        text=True,
        check=False,
    )


# (a) well-formed design.md → exit 0, no BLOCKED verdict anywhere
def test_well_formed_passes(tmp_path: Path) -> None:
    design_dir = _build_design_md(tmp_path)
    result = _run(design_dir)
    assert result.returncode == 0, f"stderr={result.stderr!r}"
    assert "BLOCKED" not in result.stderr
    assert "BLOCKED" not in result.stdout


# (b) missing ## Behaviors → exit 1, JSON missing=["Behaviors"] on stderr
def test_missing_behaviors_blocked(tmp_path: Path) -> None:
    sections = _well_formed_sections()
    del sections["Behaviors"]
    design_dir = _build_design_md(tmp_path, sections)
    result = _run(design_dir)
    assert result.returncode == 1
    assert "BLOCKED" not in result.stdout, "verdict must be on stderr, not stdout"
    verdict = json.loads(result.stderr)
    assert verdict["verdict"] == "BLOCKED"
    assert verdict["schema_version"] == 1
    assert "Behaviors" in verdict["missing"]


# (c) empty ## Constraints → exit 1, JSON empty=["Constraints"] on stderr
def test_empty_constraints_blocked(tmp_path: Path) -> None:
    sections = _well_formed_sections()
    sections["Constraints"] = ""
    design_dir = _build_design_md(tmp_path, sections)
    result = _run(design_dir)
    assert result.returncode == 1
    verdict = json.loads(result.stderr)
    assert "Constraints" in verdict["empty"]


# (d) Scope present but its ### In scope is "..." only → placeholder_only=["Scope.In scope"]
def test_scope_in_scope_placeholder_only_blocked(tmp_path: Path) -> None:
    sections = _well_formed_sections()
    sections["Scope"] = (
        "### In scope\n"
        "...\n\n"
        "### Out of scope\n"
        "The orchestrator itself is a separate design."
    )
    design_dir = _build_design_md(tmp_path, sections)
    result = _run(design_dir)
    assert result.returncode == 1
    verdict = json.loads(result.stderr)
    assert "Scope.In scope" in verdict["placeholder_only"]


# (e) missing ## Problem → exit 1, JSON missing=["Problem"] on stderr
def test_missing_problem_blocked(tmp_path: Path) -> None:
    sections = _well_formed_sections()
    del sections["Problem"]
    design_dir = _build_design_md(tmp_path, sections)
    result = _run(design_dir)
    assert result.returncode == 1
    verdict = json.loads(result.stderr)
    assert "Problem" in verdict["missing"]


# (f) missing ## Vision alignment → exit 1, JSON missing=["Vision alignment"] on stderr
def test_missing_vision_alignment_blocked(tmp_path: Path) -> None:
    sections = _well_formed_sections()
    del sections["Vision alignment"]
    design_dir = _build_design_md(tmp_path, sections)
    result = _run(design_dir)
    assert result.returncode == 1
    verdict = json.loads(result.stderr)
    assert "Vision alignment" in verdict["missing"]


# (g) missing optional ## Open Questions → exit 0, warning on stderr, NOT JSON
def test_missing_optional_open_questions_warns(tmp_path: Path) -> None:
    sections = _well_formed_sections()
    del sections["Open Questions"]
    design_dir = _build_design_md(tmp_path, sections)
    result = _run(design_dir)
    assert result.returncode == 0, f"stderr={result.stderr!r}"
    assert result.stderr.strip() != "", "expected human-readable warning on stderr"
    with pytest.raises(json.JSONDecodeError):
        json.loads(result.stderr)
    assert "Open Questions" in result.stderr


# (h) required section whose only content lives in ### subsections is acceptable.
# This matches the real-world writing convention of design.md files in this repo
# (e.g., the design-pipeline-auto-mode design.md has its Behaviors section
# populated entirely via ### Skill shape A/B/C subsections).
def test_required_section_with_only_subsections_passes(tmp_path: Path) -> None:
    sections = _well_formed_sections()
    sections["Behaviors"] = (
        "### Skill shape A\n"
        "Validator gate that runs the deterministic floor check on design.md.\n\n"
        "### Skill shape B\n"
        "Generator that derives output from existing artifacts without user Q&A.\n\n"
        "### Skill shape C\n"
        "Audit with confidence-based dispatch over findings."
    )
    design_dir = _build_design_md(tmp_path, sections)
    result = _run(design_dir)
    assert result.returncode == 0, f"stderr={result.stderr!r}"
    assert "BLOCKED" not in result.stderr


# (i) Task 9.1 — floor: 2 design: missing Consumer-repo behaviour section
#     is a BLOCK (exit 1, listed under "missing"), present section passes.
def test_floor2_requires_consumer_repo_section(tmp_path: Path) -> None:
    section = "Consumer-repo behaviour"

    # Without the section → BLOCKED, listed under "missing".
    # Without the section → BLOCKED, listed under "missing".
    sections = _well_formed_sections()
    design_dir = _build_design_md(
        tmp_path, sections, title="floor2-no-section", frontmatter={"floor": "2"}
    )
    result = _run(design_dir)
    assert result.returncode == 1, f"stderr={result.stderr!r}"
    assert "BLOCKED" not in result.stdout, "verdict must be on stderr, not stdout"
    verdict = json.loads(result.stderr)
    assert verdict["verdict"] == "BLOCKED"
    assert section in verdict["missing"]

    # With the section → PASS (exit 0), no BLOCKED verdict.
    sections = _well_formed_sections()
    sections[section] = (
        "Ships as a skills/_shared helper that runs inside the user's repo, "
        "not only in the framework development checkout."
    )
    design_dir = _build_design_md(
        tmp_path, sections, title="floor2-with-section", frontmatter={"floor": "2"}
    )
    result = _run(design_dir)
    assert result.returncode == 0, f"stderr={result.stderr!r}"
    assert "BLOCKED" not in result.stderr


# (j) Task 9.1 — legacy (un-stamped) design: missing Consumer-repo behaviour
#     section is a stderr warning only, NOT a block (exit 0).
def test_legacy_design_missing_section_warns_only(tmp_path: Path) -> None:
    sections = _well_formed_sections()  # no Consumer-repo behaviour section
    design_dir = _build_design_md(tmp_path, sections)  # no frontmatter stamp
    result = _run(design_dir)
    assert result.returncode == 0, f"stderr={result.stderr!r}"
    assert "BLOCKED" not in result.stderr
    assert "BLOCKED" not in result.stdout
    # Warning on stderr, human-readable, never JSON.
    assert result.stderr.strip() != "", "expected a stderr warning"
    with pytest.raises(json.JSONDecodeError):
        json.loads(result.stderr)
    assert "Consumer-repo behaviour" in result.stderr
