"""Tests for skill_text.py - the one helper tests read a skill's text through.

Design: skill-context-diet-skills, Task 1.1. A skill may be split into a core
SKILL.md plus tier files named under its `## Tier map`. `read_skill_text`
returns the core and every tier file joined, so a test that pins a rule finds
it wherever the split put it. Behaviour only: inputs in, outputs out.

Run with: pytest skills/_shared/test_skill_text.py -q
"""
from __future__ import annotations

from pathlib import Path

import pytest

import skill_text

REPO_ROOT = Path(__file__).resolve().parents[2]

CORE_WITH_MAP = (
    "---\nname: demo\n---\n"
    "# Demo\n\n"
    "## Purpose\n\nDo the thing.\n\n"
    "## Tier map\n\n"
    "- Read `a.md` in full at tier 1.\n"
    "- Read `b.md` in full at tier 2.\n"
    "- See `skills/x/c.md` for background (a path, not a tier file).\n\n"
    "## After the map\n\n"
    "Mentions `later.md` but sits past the map.\n"
)


def make_skill(root: Path, name: str, core: str, tiers: dict[str, str]) -> None:
    """Write skills/<name>/SKILL.md plus the given tier files under root."""
    skill_dir = root / "skills" / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(core, encoding="utf-8")
    for fname, body in tiers.items():
        (skill_dir / fname).write_text(body, encoding="utf-8")


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    make_skill(tmp_path, "mapped", CORE_WITH_MAP, {"a.md": "AAA\n", "b.md": "BBB\n"})
    make_skill(tmp_path, "plain", "# Plain\n\nNo map here, see `x.md`.\n", {})
    make_skill(
        tmp_path,
        "broken",
        "# Broken\n\n## Tier map\n\n- `a.md`\n- `gone.md`\n",
        {"a.md": "AAA\n"},
    )
    return tmp_path


def test_tier_map_lists_bare_md_names_in_order(tree: Path) -> None:
    assert skill_text.tier_map("mapped", root=tree) == ["a.md", "b.md"]


def test_tier_map_ignores_backticked_paths(tree: Path) -> None:
    assert "skills/x/c.md" not in skill_text.tier_map("mapped", root=tree)


def test_tier_map_stops_at_the_next_h2(tree: Path) -> None:
    assert "later.md" not in skill_text.tier_map("mapped", root=tree)


def test_tier_map_is_empty_without_a_map(tree: Path) -> None:
    assert skill_text.tier_map("plain", root=tree) == []


def test_skill_paths_is_core_then_tier_files(tree: Path) -> None:
    base = tree / "skills" / "mapped"
    assert skill_text.skill_paths("mapped", root=tree) == [
        base / "SKILL.md",
        base / "a.md",
        base / "b.md",
    ]


def test_skill_paths_without_a_map_is_the_core_alone(tree: Path) -> None:
    assert skill_text.skill_paths("plain", root=tree) == [
        tree / "skills" / "plain" / "SKILL.md"
    ]


def test_skill_paths_names_a_missing_tier_file(tree: Path) -> None:
    with pytest.raises(FileNotFoundError, match="gone.md"):
        skill_text.skill_paths("broken", root=tree)


def test_read_skill_text_joins_core_and_tier_files(tree: Path) -> None:
    assert skill_text.read_skill_text("mapped", root=tree) == (
        CORE_WITH_MAP + "\n" + "AAA\n" + "\n" + "BBB\n"
    )


def test_read_skill_text_without_a_map_is_the_core_alone(tree: Path) -> None:
    core = (tree / "skills" / "plain" / "SKILL.md").read_text(encoding="utf-8")
    assert skill_text.read_skill_text("plain", root=tree) == core


def test_read_skill_text_raises_for_a_missing_tier_file(tree: Path) -> None:
    with pytest.raises(FileNotFoundError, match="gone.md"):
        skill_text.read_skill_text("broken", root=tree)


def test_default_root_is_the_repo_root() -> None:
    core = REPO_ROOT / "skills" / "tp-run-full-design" / "SKILL.md"
    assert skill_text.skill_paths("tp-run-full-design")[0] == core


def test_tier_map_files_exist() -> None:
    """Every tier file named by a real skill's map exists beside its SKILL.md."""
    missing = []
    for core in sorted((REPO_ROOT / "skills").glob("*/SKILL.md")):
        for fname in skill_text.tier_map(core.parent.name):
            if not (core.parent / fname).is_file():
                missing.append(f"{core.parent.name}/{fname}")
    assert missing == []
