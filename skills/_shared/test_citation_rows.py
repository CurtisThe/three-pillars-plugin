"""Tests for citation_rows.py — markdown row/cell helpers.

Carved from test_citation_liveness.py (Task 3.1 — invariant-citation-coherence).
Pure relocation: all tests pass unchanged; imports updated to citation_rows.

All hermetic: tmp-dir fixture repos, no network.

Run with: python -m pytest skills/_shared/test_citation_rows.py -q
"""

from __future__ import annotations

from pathlib import Path

import pytest


# ------------------------------------------------------------------ #
# Helpers — build fixture repos under tmp_path
# ------------------------------------------------------------------ #


def _tp_design(root: Path, slug: str) -> Path:
    d = root / "three-pillars-docs" / "tp-designs" / slug
    d.mkdir(parents=True, exist_ok=True)
    return d


def _completed(root: Path, slug: str) -> Path:
    d = root / "three-pillars-docs" / "completed-tp-designs" / slug
    d.mkdir(parents=True, exist_ok=True)
    return d


def _roadmap(root: Path, text: str) -> Path:
    p = root / "three-pillars-docs" / "product_roadmap.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


# ------------------------------------------------------------------ #
# owner_slug_of_row — directory-resolution, bullet rows, table priority
# ------------------------------------------------------------------ #


def test_owner_slug_of_row_table_priority_first(tmp_path):
    """Priority-first table: 'seeded' in cell 1 doesn't resolve; slug in cell 2 does.

    '| seeded | **`my-design`** | ... |' -> owner = 'my-design'
    """
    _completed(tmp_path, "my-design")
    from citation_rows import owner_slug_of_row

    line = "| seeded | **`my-design`** | Completion PR pending |\n"
    result = owner_slug_of_row(line, tmp_path)
    assert result == "my-design", (
        "cell 2 must be owner when cell 1 does not directory-resolve"
    )


def test_owner_slug_of_row_table_notes_slug_does_not_attribute(tmp_path):
    """Notes column slug must not attribute when owner cell resolves.

    '| bar | Completion PR pending | supersedes `foo` |' -> owner = 'bar'
    """
    _completed(tmp_path, "bar")
    _completed(tmp_path, "foo")
    from citation_rows import owner_slug_of_row

    line = "| bar | Completion PR pending | supersedes `foo` |\n"
    result = owner_slug_of_row(line, tmp_path)
    assert result == "bar", "bar in owner cell must resolve, not foo in notes"


def test_owner_slug_of_row_bullet_leading_token(tmp_path):
    """Bullet row: slug in leading bold/backtick position must be attributed.

    '- **`my-design`** — Done ...' -> owner = 'my-design'
    """
    _completed(tmp_path, "my-design")
    from citation_rows import owner_slug_of_row

    line = "- **`my-design`** — Done (2026-06-10), impl-audit pass.\n"
    result = owner_slug_of_row(line, tmp_path)
    assert result == "my-design", "leading bold/backtick token in bullet must be owner"


def test_owner_slug_of_row_bullet_prose_slug_does_not_attribute(tmp_path):
    """A slug mentioned only in the prose body of a bullet must not attribute.

    '- Some text about my-design here' -> owner = None (prose, not leading)
    """
    _completed(tmp_path, "my-design")
    from citation_rows import owner_slug_of_row

    line = "- Some text that mentions my-design as reference\n"
    result = owner_slug_of_row(line, tmp_path)
    assert result is None, "slug in bullet prose body must not attribute"


def test_owner_slug_of_row_non_table_non_bullet_returns_none(tmp_path):
    """A plain prose line must return None (no table, no bullet)."""
    _completed(tmp_path, "my-design")
    from citation_rows import owner_slug_of_row

    line = "my-design status: Completion PR pending\n"
    result = owner_slug_of_row(line, tmp_path)
    assert result is None, "plain prose line must always return None"


# ------------------------------------------------------------------ #
# Round-4 — F2: _BULLET_LEAD_RE prefix-slug boundary
# ------------------------------------------------------------------ #


@pytest.mark.parametrize("marker", ["- ", "* ", "  - "])
def test_bullet_prefix_slug_not_attributed_to_shorter(tmp_path, marker):
    """Bullet owned by LONGER slug must never attribute to shorter prefix slug.

    E.g. '- tp-merge-split currently ...' must NOT attribute to 'tp-merge'.
    Test both decorated (**`slug`**) and undecorated plain forms.
    """
    _completed(tmp_path, "tp-merge")
    _tp_design(tmp_path, "tp-merge-split")
    from citation_rows import owner_slug_of_row

    # Decorated form (bold+backtick)
    line_decorated = f"{marker}**`tp-merge-split`** — currently Completion PR pending.\n"
    result_dec = owner_slug_of_row(line_decorated, tmp_path)
    assert result_dec == "tp-merge-split", (
        f"marker {marker!r} (decorated): bullet must attribute to 'tp-merge-split', "
        f"not 'tp-merge'; got {result_dec!r}"
    )

    # Plain form (no decoration) — the known backtracking bug
    line_plain = f"{marker}tp-merge-split currently Completion PR pending.\n"
    result_plain = owner_slug_of_row(line_plain, tmp_path)
    assert result_plain == "tp-merge-split", (
        f"marker {marker!r} (plain): bullet must attribute to 'tp-merge-split', "
        f"not 'tp-merge'; got {result_plain!r}"
    )


@pytest.mark.parametrize("marker", ["- ", "* ", "  - "])
def test_bullet_marker_variants_attributed(tmp_path, marker):
    """All bullet marker variants ('- ', '* ', '  - ') must be owner-attributed."""
    _completed(tmp_path, "my-design")
    from citation_rows import owner_slug_of_row

    line = f"{marker}**`my-design`** — Done, impl-audit pass.\n"
    result = owner_slug_of_row(line, tmp_path)
    assert result == "my-design", (
        f"marker {marker!r}: bullet must attribute to 'my-design'; got {result!r}"
    )


def test_bullet_no_dir_returns_none(tmp_path):
    """'- **`not-a-design`** ... Completion PR pending' (no dir) -> None / never flip."""
    from citation_rows import owner_slug_of_row

    # not-a-design has no directory anywhere
    line = "- **`not-a-design`** — Done, Completion PR pending.\n"
    result = owner_slug_of_row(line, tmp_path)
    assert result is None, (
        "a bullet whose slug has no design directory must return None"
    )


# ------------------------------------------------------------------ #
# Round-4 — F3: pipe-in-table cell model (dispatch order, pipeless-margin,
# escaped pipes)
# ------------------------------------------------------------------ #


def test_bullet_with_pipe_in_prose_not_routed_to_table_branch(tmp_path):
    """A bullet whose prose contains '|' must NOT be routed to the table branch."""
    _completed(tmp_path, "my-design")
    from citation_rows import owner_slug_of_row

    # Bullet marker is anchor — pipe inside prose must not confuse
    line = "- **`my-design`** — see foo | bar for details.\n"
    result = owner_slug_of_row(line, tmp_path)
    assert result == "my-design", (
        "pipe in bullet prose must not route to table branch; bullet anchor takes priority"
    )


def test_pipeless_margin_table_row_attributes_correctly(tmp_path):
    """A pipeless-margin table row 'foo | bar | status' must attribute correctly.

    The naive split('|') drops parts[0] which contains the owner — we must only
    discard the leading margin when the stripped line actually starts with '|'.
    """
    _completed(tmp_path, "my-design")
    from citation_rows import owner_slug_of_row

    # No leading '|' — 'my-design' is in parts[0] which must not be dropped
    line = "my-design | some notes | Completion PR pending\n"
    result = owner_slug_of_row(line, tmp_path)
    assert result == "my-design", (
        "pipeless-margin row: owner token in parts[0] must be included, not discarded"
    )


def test_escaped_pipe_in_table_cell_no_phantom_split(tmp_path):
    r"""A \| escaped pipe in a table cell must NOT create phantom cells."""
    _completed(tmp_path, "my-design")
    from citation_rows import owner_slug_of_row

    # The \| is an escaped pipe inside the notes column — must not split into phantom cells
    line = r"| my-design | Status note with \| escaped pipe | Completion PR pending |" + "\n"
    result = owner_slug_of_row(line, tmp_path)
    assert result == "my-design", (
        r"escaped \| inside table cell must not create phantom cells that misattribute"
    )


# ------------------------------------------------------------------ #
# Round-4 — F4: _quoted_spans cross-cell quote pairing
# ------------------------------------------------------------------ #


def test_quoted_spans_reset_at_cell_separator(tmp_path):
    """A stray unbalanced quote in one cell must not swallow the status in the next.

    Row: | my-design | "stray quote | Completion PR pending |
    If _quoted_spans pairs the stray quote from cell 2 with something across the cell
    boundary, the status in cell 3 would be inside a 'quoted span' and skipped.
    """
    _completed(tmp_path, "my-design")
    _roadmap(
        tmp_path,
        "*Last updated: 2026-01-01*\n\n"
        "## Designs\n\n"
        '| `my-design` | "stray quote | Completion PR pending |\n',
    )
    from reconcile_docs import flip_status

    # Must still flip — stray quote in one cell must not suppress status in next
    edits = flip_status(tmp_path, "my-design", pr_number=5, apply=False)
    assert len(edits) == 1, (
        "stray unbalanced quote in one cell must not suppress status flip in next cell"
    )


# ------------------------------------------------------------------ #
# Round-5 — F2: _quoted_spans two-quote cross-cell
# ------------------------------------------------------------------ #


def test_quoted_spans_two_quote_cross_cell_swallows_status(tmp_path):
    """Two-quote fixture: naive cross-cell pairing must NOT swallow the status match.

    Row: | `my-design` | "stray | Completion PR pending | trailing " note |
    With naive (non-cell-resetting) quote scanning, the first " in cell 2 pairs
    with the trailing " in cell 4, making 'Completion PR pending' appear inside a
    quoted span — suppressing the flip. The per-cell reset must prevent this.

    Reverting _quoted_spans to plain line.find() must fail this test.
    """
    _completed(tmp_path, "my-design")
    _roadmap(
        tmp_path,
        "*Last updated: 2026-01-01*\n\n"
        "## Designs\n\n"
        '| `my-design` | "stray | Completion PR pending | trailing " note |\n',
    )
    from reconcile_docs import flip_status

    edits = flip_status(tmp_path, "my-design", pr_number=7, apply=False)
    assert len(edits) == 1, (
        "two-quote cross-cell: naive pairing swallows status match; per-cell reset must fire"
    )


# ------------------------------------------------------------------ #
# Round-5 — F3: _quoted_spans bullet-row pipe awareness
# ------------------------------------------------------------------ #


def test_quoted_spans_bullet_pipe_keeps_quote_protection(tmp_path):
    """A bullet row with a quoted fragment containing a pipe must keep quote protection.

    Bullet: - `my-design` — note with "quoted | piped" fragment; Completion PR pending
    On a bullet row '|' is prose — the quote must NOT be broken by the pipe,
    and if the status is inside the quoted fragment it must be treated as prose.
    """
    _completed(tmp_path, "my-design")
    _roadmap(
        tmp_path,
        "*Last updated: 2026-01-01*\n\n"
        "## Designs\n\n"
        '- `my-design` — note with "quoted Completion PR pending | piped" end\n',
    )
    from reconcile_docs import flip_status

    # The status is inside a quoted span on a bullet row — must NOT be flipped
    edits = flip_status(tmp_path, "my-design", pr_number=8, apply=False)
    assert len(edits) == 0, (
        "bullet row: quoted fragment with pipe must keep quote protection"
    )


def test_quoted_spans_table_row_per_cell_reset_still_works(tmp_path):
    """Table rows must still get per-cell pipe reset (not disabled by bullet fix).

    The fixture has an unclosed opening quote in cell 2, then the status in cell 3,
    then a closing quote in cell 4 — without per-cell reset the quote would span
    across all three cells and swallow the status match (0 edits). With per-cell
    reset, the stray open quote in cell 2 is terminated at the '|' boundary, so
    the status in cell 3 is unquoted (1 edit).
    """
    _completed(tmp_path, "my-design")
    _roadmap(
        tmp_path,
        "*Last updated: 2026-01-01*\n\n"
        "## Designs\n\n"
        '| `my-design` | "stray | Completion PR pending | trailing" note |\n',
    )
    from reconcile_docs import flip_status

    edits = flip_status(tmp_path, "my-design", pr_number=9, apply=False)
    assert len(edits) == 1, (
        "table row: per-cell quote reset must still prevent stray quote from swallowing status"
    )


# ------------------------------------------------------------------ #
# Round-5 — F5: escape-aware trailing-pipe detection
# ------------------------------------------------------------------ #


def test_split_table_cells_escaped_trailing_pipe_keeps_last_cell(tmp_path):
    r"""A row ending in \| must keep its last real cell.

    Row: | **Done** | my-slug \|
    has_trailing_pipe must not fire on the escaped \| at end — the last
    real cell is 'my-slug \\|' (before the escape), not discarded.
    """
    _completed(tmp_path, "my-slug")
    from citation_rows import owner_slug_of_row

    # Row ends in \| (escaped pipe) — this is NOT a standard GFM trailing margin
    line = r"| **Done** | my-slug \|" + "\n"
    result = owner_slug_of_row(line, tmp_path)
    assert result == "my-slug", (
        r"row ending in \| (escaped pipe): last real cell must not be discarded via "
        "has_trailing_pipe logic — owner must be found"
    )


# ------------------------------------------------------------------ #
# Round-5 — F6: escaped-pipe lookbehind pinning
# ------------------------------------------------------------------ #


def test_escaped_pipe_phantom_slug_before_true_owner(tmp_path):
    r"""Phantom split of \| must not surface a resolving slug BEFORE the true owner.

    Row: | note \| other-design | my-design | Completion PR pending |
    Without the (?<!\\) lookbehind, splitting on all '|' produces:
      ['', ' note \\', ' other-design ', ' my-design ', ...]
    The phantom cell ' other-design ' resolves before ' my-design ' — wrong.
    With the lookbehind, the split yields:
      ['', ' note \\| other-design ', ' my-design ', ...]
    And 'my-design' is correctly the first resolving cell.
    """
    _completed(tmp_path, "my-design")
    _completed(tmp_path, "other-design")
    from citation_rows import owner_slug_of_row

    line = r"| note \| other-design | my-design | Completion PR pending |" + "\n"
    result = owner_slug_of_row(line, tmp_path)
    assert result == "my-design", (
        r"escaped \| must not be treated as a cell separator — phantom 'other-design' "
        "cell must not surface before the true owner 'my-design'"
    )


# ------------------------------------------------------------------ #
# Round-6 — F5: _strip_markup \| replacement vs deletion
# ------------------------------------------------------------------ #


def test_strip_markup_escaped_pipe_midtoken_no_concatenation(tmp_path):
    r"""_strip_markup must replace \| with a space, not delete, to prevent mid-token
    concatenation.

    Cell 'f\|oo' renders as 'f|oo' (not the slug 'foo'). Deleting \| would produce
    'foo', falsely matching an archived slug. Replacing with a space produces 'f oo',
    which does not match any slug.
    """
    _completed(tmp_path, "foo")
    from citation_rows import owner_slug_of_row

    # The raw string r"f\|oo" is the cell content: 'f' + backslash + '|' + 'oo'
    # _strip_markup must replace \| with space → 'f oo' (not 'foo')
    line = r"| f\|oo | Completion PR pending |" + "\n"
    result = owner_slug_of_row(line, tmp_path)
    assert result is None, (
        r"_strip_markup must replace \| with space (not delete) — 'f\|oo' must not match 'foo'"
    )


def test_strip_markup_escaped_pipe_trailing_still_resolves(tmp_path):
    r"""_strip_markup with trailing \| artifact must still resolve the slug.

    Cell 'my-slug \|' after replacing \| with space → 'my-slug  ' → strip() → 'my-slug'.
    The slug must still resolve correctly.
    """
    _completed(tmp_path, "my-slug")
    from citation_rows import owner_slug_of_row

    # Trailing \| after the slug — strip() at end must clean it up
    line = r"| my-slug \| | Completion PR pending |" + "\n"
    result = owner_slug_of_row(line, tmp_path)
    assert result == "my-slug", (
        r"trailing \| artifact after slug must not prevent resolution — "
        "space replacement + strip() must yield the clean slug"
    )
