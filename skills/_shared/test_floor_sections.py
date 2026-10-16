"""Tests for floor_sections.py — stamp-keyed extra-section requirements.

Covers Task 9.1 (consumer-repo-parity): the design-floor schema gains an
extra required section once a design carries the ``floor: 2`` frontmatter
stamp, while a legacy (un-stamped) design only warns when that section is
missing. Assertions check keys and behaviour, never prose wording beyond the
exact ``## `` section name.

Run with: pytest skills/_shared/test_floor_sections.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import floor_sections  # noqa: E402
from validate_artifact import validate_artifact  # noqa: E402

SECTION = "Consumer-repo behaviour"


def _design(floor_line: str | None, with_section: bool = False) -> str:
    """A minimal design.md body. ``floor_line`` is a raw ``key: value`` frontmatter
    line (or None for no frontmatter). The extra section is appended when requested."""
    fm = ""
    if floor_line is not None:
        fm = "---\n" + floor_line + "\n---\n"
    body = (
        "# test-design\n\n"
        "## Problem\n"
        "A problem that is real and long enough to clear the content floor bar.\n\n"
        "## Vision alignment\n"
        "It advances the floor rather than the ceiling of the shared tooling.\n\n"
        "## Scope\n"
        "### In scope\n"
        "Retrofit the stamp-keyed floor check onto the two design validators.\n\n"
        "## Behaviors\n"
        "A stamped design blocks on the extra section; a legacy design only warns.\n\n"
        "## Constraints\n"
        "Stdlib only; no new dependency and no circular import at module load.\n"
    )
    if with_section:
        body += (
            "\n## Consumer-repo behaviour\n"
            "Ships as skills/_shared/floor_sections.py and runs in a user's repo.\n"
        )
    return fm + body


# ---------------------------------------------------------------------------
# floor_version — the stamp, defaulting to 1 (legacy)
# ---------------------------------------------------------------------------


def test_floor_version_defaults_to_1_without_frontmatter() -> None:
    assert floor_sections.floor_version(_design(None)) == 1


def test_floor_version_defaults_to_1_when_key_absent() -> None:
    text = "---\nweight-class: full\n---\n# t\n"
    assert floor_sections.floor_version(text) == 1


def test_floor_version_defaults_to_1_when_value_not_int() -> None:
    text = "---\nfloor: two\n---\n# t\n"
    assert floor_sections.floor_version(text) == 1


def test_floor_version_reads_the_stamp() -> None:
    assert floor_sections.floor_version(_design("floor: 2")) == 2
    assert floor_sections.floor_version(_design("floor: 3")) == 3


# ---------------------------------------------------------------------------
# extra_required — the extra section list per floor
# ---------------------------------------------------------------------------


def test_extra_required_lists_section_at_floor_two_and_three() -> None:
    assert floor_sections.extra_required(_design("floor: 2")) == [SECTION]
    assert floor_sections.extra_required(_design("floor: 3")) == [SECTION]


def test_extra_required_empty_below_floor_two() -> None:
    assert floor_sections.extra_required(_design(None)) == []
    assert floor_sections.extra_required(_design("floor: 1")) == []


# ---------------------------------------------------------------------------
# validate_artifact integration — stamped blocks, legacy warns
# ---------------------------------------------------------------------------


def test_validate_artifact_floor2_without_section_blocks(tmp_path: Path) -> None:
    path = tmp_path / "design.md"
    path.write_text(_design("floor: 2", with_section=False))
    result = validate_artifact("design", path)
    assert result.verdict == "BLOCKED"
    locations = {v.location for v in result.violations}
    assert SECTION in locations


def test_validate_artifact_floor2_with_section_passes(tmp_path: Path) -> None:
    path = tmp_path / "design.md"
    path.write_text(_design("floor: 2", with_section=True))
    result = validate_artifact("design", path)
    assert result.verdict == "PASS", f"violations={result.violations!r}"


@pytest.mark.parametrize("children,verdict", [
    ("### What ships\nShips as skills/_shared/floor_sections.py and runs in a user's repo.\n",
     "PASS"),
    ("### What ships\n\n### When a piece is absent\n", "BLOCKED")])
def test_validate_artifact_floor2_reads_subsections(tmp_path: Path, children, verdict) -> None:
    """L126: the section's ### children count, as they do for the base sections."""
    path = tmp_path / "design.md"
    path.write_text(_design("floor: 2") + "\n## Consumer-repo behaviour\n" + children)
    assert validate_artifact("design", path).verdict == verdict


def test_validate_artifact_legacy_without_section_warns_only(capsys, tmp_path: Path) -> None:
    path = tmp_path / "design.md"
    path.write_text(_design(None, with_section=False))
    result = validate_artifact("design", path)
    assert result.verdict == "PASS"
    err = capsys.readouterr().err
    assert SECTION in err
    assert "warning" in err.lower()
