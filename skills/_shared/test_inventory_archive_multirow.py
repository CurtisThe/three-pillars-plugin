"""test_inventory_archive_multirow.py — every inventory row of the slug moves.

PR #177 round 4: a slug promoted from a seed table keeps its seed row (in a
`| Priority | Design | What | Status |` wave table) above the Active row that
`/tp-design-learn` wrote. `move_completed` moves every row attributable to the
slug in one call, each under its own archive sub-heading with that table's
repeated header, so the Done row never stays live behind a stale seed row and
the `/tp-post-merge` re-run is the promised no-op.

Run with: python3 -m pytest skills/_shared/test_inventory_archive_multirow.py -q
"""
from __future__ import annotations

from pathlib import Path

import verify_moves
from inventory_archive import move_completed

LIVE_REL = "three-pillars-docs/product_roadmap.md"
ARCHIVE_REL = "three-pillars-docs/product_roadmap_archive.md"
SLUG = "promoted-slug"
SEED_HEAD = "### Process-hardening seeds (next fleet batch)"
ACTIVE_HEAD = "### Active (canon-reframe arc)"
SEED_ROW = f"| 2 | `{SLUG}` | The seed as triaged. | Seed |"
ACTIVE_ROW = f"| {SLUG} | What shipped. | design | Implemented — awaiting PR | Docs |"
OTHER_SEED = "| 1 | `other-seed` | Stays live. | Seed |"


def _repo(tmp_path: Path) -> Path:
    live = "\n".join([
        "# Product Roadmap", "", "## Design Inventory", "",
        SEED_HEAD, "", "| Priority | Design | What | Status |", "|---|---|---|---|",
        OTHER_SEED, SEED_ROW, "",
        ACTIVE_HEAD, "", "| Name | What | Type | Status | Track |", "|---|---|---|---|---|",
        ACTIVE_ROW, "", "## Methodology", "", "- stay live", "",
    ]) + "\n"
    (tmp_path / LIVE_REL).parent.mkdir(parents=True)
    (tmp_path / LIVE_REL).write_text(live, encoding="utf-8")
    for slug in (SLUG, "other-seed"):
        (tmp_path / "three-pillars-docs" / "completed-tp-designs" / slug).mkdir(parents=True)
    return tmp_path


def test_seed_and_active_rows_move_together_and_rerun_is_a_noop(tmp_path):
    root = _repo(tmp_path)
    before_live = (root / LIVE_REL).read_text(encoding="utf-8")

    result = move_completed(root, SLUG, apply=True)

    assert (result.moved, result.reason, result.rows) == (2, None, [SEED_ROW, ACTIVE_ROW])
    after_live = (root / LIVE_REL).read_text(encoding="utf-8")
    after_archive = (root / ARCHIVE_REL).read_text(encoding="utf-8")
    assert SLUG not in after_live and OTHER_SEED in after_live
    archive_lines = after_archive.splitlines()
    for heading, header, row in ((SEED_HEAD, "| Priority | Design | What | Status |", SEED_ROW),
                                 (ACTIVE_HEAD, "| Name | What | Type | Status | Track |", ACTIVE_ROW)):
        i = archive_lines.index(heading)  # each row sits under its own sub-heading
        assert archive_lines[i + 2:i + 5] == [header, archive_lines[i + 3], row]
        assert archive_lines.count(row) == 1
    assert verify_moves.verify_move(
        before_live, after_live, "", after_archive,
        scaffold=verify_moves.scaffold_lines(ARCHIVE_REL, after_archive)) == []

    again = move_completed(root, SLUG, apply=True)

    assert again.moved == 0 and SLUG in again.reason
    assert (root / LIVE_REL).read_text(encoding="utf-8") == after_live
    assert (root / ARCHIVE_REL).read_text(encoding="utf-8") == after_archive
