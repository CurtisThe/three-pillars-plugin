#!/usr/bin/env python3
"""forge_floor.py -- the ``## Forge behaviour`` design-floor check (forge-interface 2.1).

At ``floor: 3`` a design whose weight class is not ``just-do-it`` and whose text
names a forge surface (a PR create / read / comment / label / merge, a review
loop, a merge gate, CI status, branch protection, or a ``gh`` / ``tea`` call)
must carry a non-placeholder ``## Forge behaviour`` section. Below floor 3, or at
just-do-it, the same shape only warns on stderr (one line).

The surface list is a closed, named table (``FORGE_SURFACES``): the check reads
prose for those keywords, so the table is the whole input domain and a keyword
is matched on word boundaries (a plural ``s`` is allowed) rather than as a bare
substring (``gh pr`` must not fire inside "high priority").

``floor_sections`` imports this module at load time; this module reads the floor
through ``floor_sections`` lazily, inside the functions, so there is no circular
import. Stdlib plus ``weight_class`` only.
"""
from __future__ import annotations

import re

import weight_class

# The section a forge-surface design must carry (exact heading text, a key not prose).
FORGE_SECTION = "Forge behaviour"

# The closed keyword table, matched case-insensitively. Order is the report order.
FORGE_SURFACES: tuple[str, ...] = (
    "pull request",
    "PR create",
    "PR read",
    "PR comment",
    "PR label",
    "PR merge",
    "review loop",
    "merge gate",
    "CI status",
    "branch protection",
    "gh pr",
    "gh api",
    "tea pr",
)

_FLOOR_THREE = 3
_CLASS_KEY = "weight-class"
_JUST_DO_IT = "just-do-it"


def _pattern(surface: str) -> re.Pattern[str]:
    """Word-bounded, case-insensitive pattern for one surface (optional plural ``s``)."""
    words = r"\s+".join(re.escape(w) for w in surface.split())
    return re.compile(rf"\b{words}s?\b", re.IGNORECASE)


_PATTERNS = tuple((surface, _pattern(surface)) for surface in FORGE_SURFACES)


def surfaces_named(text: str) -> list[str]:
    """The ``FORGE_SURFACES`` entries the text names, each once, in table order."""
    return [surface for surface, pattern in _PATTERNS if pattern.search(text)]


def required(text: str) -> bool:
    """True when the design must carry ``## Forge behaviour``.

    Floor >= 3, a weight class other than ``just-do-it`` (an absent class is not
    just-do-it), and at least one forge surface named.
    """
    import floor_sections  # lazy: floor_sections imports this module at load

    if floor_sections.floor_version(text) < _FLOOR_THREE:
        return False
    if weight_class.parse_frontmatter(text).get(_CLASS_KEY) == _JUST_DO_IT:
        return False
    return bool(surfaces_named(text))


def warning(text: str, sections: dict[str, str]) -> str | None:
    """The one-line stderr warning for a design that names a forge surface but
    carries no ``## Forge behaviour`` section and is NOT blocked on it, or ``None``.

    ``None`` when the section is required (absence is a block, handled by
    ``floor_sections``), when the section is present, or when no surface is named.
    """
    if required(text) or FORGE_SECTION in sections:
        return None
    named = surfaces_named(text)
    if not named:
        return None
    return (
        "warning: design.md names forge surface(s) "
        + ", ".join(named)
        + " but has no ## "
        + FORGE_SECTION
        + " section (required at floor 3, class above just-do-it)"
    )
