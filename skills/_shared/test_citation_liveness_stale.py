"""Tests for citation_liveness.py — stale-row and heading regression suite.

Carved from test_citation_liveness.py (Task 3.1 — invariant-citation-coherence).
Covers: REGRESSION R2 (H1 history reset + heading-line cites), owner attribution,
bullet stale detection, fenced-code exclusions, superseded cites, and
quote-suppression for stale_status_rows.

All hermetic: tmp-dir fixture repos, no network.
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


def _skills_file(root: Path, rel: str, text: str) -> Path:
    p = root / "skills" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def _living_doc(root: Path, name: str, text: str) -> Path:
    p = root / "three-pillars-docs" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def _roadmap(root: Path, text: str) -> Path:
    return _living_doc(root, "product_roadmap.md", text)


# ------------------------------------------------------------------ #
# REGRESSION — R2: dead_design_cites H1 history-reset + heading-line cites
# ------------------------------------------------------------------ #


def test_h1_heading_exits_history_scope_and_cite_is_flagged(tmp_path):
    """An H1 heading (# Section) resets in_history=False after a ## History section.

    A dead cite on a line AFTER the H1 heading must be flagged even if a
    ## History section preceded it.
    """
    _completed(tmp_path, "gone-slug")
    _living_doc(
        tmp_path,
        "product_roadmap.md",
        "*Last updated: 2026-01-01*\n\n"
        "## History\n\n"
        "Old stuff: three-pillars-docs/tp-designs/gone-slug/design.md\n\n"
        "# Active Section\n\n"
        "See three-pillars-docs/tp-designs/gone-slug/design.md (live cite after H1)\n",
    )
    from citation_liveness import dead_design_cites

    results = dead_design_cites(tmp_path)
    # Only the cite AFTER the H1 heading must be flagged (history cite excluded)
    assert len(results) == 1, (
        "H1 heading must reset history scope — cite after H1 must be flagged"
    )
    assert results[0].kind == "living-doc"


def test_dead_cite_on_h1_heading_line_itself_is_flagged(tmp_path):
    """A dead cite that appears ON the H1 heading line itself must be flagged.

    H1 resets in_history first, then falls through to the cite scanner.
    """
    _completed(tmp_path, "gone-slug")
    _living_doc(
        tmp_path,
        "product_roadmap.md",
        "*Last updated: 2026-01-01*\n\n"
        "# Section tp-designs/gone-slug heading\n",
    )
    from citation_liveness import dead_design_cites

    results = dead_design_cites(tmp_path)
    assert len(results) == 1, (
        "dead cite on an H1 heading line must be flagged (fall-through after H1 reset)"
    )


def test_dead_cite_on_h2_non_history_heading_line_is_flagged(tmp_path):
    """A dead cite that appears ON an H2 non-History heading line must be flagged.

    The H2 heading sets in_history=False (non-History heading), then falls through
    to cite scanning.
    """
    _completed(tmp_path, "gone-slug")
    _living_doc(
        tmp_path,
        "product_roadmap.md",
        "*Last updated: 2026-01-01*\n\n"
        "## Designs tp-designs/gone-slug\n",
    )
    from citation_liveness import dead_design_cites

    results = dead_design_cites(tmp_path)
    assert len(results) == 1, (
        "dead cite on an H2 non-History heading line must be flagged"
    )


# ------------------------------------------------------------------ #
# REGRESSION — R2: stale_status_rows H1 reset + owner-cell attribution
# ------------------------------------------------------------------ #


def test_stale_rows_h1_heading_resets_history_scope(tmp_path):
    """A stale row after an H1 heading (following a ## History section) must be flagged.

    H1 exits the history scope so subsequent rows re-enter the active scan.
    """
    _completed(tmp_path, "my-design")
    _roadmap(
        tmp_path,
        "*Last updated: 2026-01-01*\n\n"
        "## Roadmap History\n\n"
        "| `my-design` | Completion PR pending |\n\n"
        "# Active\n\n"
        "| `my-design` | Completion PR pending |\n",
    )
    from citation_liveness import stale_status_rows

    results = stale_status_rows(tmp_path, live_branches=set())
    # Only the row after the H1 heading must be flagged
    assert len(results) == 1, (
        "H1 heading must reset history scope — stale row after H1 must be flagged"
    )
    assert results[0].slug == "my-design"


def test_stale_rows_unbackticked_owner_cell_attributed(tmp_path):
    """An unbackticked owner cell ('foo' not '`foo`') must be correctly attributed."""
    _completed(tmp_path, "my-design")
    _roadmap(
        tmp_path,
        "*Last updated: 2026-01-01*\n\n"
        "## Designs\n\n"
        "| my-design | Completion PR pending |\n",
    )
    from citation_liveness import stale_status_rows

    results = stale_status_rows(tmp_path, live_branches=set())
    assert len(results) == 1, (
        "unbackticked owner cell must be attributed by cell position, not backtick hunt"
    )
    assert results[0].slug == "my-design"


def test_stale_rows_backtick_in_notes_column_does_not_attribute(tmp_path):
    """A backticked archived slug in a notes column must NOT attribute the row.

    Row: | bar | Completion PR pending | supersedes `my-design` |
    stale_status_rows must NOT flag this row for 'my-design' — bar is the owner,
    and bar is not in completed-tp-designs.
    """
    _completed(tmp_path, "my-design")
    _tp_design(tmp_path, "bar")
    _roadmap(
        tmp_path,
        "*Last updated: 2026-01-01*\n\n"
        "## Designs\n\n"
        "| bar | Completion PR pending | supersedes `my-design` |\n",
    )
    from citation_liveness import stale_status_rows

    results = stale_status_rows(tmp_path, live_branches=set())
    assert results == [], (
        "backticked archived slug in notes column must not attribute the row"
    )


# ------------------------------------------------------------------ #
# Bullet-format stale row detection + owner_slug_of_row contract
# ------------------------------------------------------------------ #


def test_stale_status_rows_bullet_format_detected(tmp_path):
    """A bullet-format stale row must be detected by stale_status_rows."""
    _completed(tmp_path, "my-design")
    _roadmap(
        tmp_path,
        "*Last updated: 2026-01-01*\n\n"
        "### Recent completions\n\n"
        "- **`my-design`** — Done (2026-06-10), impl-audit pass. "
        "Completion PR pending (Tier 6).\n",
    )
    from citation_liveness import stale_status_rows

    results = stale_status_rows(tmp_path, live_branches=set())
    assert len(results) == 1, (
        "bullet-format stale row must be detected by stale_status_rows"
    )
    assert results[0].slug == "my-design"


def test_stale_status_rows_bullet_live_branch_not_flagged(tmp_path):
    """A bullet-format row must NOT be flagged when the branch is live."""
    _completed(tmp_path, "my-design")
    _roadmap(
        tmp_path,
        "*Last updated: 2026-01-01*\n\n"
        "### Recent completions\n\n"
        "- **`my-design`** — Done. Completion PR pending (Tier 6).\n",
    )
    from citation_liveness import stale_status_rows

    results = stale_status_rows(tmp_path, live_branches={"tp/my-design"})
    assert results == [], "bullet row with live branch must NOT be flagged"


def test_owner_slug_of_row_imported_by_reconcile_docs(tmp_path):
    """owner_slug_of_row must be importable from citation_liveness by reconcile_docs.

    Verifies the single shared implementation contract: reconcile_docs imports
    owner_slug_of_row from citation_liveness (not a local copy).
    """
    import reconcile_docs
    import citation_liveness
    assert reconcile_docs.owner_slug_of_row is citation_liveness.owner_slug_of_row, (
        "reconcile_docs.owner_slug_of_row must be imported from citation_liveness "
        "(single shared implementation — ONE definition total)"
    )


# ------------------------------------------------------------------ #
# Task 2.5 — Acceptance: zero dead cites in real repo
# ------------------------------------------------------------------ #


def test_repo_tree_has_zero_dead_design_cites():
    """After the sweep, no dead tp-designs/* cites exist in the repo tree."""
    repo_root = Path(__file__).resolve().parents[2]
    from citation_liveness import dead_design_cites

    results = dead_design_cites(repo_root)
    assert results == [], (
        f"Found {len(results)} dead design cite(s) — run reconcile_docs.py "
        f"--sweep --apply to clear them:\n"
        + "\n".join(f"  {r.path}:{r.line}  slug={r.slug}" for r in results)
    )


# ------------------------------------------------------------------ #
# Round-4 — F2: bullet prefix stale detection via stale_status_rows
# ------------------------------------------------------------------ #


def test_bullet_longer_prefix_pair_stale_detection(tmp_path):
    """stale_status_rows: bullet for longer slug detected, shorter slug NOT detected."""
    _completed(tmp_path, "tp-merge")
    _completed(tmp_path, "tp-merge-split")
    _roadmap(
        tmp_path,
        "*Last updated: 2026-01-01*\n\n"
        "### Recent completions\n\n"
        "- **`tp-merge-split`** — Done. Completion PR pending (Tier 6).\n",
    )
    from citation_liveness import stale_status_rows

    results = stale_status_rows(tmp_path, live_branches=set())
    slugs = [r.slug for r in results]
    assert "tp-merge-split" in slugs, "tp-merge-split bullet must be detected as stale"
    assert "tp-merge" not in slugs, "tp-merge must NOT be attributed from tp-merge-split bullet"


# ------------------------------------------------------------------ #
# Round-4 — F3: pipeless margin stale via stale_status_rows
# ------------------------------------------------------------------ #


def test_pipeless_margin_flip_not_wrong_row(tmp_path):
    """stale_status_rows must detect both pipeless and standard rows correctly."""
    _completed(tmp_path, "my-design")
    _completed(tmp_path, "other-design")
    _roadmap(
        tmp_path,
        "*Last updated: 2026-01-01*\n\n"
        "## Designs\n\n"
        "| `my-design` | Completion PR pending |\n"
        "other-design | Completion PR pending\n",  # pipeless-margin
    )
    from citation_liveness import stale_status_rows

    results = stale_status_rows(tmp_path, live_branches=set())
    slugs = {r.slug for r in results}
    assert "my-design" in slugs
    assert "other-design" in slugs


# ------------------------------------------------------------------ #
# Round-4 — F5: fenced code block awareness
# ------------------------------------------------------------------ #


def test_fenced_code_block_dead_cite_not_scanned(tmp_path):
    """A dead cite inside a fenced code block in a living doc must not be flagged."""
    _completed(tmp_path, "gone-slug")
    _living_doc(
        tmp_path,
        "product_roadmap.md",
        "*Last updated: 2026-01-01*\n\n"
        "## Active\n\n"
        "```\n"
        "three-pillars-docs/tp-designs/gone-slug/design.md\n"
        "```\n",
    )
    from citation_liveness import dead_design_cites

    results = dead_design_cites(tmp_path)
    assert results == [], "dead cite inside fenced code block must not be flagged"


def test_fenced_code_block_stale_row_not_detected(tmp_path):
    """stale_status_rows must skip rows inside fenced code blocks."""
    _completed(tmp_path, "my-design")
    _roadmap(
        tmp_path,
        "*Last updated: 2026-01-01*\n\n"
        "## Designs\n\n"
        "```\n"
        "| `my-design` | Completion PR pending |\n"
        "```\n",
    )
    from citation_liveness import stale_status_rows

    results = stale_status_rows(tmp_path, live_branches=set())
    assert results == [], "stale row inside fenced code block must not be detected"


# ------------------------------------------------------------------ #
# Round-5 — F7: code-scope fence tracking in dead_design_cites
# ------------------------------------------------------------------ #


def test_dead_cite_not_flagged_inside_skills_fence(tmp_path):
    """A dead cite inside a fenced code block in a skills/ file must NOT be flagged."""
    _completed(tmp_path, "gone-slug")
    _skills_file(
        tmp_path,
        "_shared/SKILL.md",
        "# My Skill\n\n"
        "Example usage:\n\n"
        "```\n"
        "# three-pillars-docs/tp-designs/gone-slug/design.md\n"
        "```\n\n"
        "Normal prose here.\n",
    )
    from citation_liveness import dead_design_cites

    results = dead_design_cites(tmp_path)
    assert results == [], (
        "dead cite inside fenced code block in skills/ file must not be flagged"
    )


# ------------------------------------------------------------------ #
# Round-6 — superseded-tp-designs cite not detected
# ------------------------------------------------------------------ #


def test_superseded_tp_designs_cite_not_detected(tmp_path):
    """A superseded-tp-designs/{slug} cite must NOT be detected as a dead cite."""
    _completed(tmp_path, "my-design")
    _living_doc(
        tmp_path,
        "product_roadmap.md",
        "*Last updated: 2026-01-01*\n\n"
        "## Designs\n\n"
        "See three-pillars-docs/superseded-tp-designs/my-design for prior art.\n",
    )
    from citation_liveness import dead_design_cites

    results = dead_design_cites(tmp_path)
    assert results == [], (
        "superseded-tp-designs/{slug} cite must NOT be detected as a dead cite"
    )


# ------------------------------------------------------------------ #
# Round-7 — F2: stale_status_rows quote-parity
# ------------------------------------------------------------------ #


def test_stale_status_rows_quoted_only_mention_not_reported(tmp_path):
    """A roadmap row whose ONLY stale-status mention is inside quote/backtick pairs
    must NOT be reported by stale_status_rows.
    """
    _completed(tmp_path, "my-design")
    _living_doc(
        tmp_path,
        "product_roadmap.md",
        "*Last updated: 2026-01-01*\n\n"
        "## Designs\n\n"
        '| `my-design` | "Completion PR pending" |\n',
    )
    from citation_liveness import stale_status_rows

    results = stale_status_rows(tmp_path, live_branches=set())
    assert results == [], (
        "quoted-only stale-status mention must NOT be reported by stale_status_rows"
    )


def test_stale_status_rows_unquoted_mention_still_reported(tmp_path):
    """An unquoted stale-status mention must still be reported by stale_status_rows."""
    _completed(tmp_path, "my-design")
    _living_doc(
        tmp_path,
        "product_roadmap.md",
        "*Last updated: 2026-01-01*\n\n"
        "## Designs\n\n"
        "| `my-design` | Completion PR pending |\n",
    )
    from citation_liveness import stale_status_rows

    results = stale_status_rows(tmp_path, live_branches=set())
    assert len(results) == 1, "unquoted stale-status mention must still be reported"
    assert results[0].slug == "my-design"
