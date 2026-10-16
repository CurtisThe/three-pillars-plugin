"""Tier map pins for the tp-run-full-design core and its seven tier files.

Design: skill-context-diet-skills, Task 3.1; prose-pin-gate Task 1.5. The core
SKILL.md names each tier file under its Tier map, in parsed order. Sizes stay
under the per-file caps, and a missing tier file is a named error, never a
silent skip.

Run with: pytest skills/tp-run-full-design/scripts/test_tier_map.py -q
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_shared"))
import skill_text  # noqa: E402

SKILL_DIR = Path(__file__).resolve().parents[1]
SKILL = SKILL_DIR.name
TIER_FILES = ("audits.md", "tier-1-pickup.md", "tier-2-4-build.md", "tier-5-closeout.md",
              "tier-6-pr.md", "tier-7-review.md", "run-safety.md")
CORE_CAP = 20_000
TIER_CAP = 15_000


def test_tier_map_lists_the_seven_files_in_order() -> None:
    assert skill_text.tier_map(SKILL) == list(TIER_FILES)


@pytest.mark.parametrize("name", list(TIER_FILES))
def test_tier_file_exists(name: str) -> None:
    assert (SKILL_DIR / name).is_file()


def test_core_is_within_its_char_cap() -> None:
    assert len((SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")) <= CORE_CAP


@pytest.mark.parametrize("name", list(TIER_FILES))
def test_tier_file_is_within_its_char_cap(name: str) -> None:
    assert len((SKILL_DIR / name).read_text(encoding="utf-8")) <= TIER_CAP


def test_a_missing_tier_file_is_a_named_error(tmp_path: Path) -> None:
    copy = tmp_path / "skills" / SKILL
    copy.mkdir(parents=True)
    for md in SKILL_DIR.glob("*.md"):
        shutil.copy(md, copy / md.name)
    (copy / "run-safety.md").unlink()
    with pytest.raises(FileNotFoundError) as err:
        skill_text.skill_paths(SKILL, root=tmp_path)
    assert "run-safety.md" in str(err.value)
