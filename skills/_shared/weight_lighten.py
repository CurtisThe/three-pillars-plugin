"""``weight_class.py lighten`` — suggest a lighter (or default) weight class.

Reads the four rubric axes from flags or seed/design frontmatter, runs the lean
``recommend_class`` rubric and compares it with the declared class. Output is
one line: ``keep <class>`` | ``suggest <class> because <axis>`` |
``need-axes`` | ``bad-axis <name>``. A ``design.md`` class is never raised; a
``seed.md`` class is a default, not a floor.
"""
import re
from pathlib import Path

import jdi_eligibility
import safety_gate
from weight_class import (
    ESCALATION_ORDER,
    VALID_CLASSES,
    parse_frontmatter,
    read_class,
    recommend_class,
)

_AXES = ("risk", "blast_radius", "reversibility", "novelty")
_LEVELS = ("low", "medium", "high")
_SPAN = re.compile(r"`([^`\n]+)`")


def _read_fm(path: Path) -> dict:
    try:
        return parse_frontmatter(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return {}


def _paths(design_dir: Path) -> list:
    """Union of the design's ``## Scope`` paths and the seed's backtick spans."""
    found = []
    if (design_dir / "design.md").is_file():
        try:
            found = list(jdi_eligibility.scope_paths(str(design_dir)))
        except ValueError:
            found = []
    try:
        text = (design_dir / "seed.md").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return found
    return found + _SPAN.findall(text)


def _because(axes: dict, klass: str) -> str:
    if klass == "full":
        return "risk" if axes["risk"] == "high" else "blast_radius"
    if klass == "light":
        concern = dict(axes)
        concern["reversibility"] = {"high": "low", "medium": "medium",
                                    "low": "high"}[axes["reversibility"]]
        for name in _AXES:
            if concern[name] != "low":
                return name
    return "risk"


def lighten(design_dir, axes) -> tuple:
    """Return ``(line, rc)`` for the lighten suggestion (rc 2 on bad input)."""
    design_dir = Path(design_dir)
    design_fm = _read_fm(design_dir / "design.md")
    seed_fm = _read_fm(design_dir / "seed.md")
    merged = {}
    for name in _AXES:
        value = (axes or {}).get(name)
        if value is None:
            key = name.replace("_", "-")
            value = design_fm.get(key) or seed_fm.get(key)
        if value is not None:
            merged[name] = value
    if not merged:
        return ("need-axes", 2)
    for name in _AXES:
        if name in merged and merged[name] not in _LEVELS:
            return (f"bad-axis {name}", 2)
    if len(merged) < len(_AXES):
        return ("need-axes", 2)

    declared, source = read_class(design_dir)
    from_seed = False
    if source != "frontmatter" and seed_fm.get("weight-class") in VALID_CLASSES:
        declared, from_seed = seed_fm["weight-class"], True
    pinned = str(design_fm.get("pin-class", seed_fm.get("pin-class", ""))).lower() == "true"
    keep = (f"keep {declared}", 0)
    if pinned or declared not in ESCALATION_ORDER:
        return keep

    rubric, _ = recommend_class(*(merged[n] for n in _AXES))
    if rubric == "spike":
        return keep
    if rubric == "just-do-it":
        spans = _paths(design_dir)
        if any(safety_gate.touches_gate([p]) or jdi_eligibility.surface_hit(p)
               for p in spans):
            rubric = "light"
    if rubric == declared:
        return keep
    rank = ESCALATION_ORDER.index
    if not from_seed and rank(rubric) > rank(declared):
        return keep
    return (f"suggest {rubric} because {_because(merged, rubric)}", 0)
