"""test_docs_fold_inventory.py — fix.2: a lone ``+`` table row lands in the section's last table.

design: living-doc-fragments, fidelity-audit fix 2. Under a ``##`` heading with ``###`` subsections a
lone ``+ | row |`` used to append after the last non-blank line of the whole section (here the
Superseded blockquote), outside any table, where ``inventory_archive`` cannot move it on ``close``.
Assertions compare exact output text and the mover's row count (Oracle: example), never reason wording.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))

import changes_fragment as cf  # noqa: E402
import docs_fold  # noqa: E402
import inventory_archive  # noqa: E402

ROADMAP = "three-pillars-docs/product_roadmap.md"
FM = "---\nslug: demo\nkind: design\ndate: 2020-01-02\n---\n"
ROADMAP_TEXT = """# Product Roadmap

## Design Inventory

> The archive holds completed rows.

### Active
| Design | Status |
|---|---|
| other | Done |

### Superseded by canon-reframe pivot

> Pre-pivot rows live in the archive.

## Roadmap History

- **2019-05-05** — older entry
"""
NO_TABLE_TEXT = ROADMAP_TEXT.replace("| Design | Status |\n|---|---|\n| other | Done |\n", "- plain bullet\n")


def _fold(text: str):
    fragment = cf.parse(FM + "\n## Roadmap\n\n### Design Inventory\n+ | demo | Done |\n", stem="demo")
    assert fragment.problems == []
    return docs_fold.fold({ROADMAP: text}, fragment, pr=None).docs[ROADMAP]


def test_row_lands_after_the_last_table_row(tmp_path):
    out = _fold(ROADMAP_TEXT)
    assert "| other | Done |\n| demo | Done |\n\n### Superseded" in out
    assert out.index("| demo | Done |") < out.index("Pre-pivot rows")


def test_close_can_move_the_folded_row(tmp_path):
    (tmp_path / "three-pillars-docs" / "tp-designs" / "demo").mkdir(parents=True)
    (tmp_path / ROADMAP).write_text(_fold(ROADMAP_TEXT), encoding="utf-8")
    result = inventory_archive.move_completed(tmp_path, "demo", apply=False)
    assert result.moved == 1 and result.rows == ["| demo | Done |"]


def test_a_section_without_a_table_raises_fold_error():
    with pytest.raises(docs_fold.FoldError) as info:
        _fold(NO_TABLE_TEXT)
    assert info.value.section == "Roadmap"
