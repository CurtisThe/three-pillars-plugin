"""test_docs_fold_issues.py — Task 1.3: `docs_fold.fold` on the known-issues and Vision sections.

design: living-doc-fragments, Task 1.3 (grammar: design §Entities). Docs are in-memory
`dict[rel, text]`; only `low_doc_parts.target_part` reads the disk, from a `tmp_path` root given as
`root=`. Exact output text is asserted (Oracle: example); reasons are never matched by wording
(test-fragility.md §2).
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tp-merge-from-main", "scripts"))

import changes_fragment as cf  # noqa: E402
import docs_fold  # noqa: E402
import low_doc_parts  # noqa: E402
import verify_atoms  # noqa: E402

KI = "three-pillars-docs/known_issues.md"
RESOLVED = "three-pillars-docs/known_issues_resolved.md"
ROADMAP = "three-pillars-docs/product_roadmap.md"
LOW1 = "three-pillars-docs/known_issues_low.md"
LOW2 = "three-pillars-docs/known_issues_low_2.md"
DATE = "2020-01-02"
FM = f"---\nslug: demo\nkind: design\ndate: {DATE}\n---\n"

KI_TEXT = """# Known Issues
*Last updated: 2019-05-05 — see [History](#history).*

## Critical / High

## Medium

### M34: `release.sh` hard-codes the ship list
Twice, beside `ship-list.json`.

### M35: `shipped_files` walks the working tree
Body of M35.

## History
- **2019-05-05** — first
"""

RESOLVED_TEXT = """# Known Issues — RESOLVED archive

## Critical / High

### H1 (RESOLVED 2019-01-01): old high
Old body.

## Medium

### M6 (RESOLVED 2019-01-01): old medium
Old medium body.
"""

LOW1_TEXT = "# Known Issues — Low (cold)\n\n### L1: first low\nLow body.\n"
LOW2_TEXT = "# Known Issues — Low (cold), part 2\n\n### L2: second low\nLow two body.\n"

ROADMAP_TEXT = "# Product Roadmap\n\n## Current Focus\n- focus one\n- focus two\n"


def _frag(body: str):
    fragment = cf.parse(FM + body, stem="demo")
    assert fragment.problems == []
    return fragment


def _write(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_add_routes_h_m_to_sections_and_l_to_low_part(tmp_path):
    _write(tmp_path, LOW1, LOW1_TEXT)
    _write(tmp_path, LOW2, LOW2_TEXT)
    assert low_doc_parts.target_part(tmp_path, 60) == LOW2
    docs = {KI: KI_TEXT, LOW1: LOW1_TEXT, LOW2: LOW2_TEXT}
    fragment = _frag("\n## Known issues — add\n\n### H-new-demo-boom: it explodes\nHigh body, {pr}.\n"
                     "\n### M-new-demo-slow: it is slow\nMedium body.\n"
                     "\n### L-new-demo-typo: a typo\nLow body.\n")
    result = docs_fold.fold(docs, fragment, pr=361, root=tmp_path)
    assert result.docs[KI] == KI_TEXT.replace(
        "*Last updated: 2019-05-05", f"*Last updated: {DATE}").replace(
        "## Critical / High\n\n", "## Critical / High\n\n### H-new-demo-boom: it explodes\n"
                                  "High body, PR #361.\n\n").replace(
        "Body of M35.\n", "Body of M35.\n\n### M-new-demo-slow: it is slow\nMedium body.\n")
    assert result.docs[LOW2] == LOW2_TEXT + "\n### L-new-demo-typo: a typo\nLow body.\n"
    assert result.docs[LOW1] == LOW1_TEXT
    assert result.directed == set()


def test_add_low_creates_the_part_target_part_names(tmp_path):
    fragment = _frag("\n## Known issues — add\n\n### L-new-demo-typo: a typo\nLow body.\n")
    result = docs_fold.fold({KI: KI_TEXT}, fragment, pr=None, root=tmp_path)
    assert result.docs[LOW1] == (low_doc_parts.part_header(1)
                                 + "### L-new-demo-typo: a typo\nLow body.\n")


def test_add_to_a_missing_section_is_a_fold_error(tmp_path):
    fragment = _frag("\n## Known issues — add\n\n### M-new-demo-slow: it is slow\nBody.\n")
    with pytest.raises(docs_fold.FoldError) as info:
        docs_fold.fold({KI: "# Known Issues\n\n## Critical / High\n"}, fragment, pr=None,
                       root=tmp_path)
    assert info.value.section == "Known issues — add"


def test_resolve_moves_entry_verbatim_with_resolved_heading():
    fragment = _frag("\n## Known issues — resolve\n\n- M34: fixed by demo, {pr}\n")
    result = docs_fold.fold({KI: KI_TEXT, RESOLVED: RESOLVED_TEXT}, fragment, pr=361)
    assert result.docs[KI] == KI_TEXT.replace(
        "*Last updated: 2019-05-05", f"*Last updated: {DATE}").replace(
        "### M34: `release.sh` hard-codes the ship list\nTwice, beside `ship-list.json`.\n\n", "")
    assert result.docs[RESOLVED] == RESOLVED_TEXT + (
        f"\n### M34 (RESOLVED {DATE}): `release.sh` hard-codes the ship list\n"
        "Twice, beside `ship-list.json`.\nfixed by demo, PR #361\n")
    assert result.directed == set()  # a resolve is a move, not a removal


def test_resolve_adds_the_missing_section_to_the_archive():
    archive = "# Known Issues — RESOLVED archive\n\n## Critical / High\n"
    fragment = _frag("\n## Known issues — resolve\n\n- M35: gone\n")
    result = docs_fold.fold({KI: KI_TEXT, RESOLVED: archive}, fragment, pr=None)
    assert result.docs[RESOLVED] == archive + (
        f"\n## Medium\n\n### M35 (RESOLVED {DATE}): `shipped_files` walks the working tree\n"
        "Body of M35.\ngone\n")
    assert "### M35" not in result.docs[KI]


def test_resolve_of_a_missing_id_is_a_fold_error():
    fragment = _frag("\n## Known issues — resolve\n\n- M99: nope\n")
    with pytest.raises(docs_fold.FoldError) as info:
        docs_fold.fold({KI: KI_TEXT, RESOLVED: RESOLVED_TEXT}, fragment, pr=None)
    assert info.value.section == "Known issues — resolve"


def test_directed_atoms_list_removed_lines():
    roadmap = ROADMAP_TEXT + "\n## Design Inventory\n| D7 | demo-row | open |\n- **`old`** — Done — PR #1\n"
    fragment = _frag("\n## Roadmap\n\n### Design Inventory\n- | D7 | demo-row | open |\n"
                     "+ | D7 | demo-row | done |\n- - **`old`** — Done — PR #1\n"
                     "\n### Current Focus\n- - focus two\n")
    result = docs_fold.fold({ROADMAP: roadmap}, fragment, pr=None)
    expected = set()
    for line in ("| D7 | demo-row | open |", "- **`old`** — Done — PR #1", "- focus two"):
        expected |= set(verify_atoms.atoms(line))
    assert expected  # the removed lines carry real atoms
    assert result.directed == expected


def test_vision_section_is_left_in_place():
    fragment = _frag("\n## Vision\n\nThe operator should reconsider the non-goals.\n")
    docs = {KI: KI_TEXT, ROADMAP: ROADMAP_TEXT}
    result = docs_fold.fold(docs, fragment, pr=361)
    assert result.docs == docs
    assert result.directed == set()
