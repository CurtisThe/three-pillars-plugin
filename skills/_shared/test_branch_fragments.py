"""Tests for branch_fragments.py (design followups-1024, Task 1.5)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import branch_fragments  # noqa: E402
from test_docs_compile import ROADMAP, frag, git, make_repo  # noqa: E402

BODY = "\n## Roadmap\n\n### Current Focus\n- - focus one\n+ - focus new\n"
CHANGES = "three-pillars-docs/changes"
PREFIX = "stale-anchor: other (origin/tp/other): "


def _repo(tmp_path, with_ref=True):
    root = make_repo(tmp_path, {})
    if not with_ref:
        return root
    git(root, "checkout", "-q", "-b", "tp/other")
    (root / CHANGES).mkdir(parents=True, exist_ok=True)
    (root / CHANGES / "other.md").write_text(frag("other", "2020-01-02", BODY), encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "fragment")
    git(root, "update-ref", "refs/remotes/origin/tp/other", "tp/other")
    git(root, "checkout", "-q", "main")
    return root


def _check(root, capsys):
    code = branch_fragments.main(["check", "--repo-root", str(root)])
    return code, capsys.readouterr().out


def test_intact_anchor_prints_nothing(tmp_path, capsys):
    assert _check(_repo(tmp_path), capsys) == (0, "")


def test_gone_anchor_is_listed_once(tmp_path, capsys):
    root = _repo(tmp_path)
    path = root / ROADMAP
    path.write_text(path.read_text(encoding="utf-8").replace("- focus one\n", ""), encoding="utf-8")
    code, out = _check(root, capsys)
    assert code == 1
    assert len(out.splitlines()) == 1 and out.startswith(PREFIX)


def test_merged_ref_is_skipped(tmp_path, capsys):
    root = _repo(tmp_path)
    path = root / ROADMAP
    path.write_text(path.read_text(encoding="utf-8").replace("- focus one\n", ""), encoding="utf-8")
    git(root, "update-ref", "refs/remotes/origin/tp/old", git(root, "rev-parse", "main"))
    code, out = _check(root, capsys)
    assert code == 1 and len(out.splitlines()) == 1


def test_no_origin_ref_is_clean(tmp_path, capsys):
    assert _check(_repo(tmp_path, with_ref=False), capsys) == (0, "")
