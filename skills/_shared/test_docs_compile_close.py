"""test_docs_compile_close.py — Task 1.5: close and reconcile run per folded slug inside the compile.

design: living-doc-fragments, Task 1.5 (§Interfaces step 3, PR-number fallback). Real temp git repos;
assertions are exact row text and printed lines (Oracle: example), never message wording
(test-fragility.md §2).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import docs_compile  # noqa: E402
import reconcile_docs  # noqa: E402
from test_docs_compile import ROADMAP, frag, git, make_repo  # noqa: E402

ARCHIVE = "three-pillars-docs/product_roadmap_archive.md"
DONE = "three-pillars-docs/completed-tp-designs/alpha"
DESIGN = "three-pillars-docs/tp-designs/alpha/design.md"  # the row owner must directory-resolve
ROW = f"| alpha | Fixture. | design | Completion PR pending — [design]({DONE}/design.md) | Docs |"
ROADMAP2 = """# Product Roadmap
*Last updated: 2019-05-05 — see [History](#roadmap-history) for the full changelog.*

## Current Focus
- focus one

## Design Inventory

### Active (arc)

| Name | What | Type | Status | Track |
|---|---|---|---|---|
| unrelated | Stays live. | design | Seed | Docs |

## Roadmap History

*Newest-first. One line per update.*
- **2019-05-05** — older entry
"""
BODY = f"\n## Roadmap\n\n### Active (arc)\n+ {ROW}\n"


def _repo(tmp_path, name="repo"):
    root = make_repo(tmp_path, {"alpha": frag("alpha", "2020-01-02", BODY)}, docs={ROADMAP: ROADMAP2, DESIGN: "# alpha\n"}, name=name)
    return root, git(root, "rev-parse", "HEAD")


def _row(text):
    return [ln for ln in text.splitlines() if ln.startswith("| alpha ")]


def test_inventory_row_moved_and_pr_written_after_fold(tmp_path):
    root, base = _repo(tmp_path)
    result = docs_compile.compile_all(root, base_ref=base, prs={"alpha": 7}, commit=True)
    assert result.folded == ["alpha"] and result.refused == []
    assert _row((root / ROADMAP).read_text(encoding="utf-8")) == []
    (moved,) = _row((root / ARCHIVE).read_text(encoding="utf-8"))
    assert "Done — PR #7" in moved and "pending" not in moved
    assert git(root, "status", "--porcelain") == ""


def test_unknown_pr_uses_merged_pr_number_and_prints_line(tmp_path, monkeypatch, capsys):
    root, base = _repo(tmp_path)
    monkeypatch.setattr(reconcile_docs, "merged_pr_number", lambda _root, _slug, gh_fn=None: 9)
    assert docs_compile.main(["--base-ref", base, "--commit", "--repo-root", str(root)]) == 0
    (moved,) = _row((root / ARCHIVE).read_text(encoding="utf-8"))
    assert "Done — PR #9" in moved
    assert "PR number unknown" not in capsys.readouterr().out

    other, other_base = _repo(tmp_path, "again")
    monkeypatch.setattr(reconcile_docs, "merged_pr_number", lambda _root, _slug, gh_fn=None: None)
    assert docs_compile.main(["--base-ref", other_base, "--commit", "--repo-root", str(other)]) == 0
    assert "docs-compile: PR number unknown for alpha" in capsys.readouterr().out
    (moved,) = _row((other / ARCHIVE).read_text(encoding="utf-8"))
    assert "Done (completion PR)" in moved
