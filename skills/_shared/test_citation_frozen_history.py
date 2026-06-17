"""History-boundary scenarios for citation_frozen.is_frozen.

These lock the `## History` boundary contract: the boundary is owned by
citation_liveness._in_history and the scan-loop tracking shape. The helper
`_track_in_history` below mirrors that loop exactly (the same shape the real
scanner uses) so the cite-on-heading and first-line-after-History edges are
asserted in BOTH directions.

design: invariant-citation-coherence
"""

from __future__ import annotations

from citation_frozen import is_frozen
from citation_liveness import _in_history


def _track_in_history(lines: list[str]) -> list[bool]:
    """Mirror the scanner's in_history tracking, returning the state PER LINE.

    Boundary rule (matches citation_liveness): on a `## ` heading, set
    in_history = _in_history(title) and the heading line ITSELF is inside that
    section. An H1 `# ` (not `## `) exits history. The section runs until the
    next `## ` (any H2) or the next H1.
    """
    states: list[bool] = []
    in_history = False
    for line in lines:
        if line.startswith("# ") and not line.startswith("## "):
            in_history = False
        if line.startswith("## "):
            in_history = _in_history(line[3:].strip())
        # The state recorded for THIS line includes the heading itself.
        states.append(in_history)
    return states


PATH = "three-pillars-docs/architecture.md"


def test_cite_on_history_heading_line_is_frozen():
    lines = [
        "# Architecture",
        "Body cites invariant #99 here (live).",
        "## History of invariant #99",  # cite ON the History heading
        "- 2026-01-01 something",
    ]
    states = _track_in_history(lines)
    # The History heading line itself is inside history.
    assert states[2] is True
    assert is_frozen(PATH, lines[2], in_history=states[2], in_fence=False) is True


def test_body_inside_history_section_is_frozen():
    lines = [
        "## History",
        "An old note about invariant #99.",
    ]
    states = _track_in_history(lines)
    assert states[1] is True
    assert is_frozen(PATH, lines[1], in_history=states[1], in_fence=False) is True


def test_first_line_after_non_history_h2_following_history_is_live():
    # A `## History` section, then a NON-history `## `; the first line AFTER
    # that non-history heading must classify LIVE again.
    lines = [
        "## History",                        # 0 frozen
        "Old note invariant #99.",           # 1 frozen
        "## Current Constraints",            # 2 non-history H2 -> live
        "Body cites invariant #99 (live).",  # 3 first line after -> LIVE
    ]
    states = _track_in_history(lines)
    assert states[0] is True
    assert states[1] is True
    assert states[2] is False  # the non-history heading itself is live
    assert states[3] is False  # first line after -> live
    # The load-bearing assertion: the first body line after the non-history H2.
    assert is_frozen(PATH, lines[3], in_history=states[3], in_fence=False) is False


def test_non_history_h2_heading_itself_is_live():
    lines = [
        "## Constraints",
        "Body invariant #99.",
    ]
    states = _track_in_history(lines)
    assert states[0] is False
    assert is_frozen(PATH, lines[0], in_history=states[0], in_fence=False) is False


def test_h1_exits_history_scope():
    lines = [
        "## History",                  # 0 frozen
        "Old note invariant #99.",     # 1 frozen
        "# New Top Section",           # 2 H1 exits history -> live
        "Body invariant #99 (live).",  # 3 live
    ]
    states = _track_in_history(lines)
    assert states[0] is True
    assert states[1] is True
    assert states[2] is False
    assert states[3] is False
    assert is_frozen(PATH, lines[3], in_history=states[3], in_fence=False) is False


def test_consecutive_history_sections_stay_frozen():
    lines = [
        "## Roadmap History",          # 0 frozen (contains "History")
        "note invariant #99.",         # 1 frozen
        "## Change History",           # 2 still a History heading -> frozen
        "note invariant #99.",         # 3 frozen
    ]
    states = _track_in_history(lines)
    assert all(states)
