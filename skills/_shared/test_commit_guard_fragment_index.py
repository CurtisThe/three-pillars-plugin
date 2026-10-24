"""commit_guard.run checks the STAGED blob of a fragment, not the disk copy."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import commit_guard  # noqa: E402

FRAG = "three-pillars-docs/changes/demo.md"
TEMPLATE = (
    "---\nslug: demo\nkind: design\ndate: 2026-10-23\n---\n\n"
    "## Roadmap\n\n### Recent completions\n\n"
    "+ - **`demo`** — {token}, x\n"
)
BAD = "Completion PR pending"
GOOD = "Done — {pr}"


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(root), check=True, capture_output=True)


def _repo(tmp_path: Path, monkeypatch) -> Path:
    for var in ("GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE"):
        monkeypatch.delenv(var, raising=False)
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "t")
    return tmp_path


def _stage_then_edit(root: Path, staged: str, on_disk: str) -> None:
    path = root / FRAG
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(TEMPLATE.format(token=staged), encoding="utf-8")
    _git(root, "add", FRAG)
    path.write_text(TEMPLATE.format(token=on_disk), encoding="utf-8")


def test_staged_bad_blob_blocks_even_when_disk_copy_fixed(tmp_path, monkeypatch):
    root = _repo(tmp_path, monkeypatch)
    _stage_then_edit(root, staged=BAD, on_disk=GOOD)
    assert commit_guard.run(root, "pre-commit") == 1


def test_staged_good_blob_passes_despite_bad_disk_copy(tmp_path, monkeypatch):
    root = _repo(tmp_path, monkeypatch)
    _stage_then_edit(root, staged=GOOD, on_disk=BAD)
    assert commit_guard.run(root, "pre-commit") == 0


def test_fragment_check_import_failure_blocks_with_internal_error(
        tmp_path, monkeypatch, capsys):
    root = _repo(tmp_path, monkeypatch)
    monkeypatch.setitem(sys.modules, "fragment_commit_check", None)
    assert commit_guard.run(root, "pre-commit") == 1
    assert "internal error in fragment_commit_check" in capsys.readouterr().err
