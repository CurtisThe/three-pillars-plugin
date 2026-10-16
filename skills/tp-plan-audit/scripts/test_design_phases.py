"""test_design_phases.py — the declared Implementation Order phase list.

design: consumer-repo-parity (H4, Phase 3, Task 3.3)

``parse_implementation_order(detailed)`` → ``{canonical, shape, phases,
errors}``, where ``phases`` is the list of phase titles in order (a list of
strings, for ``check_phase_alignment``'s count comparison). Two shapes are
declared:

* ``list`` — top-level (unindented) ``N. **Title**`` items, numbered 1..n
  consecutively; indented lines are continuations of the preceding item.
* ``headings`` — ``### Phase N:`` / ``## Phase N:`` headings (today's legacy
  form, replicated from ``audit_plan.extract_design_phases``).

Headings win when any Phase heading is present: numbered bold steps inside a
phase body are body text, not a shape switch. A section in neither shape is
non-canonical and the errors name both shapes. Stdlib-only module under test.
"""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from design_phases import parse_implementation_order  # noqa: E402


LIST_DESIGN = textwrap.dedent("""\
    ## Implementation Order

    1. **Foundation** — write tests, then implement
       the core parser module.
    2. **Integration** — wire the parser into the
       audit entry point and extend the suite.
    3. **Hardening** — pin the exit contract.

    ## Interfaces
""")

H3_DESIGN = textwrap.dedent("""\
    ## Implementation Order

    ### Phase 1: Foundation
    - Set up widget module

    ### Phase 2: Integration
    - Wire to app
""")

H2_DESIGN = textwrap.dedent("""\
    ## Implementation Order

    ## Phase 1: Foundation
    - Set up widget module

    ## Phase 2: Integration
    - Wire to app

    ## Other Section
""")

# A legacy headings section whose phase bodies list numbered bold steps: the
# steps are body text, so the shape stays `headings` (no "mixed" error).
H3_WITH_BOLD_STEPS = textwrap.dedent("""\
    ## Implementation Order

    ### Phase 1: Foundation
    1. **Tests** — first
    2. **Impl** — second

    ### Phase 2: Integration
    - Wire to app
""")

NEITHER_DESIGN = textwrap.dedent("""\
    ## Implementation Order

    Ship everything in one go, no phases declared.

    ## Interfaces
""")

NO_SECTION_DESIGN = textwrap.dedent("""\
    # Detailed Design

    ## Modules
    - widget

    ## Interfaces
""")


# --- list shape -------------------------------------------------------------

def test_list_shape_parses_titles_in_order():
    r = parse_implementation_order(LIST_DESIGN)
    assert r["canonical"] is True
    assert r["shape"] == "list"
    assert r["phases"] == ["Foundation", "Integration", "Hardening"]
    assert r["errors"] == []


def test_list_shape_indented_continuations_are_not_items():
    r = parse_implementation_order(LIST_DESIGN)
    # The continuation lines under item 1 and 2 must not become phases.
    assert len(r["phases"]) == 3
    assert r["canonical"] is True, r["errors"]


def test_list_shape_accepts_numbered_1_to_10():
    body = "\n".join(f"{n}. **Phase {n}** — step {n}" for n in range(1, 11))
    r = parse_implementation_order(f"## Implementation Order\n\n{body}\n")
    assert r["canonical"] is True, r["errors"]
    assert r["shape"] == "list"
    assert r["phases"] == [f"Phase {n}" for n in range(1, 11)]


def test_list_shape_non_consecutive_start_is_an_error():
    r = parse_implementation_order(textwrap.dedent("""\
        ## Implementation Order

        2. **First** — really
        3. **Second** — really
    """))
    assert r["canonical"] is False
    assert r["errors"]
    assert r["shape"] == "list"


def test_list_shape_gap_in_numbering_is_an_error():
    r = parse_implementation_order(textwrap.dedent("""\
        ## Implementation Order

        1. **First** — really
        3. **Third** — skipping two
    """))
    assert r["canonical"] is False
    assert r["errors"]
    assert r["shape"] == "list"


# --- headings shape ---------------------------------------------------------

def test_headings_shape_h3():
    r = parse_implementation_order(H3_DESIGN)
    assert r["canonical"] is True
    assert r["shape"] == "headings"
    assert r["phases"] == ["Foundation", "Integration"]
    assert r["errors"] == []


def test_headings_shape_h2_section_ends_at_next_non_phase_h2():
    r = parse_implementation_order(H2_DESIGN)
    assert r["canonical"] is True
    assert r["shape"] == "headings"
    assert r["phases"] == ["Foundation", "Integration"]
    assert r["errors"] == []


def test_headings_with_numbered_bold_steps_stay_headings():
    r = parse_implementation_order(H3_WITH_BOLD_STEPS)
    assert r["canonical"] is True
    assert r["shape"] == "headings"
    assert r["phases"] == ["Foundation", "Integration"]
    assert r["errors"] == []


def test_headings_shape_phase_numbering_is_not_constrained():
    r = parse_implementation_order(textwrap.dedent("""\
        ## Implementation Order

        ### Phase 1: One
        - a

        ### Phase 3: Three
        - b
    """))
    assert r["canonical"] is True, r["errors"]
    assert r["shape"] == "headings"
    assert r["phases"] == ["One", "Three"]


# --- neither shape ----------------------------------------------------------

def test_neither_shape_is_non_canonical_and_names_both_shapes():
    r = parse_implementation_order(NEITHER_DESIGN)
    assert r["canonical"] is False
    assert r["shape"] is None
    assert r["phases"] == []
    assert r["errors"]
    joined = " ".join(r["errors"])
    assert "1. **Title**" in joined
    assert "### Phase N:" in joined


def test_missing_implementation_order_is_non_canonical():
    r = parse_implementation_order(NO_SECTION_DESIGN)
    assert r["canonical"] is False
    assert r["shape"] is None
    assert r["phases"] == []
    assert r["errors"]
    joined = " ".join(r["errors"])
    assert "1. **Title**" in joined
    assert "### Phase N:" in joined


# --- return contract --------------------------------------------------------

def test_result_carries_exactly_the_four_keys():
    r = parse_implementation_order(LIST_DESIGN)
    assert set(r) == {"canonical", "shape", "phases", "errors"}


def test_canonical_shapes_have_no_errors_and_vica_versa():
    for doc in (LIST_DESIGN, H3_DESIGN, H2_DESIGN, H3_WITH_BOLD_STEPS):
        r = parse_implementation_order(doc)
        assert r["canonical"] is True, doc
        assert r["errors"] == []
    for doc in (NEITHER_DESIGN, NO_SECTION_DESIGN):
        r = parse_implementation_order(doc)
        assert r["canonical"] is False, doc
        assert r["errors"]
