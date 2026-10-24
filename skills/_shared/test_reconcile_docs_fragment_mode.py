"""Task 1.9: `reconcile_docs.py --archive-cites` / `--pre-merge` skip when a fragment exists.

design: living-doc-fragments. Oracle: example.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import reconcile_docs

DOCS = "three-pillars-docs"
ROADMAP = (f"# Roadmap\n\n## Design Inventory\n\n| demo | Fixture. | design | Completion PR pending "
           f"| Docs |\n- see three-pillars-docs/tp-designs/demo/design.md\n")


def _repo(root: Path) -> Path:
    (root / DOCS / "changes").mkdir(parents=True)
    (root / DOCS / "product_roadmap.md").write_text(ROADMAP, encoding="utf-8")
    (root / DOCS / "changes" / "demo.md").write_text(
        "---\nslug: demo\nkind: design\ndate: 2026-10-22\n---\n", encoding="utf-8")
    return root


def _snapshot(root: Path) -> dict:
    return {str(p): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


@pytest.mark.parametrize("flag", ["--archive-cites", "--pre-merge"])
def test_skips_with_fragment(tmp_path, capsys, flag):
    root = _repo(tmp_path)
    before = _snapshot(root)
    ret = reconcile_docs.main(["reconcile_docs.py", flag, "--slug", "demo", "--apply", "--json",
                               "--repo", str(root)])
    assert ret == 0
    assert json.loads(capsys.readouterr().out) == {"mode": "fragment", "edits": []}
    assert _snapshot(root) == before


def test_archive_cites_skips_with_fragment(tmp_path, capsys):
    test_skips_with_fragment(tmp_path, capsys, "--archive-cites")


def test_pre_merge_skips_with_fragment(tmp_path, capsys):
    test_skips_with_fragment(tmp_path, capsys, "--pre-merge")
