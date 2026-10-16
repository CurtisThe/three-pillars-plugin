"""Tests for reconcile_docs.flip_status_with_skipped on the roadmap archive.

Design archive-slimming Task 1.5: a status row that moved to
product_roadmap_archive.md at design-complete (before the merge) still gets
its post-merge flip, processed per file alongside the live roadmap. The
live roadmap is still flipped as before, and the History-section exclusion
still applies in the archive.

Run with: python -m pytest skills/_shared/test_reconcile_docs_archive.py -q

All hermetic: tmp-dir fixture repos, no network.
"""

from __future__ import annotations

from pathlib import Path

# ------------------------------------------------------------------ #
# Fixture helpers (mirror test_reconcile_docs.py)
# ------------------------------------------------------------------ #


def _completed(root: Path, slug: str) -> Path:
    """Create completed-tp-designs/<slug>/ so owner_slug_of_row resolves rows."""
    d = root / "three-pillars-docs" / "completed-tp-designs" / slug
    d.mkdir(parents=True, exist_ok=True)
    return d


def _living_doc(root: Path, name: str, text: str) -> Path:
    p = root / "three-pillars-docs" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


STALE_ROW = "| my-slug | description | Done — completion PR pending |"
STALE_TEXT = "completion PR pending"
HISTORY_HEADING = "## Roadmap History — older entries"
HISTORY_BULLET = f"- 2026-01-01 — my-slug was {STALE_TEXT}."
INVENTORY_HEADING = "## Design Inventory — completed and superseded rows"

# ------------------------------------------------------------------ #
# Archive-only flip
# ------------------------------------------------------------------ #


def test_flip_updates_row_when_slug_lives_only_in_archive(tmp_path):
    """Archive holds the slug's stale row, live roadmap has none: the archive
    row gets the post-merge flip and the live roadmap is left untouched."""
    _completed(tmp_path, "my-slug")
    archive_rel = "three-pillars-docs/product_roadmap_archive.md"
    _living_doc(
        tmp_path,
        "product_roadmap_archive.md",
        "# Product Roadmap — Archive\n\n"
        f"{INVENTORY_HEADING}\n\n"
        "### Sub\n\n"
        f"{STALE_ROW}\n"
        f"\n{HISTORY_HEADING}\n\n"
        f"{HISTORY_BULLET}\n",
    )
    _living_doc(tmp_path, "product_roadmap.md", "*Last updated: 2026-01-01*\n")

    from reconcile_docs import flip_status_with_skipped

    edits, skipped = flip_status_with_skipped(tmp_path, "my-slug", pr_number=42, apply=True)
    assert skipped == []
    assert len(edits) == 1
    e = edits[0]
    assert e.path == archive_rel
    assert e.kind == "status-flip"
    assert "Done — merged PR #42" in e.after

    content = (tmp_path / archive_rel).read_text(encoding="utf-8")
    assert "Done — merged PR #42" in content
    assert STALE_ROW not in content
    # History-section exclusion still applies in the archive
    assert HISTORY_BULLET in content
    # Live roadmap untouched
    live = (tmp_path / "three-pillars-docs" / "product_roadmap.md").read_text(encoding="utf-8")
    assert live == "*Last updated: 2026-01-01*\n"


def test_flip_archive_only_returns_planned_edit_without_apply(tmp_path):
    """apply=False plans the archive flip and writes nothing."""
    _completed(tmp_path, "my-slug")
    archive_rel = "three-pillars-docs/product_roadmap_archive.md"
    archive_text = (
        f"{INVENTORY_HEADING}\n\n### Sub\n\n{STALE_ROW}\n"
    )
    _living_doc(tmp_path, "product_roadmap_archive.md", archive_text)
    live_text = "*Last updated: 2026-01-01*\n"
    _living_doc(tmp_path, "product_roadmap.md", live_text)

    from reconcile_docs import flip_status_with_skipped

    edits, skipped = flip_status_with_skipped(tmp_path, "my-slug", pr_number=42, apply=False)
    assert skipped == []
    assert len(edits) == 1
    assert edits[0].path == archive_rel
    assert "merged PR #42" in edits[0].after
    # No writes in plan mode
    assert (tmp_path / archive_rel).read_text(encoding="utf-8") == archive_text
    assert (tmp_path / "three-pillars-docs" / "product_roadmap.md").read_text(encoding="utf-8") == live_text


def test_flip_skips_archive_rows_in_history_section(tmp_path):
    """A stale row inside the archive's ## Roadmap History is never flipped."""
    _completed(tmp_path, "my-slug")
    archive_rel = "three-pillars-docs/product_roadmap_archive.md"
    history_row = f"| my-slug | moved earlier | Done — {STALE_TEXT} |"
    _living_doc(
        tmp_path,
        "product_roadmap_archive.md",
        f"{INVENTORY_HEADING}\n\n### Sub\n\n{STALE_ROW}\n"
        f"\n{HISTORY_HEADING}\n\n"
        f"{HISTORY_BULLET}\n\n"
        f"{history_row}\n",
    )
    _living_doc(tmp_path, "product_roadmap.md", "*Last updated: 2026-01-01*\n")

    from reconcile_docs import flip_status_with_skipped

    edits, skipped = flip_status_with_skipped(tmp_path, "my-slug", pr_number=42, apply=True)
    # Exactly the one live row is flipped; the history row is never touched
    assert skipped == []
    assert len(edits) == 1
    assert "Done — merged PR #42" in edits[0].after

    content = (tmp_path / archive_rel).read_text(encoding="utf-8")
    assert history_row in content, "history row must survive --apply untouched"
    assert "merged PR #42" not in content.split(HISTORY_HEADING)[1]


def test_flip_archive_without_live_roadmap(tmp_path):
    """No live roadmap file at all: the archive row still gets the flip."""
    _completed(tmp_path, "my-slug")
    archive_rel = "three-pillars-docs/product_roadmap_archive.md"
    _living_doc(
        tmp_path,
        "product_roadmap_archive.md",
        f"{INVENTORY_HEADING}\n\n### Sub\n\n{STALE_ROW}\n",
    )

    from reconcile_docs import flip_status_with_skipped

    edits, skipped = flip_status_with_skipped(tmp_path, "my-slug", pr_number=42, apply=True)
    assert skipped == []
    assert len(edits) == 1
    assert edits[0].path == archive_rel
    assert "Done — merged PR #42" in (tmp_path / archive_rel).read_text(encoding="utf-8")


# ------------------------------------------------------------------ #
# Row in both files — per-file ambiguity rule preserved
# ------------------------------------------------------------------ #


def test_flip_row_in_both_files_ambiguity_rule_applies_per_file(tmp_path):
    """A >1 unquoted match row in each file is skipped per file (existing
    ambiguity rule), and an unambiguous row in each file is flipped per file."""
    _completed(tmp_path, "my-slug")
    _completed(tmp_path, "other-slug")
    archive_rel = "three-pillars-docs/product_roadmap_archive.md"
    _living_doc(
        tmp_path,
        "product_roadmap.md",
        "*Last updated: 2026-01-01*\n\n"
        "## Designs\n\n"
        "| `my-slug` | Completion PR pending | also Completion PR pending |\n",
    )
    _living_doc(
        tmp_path,
        "product_roadmap_archive.md",
        f"{INVENTORY_HEADING}\n\n### Sub\n\n"
        "| `my-slug` | Completion PR pending | also Completion PR pending |\n"
        "| `other-slug` | Completion PR pending |\n",
    )

    from reconcile_docs import flip_status_with_skipped

    edits, skipped = flip_status_with_skipped(tmp_path, "my-slug", pr_number=42, apply=True)
    # Both ambiguous rows are considered: one skipped entry per file
    files = {s["file"] for s in skipped}
    assert files == {
        "three-pillars-docs/product_roadmap.md",
        "three-pillars-docs/product_roadmap_archive.md",
    }
    assert all(s["reason"] == "ambiguous-multi-match" for s in skipped)
    assert edits == []
    # Nothing written: both files retain their stale rows
    live = (tmp_path / "three-pillars-docs" / "product_roadmap.md").read_text(encoding="utf-8")
    archive = (tmp_path / archive_rel).read_text(encoding="utf-8")
    assert "merged PR" not in live
    assert "merged PR" not in archive


def test_flip_unambiguous_row_in_both_files_flips_both(tmp_path):
    """Unambiguous stale row in each file: both rows get the post-merge flip."""
    _completed(tmp_path, "my-slug")
    archive_rel = "three-pillars-docs/product_roadmap_archive.md"
    _living_doc(
        tmp_path,
        "product_roadmap.md",
        "*Last updated: 2026-01-01*\n\n"
        "## Designs\n\n"
        "| `my-slug` | Completion PR pending |\n",
    )
    _living_doc(
        tmp_path,
        "product_roadmap_archive.md",
        f"{INVENTORY_HEADING}\n\n### Sub\n\n"
        f"| `my-slug` | moved at design-complete | Done — {STALE_TEXT} |\n",
    )

    from reconcile_docs import flip_status_with_skipped

    edits, skipped = flip_status_with_skipped(tmp_path, "my-slug", pr_number=42, apply=True)
    assert skipped == []
    assert len(edits) == 2
    assert {e.path for e in edits} == {
        "three-pillars-docs/product_roadmap.md",
        archive_rel,
    }
    live = (tmp_path / "three-pillars-docs" / "product_roadmap.md").read_text(encoding="utf-8")
    archive = (tmp_path / archive_rel).read_text(encoding="utf-8")
    assert "merged PR #42" in live
    assert "Done — merged PR #42" in archive


# ------------------------------------------------------------------ #
# Task 1.9: the vision pair joins living_doc_archive.ARCHIVES — tolerated
# ------------------------------------------------------------------ #


import pytest  # noqa: E402

import reconcile_docs  # noqa: E402


@pytest.mark.parametrize("with_vision", [False, True])
def test_flip_ignores_a_vision_pair_beside_the_roadmap_pair(tmp_path, with_vision):
    _completed(tmp_path, "my-slug")
    _living_doc(tmp_path, "product_roadmap.md", f"# Roadmap\n\n{STALE_ROW}\n")
    if with_vision:
        vision = f"# Vision\n\n{STALE_ROW}\n"
        _living_doc(tmp_path, "vision.md", vision)
        _living_doc(tmp_path, "vision_archive.md", vision)
    edits, skipped = reconcile_docs.flip_status_with_skipped(
        tmp_path, "my-slug", 7, apply=True)
    assert skipped == [] and [e.path for e in edits] == ["three-pillars-docs/product_roadmap.md"]
    roadmap = (tmp_path / "three-pillars-docs" / "product_roadmap.md").read_text(encoding="utf-8")
    assert "merged PR #7" in roadmap
    if with_vision:
        for name in ("vision.md", "vision_archive.md"):
            assert (tmp_path / "three-pillars-docs" / name).read_text(encoding="utf-8") == vision
