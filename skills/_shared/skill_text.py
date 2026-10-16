"""skill_text.py - read a skill's full instruction text, core plus tier files.

A large skill may be split into a core `SKILL.md` plus reference ("tier")
files that sit beside it. The core names them under a `## Tier map` heading,
each as a backticked bare file name such as `tier-1-pickup.md`. This module
is the ONE place that resolves that map, so a test pinning a rule reads
`read_skill_text(skill)` and finds the rule wherever the split put it.

Rules:
- Only a backticked bare `*.md` name (no `/`, no whitespace) is a tier file; a
  backticked path such as `skills/x/c.md` is a reference, not a tier file.
- The map runs from the `## Tier map` heading to the next `## ` heading.
- A tier file named in the map but absent on disk is a packaging bug:
  `skill_paths` raises `FileNotFoundError` naming it and never skips it.

Stdlib only. This module ships with the framework (it is not
`dev_only_shared`): `root` defaults to the repo root, two levels above this
file, so it resolves the same way in a consumer's install.
"""

from __future__ import annotations

from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parents[2]
_MAP_HEADING = "## Tier map"


def _skill_dir(skill: str, root: Path | None) -> Path:
    return (DEFAULT_ROOT if root is None else Path(root)) / "skills" / skill


def _read_core(skill: str, root: Path | None) -> str:
    return (_skill_dir(skill, root) / "SKILL.md").read_text(encoding="utf-8")


def _map_lines(core: str) -> list[str]:
    """Lines under the `## Tier map` heading, up to the next `## ` heading."""
    lines: list[str] = []
    in_map = False
    for line in core.splitlines():
        if in_map and line.startswith("## "):
            break
        if in_map:
            lines.append(line)
        elif line.strip() == _MAP_HEADING:
            in_map = True
    return lines


def _backticked_spans(line: str) -> list[str]:
    """The text between each pair of backticks on one line, in order."""
    return line.split("`")[1::2]


def _is_bare_md(span: str) -> bool:
    return span.endswith(".md") and "/" not in span and not any(c.isspace() for c in span)


def tier_map(skill: str, root: Path | None = None) -> list[str]:
    """Bare `*.md` names listed under the skill's `## Tier map`, in order, or []."""
    names: list[str] = []
    for line in _map_lines(_read_core(skill, root)):
        for span in _backticked_spans(line):
            if _is_bare_md(span) and span not in names:
                names.append(span)
    return names


def skill_paths(skill: str, root: Path | None = None) -> list[Path]:
    """`[SKILL.md, *tier files]`; raises FileNotFoundError naming a missing tier file."""
    base = _skill_dir(skill, root)
    paths = [base / "SKILL.md"]
    for name in tier_map(skill, root):
        tier_path = base / name
        if not tier_path.is_file():
            raise FileNotFoundError(
                f"{skill}: tier file {name} is named in the Tier map but missing: {tier_path}"
            )
        paths.append(tier_path)
    return paths


def read_skill_text(skill: str, root: Path | None = None) -> str:
    """The files of `skill_paths` joined by a newline (SKILL.md alone with no map)."""
    return "\n".join(path.read_text(encoding="utf-8") for path in skill_paths(skill, root))
