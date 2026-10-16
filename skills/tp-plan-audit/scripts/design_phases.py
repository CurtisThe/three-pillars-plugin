"""design_phases.py — the detailed design's declared Implementation Order.

design: consumer-repo-parity (H4, Phase 3)

A detailed design declares its phases in the ``## Implementation Order``
section, in one of two shapes:

* ``list`` — top-level (unindented) ``N. **Title**`` items, numbered
  consecutively from 1; an indented line is a continuation of the item
  above it;
* ``headings`` — ``### Phase N:`` / ``## Phase N:`` headings (the legacy
  form that ``audit_plan.extract_design_phases`` accepts today).

Shape selection is one-way: any Phase heading makes the section ``headings``,
so a legacy phase body may list ``1. **Tests** …`` steps without changing the
shape (there is no "mixed" error). The ``list`` shape is considered only when
no Phase heading exists. A section in neither shape — or a missing
``Implementation Order`` section — is non-canonical, with errors that name
both declared shapes.

``phases`` is the list of phase title strings in order — the same shape
``extract_design_phases`` returned, so ``check_phase_alignment``'s count
comparison can consume it unchanged (Task 3.4 rewires the call site; this
module is the standalone parser). Stdlib only.
"""
from __future__ import annotations

import re

_SECTION_RE = re.compile(r"^##\s+Implementation Order", re.IGNORECASE)
# A `## ` heading that is NOT a Phase heading ends the section (replicates
# audit_plan.extract_design_phases' boundary rule).
_BOUNDARY_RE = re.compile(r"^##\s+")
_PHASE_HEAD_RE = re.compile(r"^#{2,3}\s+Phase\s+\d+:\s*(.+)")
# Top-level only: `^` with no leading-whitespace allowance, so indented
# continuation lines are never items.
_LIST_ITEM_RE = re.compile(r"^(\d+)\.\s+\*\*(.+?)\*\*")


def _section_lines(detailed: str) -> list[str] | None:
    """The Implementation Order section's lines, or None when absent.

    The section runs from ``## Implementation Order`` (case-insensitive) to
    the next non-Phase ``## `` heading; ``## Phase N:`` and ``### Phase N:``
    are kept inside it, as today's parser does.
    """
    out: list[str] = []
    found = False
    for line in detailed.split("\n"):
        if not found:
            if _SECTION_RE.match(line):
                found = True
            continue
        if _BOUNDARY_RE.match(line) and not _PHASE_HEAD_RE.match(line):
            break
        out.append(line)
    return out if found else None


def parse_implementation_order(detailed: str) -> dict:
    """Parse the declared phase list → ``{canonical, shape, phases, errors}``.

    ``shape`` is ``"list"`` or ``"headings"``, or ``None`` when the section is
    missing or in neither shape. ``phases`` is the list of phase titles in
    order. ``canonical`` is ``True`` exactly when a declared shape parsed with
    no errors (for ``list``: numbering 1..n consecutive).
    """
    section = _section_lines(detailed)
    if section is None:
        return {
            "canonical": False,
            "shape": None,
            "phases": [],
            "errors": [
                "no `## Implementation Order` section; declare the phases as "
                "numbered `1. **Title**` items or `### Phase N:` headings"
            ],
        }

    headings = [
        m.group(1).strip() for line in section if (m := _PHASE_HEAD_RE.match(line))
    ]
    if headings:  # any Phase heading wins; numbered steps in bodies are text
        return {"canonical": True, "shape": "headings",
                "phases": headings, "errors": []}

    items = [
        (int(m.group(1)), m.group(2).strip())
        for line in section if (m := _LIST_ITEM_RE.match(line))
    ]
    if not items:
        return {
            "canonical": False,
            "shape": None,
            "phases": [],
            "errors": [
                "Implementation Order is not a declared phase list: use "
                "numbered `1. **Title**` items or `### Phase N:` headings"
            ],
        }

    titles = [title for _num, title in items]
    numbers = [num for num, _title in items]
    if numbers == list(range(1, len(items) + 1)):
        return {"canonical": True, "shape": "list",
                "phases": titles, "errors": []}
    return {
        "canonical": False,
        "shape": "list",
        "phases": titles,
        "errors": [
            f"list numbering must be consecutive 1..n, got {numbers}"
        ],
    }
