"""Tests for living_doc_guard.py -- the shipped guard against design branches editing shared living docs.

Real temp git repos; design: living-doc-fragments (Interfaces, guard).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import living_doc_guard as g

HERE = Path(__file__).resolve().parent
KI = "three-pillars-docs/known_issues.md"
ARCH = "three-pillars-docs/architecture.md"


def _git(root: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8", check=True)
    return r.stdout.strip()


def _commit(root: Path, rel: str, text: str, msg: str = "c") -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    _git(root, "add", rel)
    _git(root, "commit", "-q", "-m", msg)


def _repo(tmp_path: Path, branch: str = "tp/demo") -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    _commit(root, KI, "base\n")
    _commit(root, "three-pillars-docs/vision.md", "v\n")
    _git(root, "checkout", "-q", "-b", branch)
    return root


def test_branch_editing_known_issues_is_refused(tmp_path):
    root = _repo(tmp_path)
    _commit(root, KI, "edited\n")
    res = g.check(root, base_ref="main")
    assert res.verdict == "refused"
    assert res.paths == [KI]
    assert "three-pillars-docs/changes/demo.md" in res.fix
    assert "skills/_shared/living-doc-fragments.md" in res.fix
    cp = subprocess.run([sys.executable, str(HERE / "living_doc_guard.py"), "check", "--base", "main",
                         "--repo-root", str(root)], capture_output=True, text=True, encoding="utf-8")
    assert cp.returncode == 1


def test_fragment_only_branch_is_clean(tmp_path):
    root = _repo(tmp_path)
    _commit(root, "three-pillars-docs/changes/demo.md", "# demo\n")
    res = g.check(root, base_ref="main")
    assert res.verdict == "clean" and res.paths == []


def test_base_sync_merge_of_base_text_is_not_counted(tmp_path):
    root = _repo(tmp_path)
    _commit(root, "three-pillars-docs/changes/demo.md", "# demo\n")
    _git(root, "checkout", "-q", "main")
    _commit(root, ARCH, "base arch\n")
    _git(root, "checkout", "-q", "tp/demo")
    _git(root, "merge", "-q", "--no-ff", "-m", "sync", "main")
    assert g.check(root, base_ref="main").verdict == "clean"


def test_docs_compile_branch_is_exempt(tmp_path):
    root = _repo(tmp_path, "tp/docs-compile")
    _commit(root, KI, "compiled\n")
    assert g.check(root, base_ref="main").verdict == "exempt"


def test_legacy_slug_is_exempt(tmp_path):
    root = _repo(tmp_path)
    (root / ".three-pillars").mkdir()
    (root / ".three-pillars/living-doc-legacy.txt").write_text("# open\nother\ndemo\n", encoding="utf-8")
    _commit(root, KI, "edited\n")
    assert g.check(root, base_ref="main").verdict == "exempt"


def test_non_tp_branch_is_skipped(tmp_path):
    root = _repo(tmp_path, "feature/x")
    _commit(root, KI, "edited\n")
    assert g.check(root, base_ref="main").verdict == "skipped"
    assert g.check(root, base_ref="main", branch="tp/demo").verdict == "refused"


def test_low_part_and_archive_are_guarded_vision_is_not(tmp_path):
    assert g.is_shared_living_doc("three-pillars-docs/known_issues_low_2.md")
    assert g.is_shared_living_doc("three-pillars-docs/architecture_archive.md")
    assert not g.is_shared_living_doc("three-pillars-docs/vision.md")
    assert not g.is_shared_living_doc("three-pillars-docs/changes/demo.md")
    root = _repo(tmp_path)
    _commit(root, "three-pillars-docs/vision.md", "v2\n")
    _commit(root, "three-pillars-docs/known_issues_low_2.md", "low\n")
    assert g.check(root, base_ref="main").paths == ["three-pillars-docs/known_issues_low_2.md"]


def test_cli_exit_codes(tmp_path):
    root = _repo(tmp_path)
    _commit(root, "three-pillars-docs/changes/demo.md", "# d\n")
    cmd = [sys.executable, str(HERE / "living_doc_guard.py"), "check", "--repo-root", str(root)]
    ok = subprocess.run([*cmd, "--base", "main", "--json"], capture_output=True, text=True, encoding="utf-8")
    assert ok.returncode == 0 and json.loads(ok.stdout)["verdict"] == "clean"
    bad = subprocess.run([*cmd, "--base", "no-such-ref"], capture_output=True, text=True, encoding="utf-8")
    assert bad.returncode == 2
    _commit(root, KI, "edited\n")
    ref = subprocess.run([*cmd, "--base", "main", "--json"], capture_output=True, text=True, encoding="utf-8")
    assert ref.returncode == 1 and json.loads(ref.stdout)["verdict"] == "refused"
