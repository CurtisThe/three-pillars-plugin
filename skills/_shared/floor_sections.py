#!/usr/bin/env python3
"""floor_sections.py — stamp-keyed extra-section requirements for the design floor.

Task 9.1 (consumer-repo-parity). When a design.md carries the ``floor: 2``
frontmatter stamp, the floor schema additionally requires a
``Consumer-repo behaviour`` section. A legacy design (no stamp — ``floor``
defaults to 1) that is missing that section is NOT blocked; it emits a stderr
warning, like the optional sections.

forge-interface 2.1. At ``floor: 3`` a design that names a forge surface (and is
not just-do-it) also requires a ``Forge behaviour`` section — the check lives in
``forge_floor``; a design that names a surface below that bar only warns.

All the floor-keyed logic lives here so each validator
(validate_artifact.py and validate_design_floor.py) gains only an import and a
one-line call. This module must not import validate_artifact at load time:
validate_design_floor imports validate_artifact, so a top-level import here
would be circular. The content-floor predicate is therefore passed in by the
caller (validate_artifact's ``_is_non_placeholder_content``) rather than
imported.
"""
from __future__ import annotations

import sys

import forge_floor
import weight_class

# The section a stamped design must carry (exact heading text, a key not prose).
CONSUMER_REPO_SECTION = "Consumer-repo behaviour"
# The section a floor-3 forge-surface design must carry (owned by forge_floor).
FORGE_SECTION = forge_floor.FORGE_SECTION

_FLOOR_KEY = "floor"
_FLOOR_TWO = 2


def floor_version(text: str) -> int:
    """Return the design's floor as an int, defaulting to 1 (legacy).

    ``floor`` is read from the leading frontmatter via
    ``weight_class.parse_frontmatter``. Absent frontmatter, an absent key, or a
    non-integer value all resolve to 1: the floor only raises the bar when a
    design is explicitly stamped with an integer >= 2.
    """
    value = weight_class.parse_frontmatter(text).get(_FLOOR_KEY)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 1


def extra_required(text: str) -> list[str]:
    """Extra required sections for the design's floor.

    ``["Consumer-repo behaviour"]`` at floor >= 2, ``[]`` otherwise; plus
    ``"Forge behaviour"`` when ``forge_floor.required`` (floor >= 3, not
    just-do-it, a forge surface named).
    """
    extras: list[str] = []
    if floor_version(text) >= _FLOOR_TWO:
        extras.append(CONSUMER_REPO_SECTION)
    if forge_floor.required(text):
        extras.append(FORGE_SECTION)
    return extras


def _classify_extra(
    text: str,
    sections: dict[str, str],
    *,
    is_non_placeholder,
) -> dict[str, list[str]]:
    """Pure classification of the floor-keyed extra sections into
    ``missing`` / ``empty`` / ``placeholder_only`` (empty lists at floor < 2).

    No side effects — the caller decides whether to block on the result.
    ``is_non_placeholder`` is the caller's content-floor predicate, passed in
    to avoid importing validate_artifact here.
    """
    result: dict[str, list[str]] = {"missing": [], "empty": [], "placeholder_only": []}
    for name in extra_required(text):
        # The ## body plus each ### child, as the base required sections are read (L126).
        bodies = [b for k, b in sections.items() if k == name or k.startswith(f"{name}.")]
        if name not in sections:
            result["missing"].append(name)
        elif not any(b.strip() for b in bodies):
            result["empty"].append(name)
        elif not any(is_non_placeholder(b) for b in bodies if b.strip()):
            result["placeholder_only"].append(name)
    return result


def _legacy_warning(text: str, sections: dict[str, str]) -> str | None:
    """The stderr warning line for a legacy (un-stamped) design that is missing
    the ``Consumer-repo behaviour`` section, or ``None``.

    Returns ``None`` for a stamped design (where absence is a block, handled by
    ``_classify_extra``) and for any design that already carries the section.
    """
    if extra_required(text):
        return None
    if CONSUMER_REPO_SECTION in sections:
        return None
    return (
        "warning: design.md is missing the floor-2 section: "
        + CONSUMER_REPO_SECTION
    )


def apply(
    text: str,
    sections: dict[str, str],
    classification: dict[str, list[str]],
    *,
    is_non_placeholder,
) -> None:
    """Fold the floor-keyed extra sections into ``classification`` (in place)
    and, for a legacy (un-stamped) design missing the consumer section, or a
    design naming a forge surface without the Forge section below the floor-3
    bar, print a stderr warning (like the optional sections).

    The caller's existing block logic then picks the folded extras up. The
    warning is suppressed when the design is blocked (on the base sections or
    the floor extras) so a BLOCKED verdict stays the only stderr output — the
    JSON channel contract.
    """
    extras = _classify_extra(text, sections, is_non_placeholder=is_non_placeholder)
    for key, values in extras.items():
        classification[key].extend(values)

    blocked = any(classification[k] for k in ("missing", "empty", "placeholder_only"))
    if not blocked:
        for warn in (_legacy_warning(text, sections), forge_floor.warning(text, sections)):
            if warn is not None:
                print(warn, file=sys.stderr)
