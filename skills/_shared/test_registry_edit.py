"""test_registry_edit.py — mechanical registry-edit detection (design: run-throughput).

Task 5.1: `registry_edit.is_mechanical_registry_edit(adir, base, path, registry_files)`
is true only for a listed path whose `base..HEAD` numstat diff is purely additive
(>=1, <=3 lines added, 0 deleted). Git-touching cases build a real tmp repo with a
scrubbed env and never read the ambient repository (M23).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from task_scope import _git_env as clean_git_env  # shipped scrub; git_env is dev-only

import registry_edit

_IDENTITY = {
    "GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture@test",
    "GIT_COMMITTER_NAME": "fixture", "GIT_COMMITTER_EMAIL": "fixture@test",
}


def _git(*args: str, cwd: Path) -> str:
    env = clean_git_env(**_IDENTITY)
    return subprocess.run(["git", *args], cwd=str(cwd), env=env,
                          capture_output=True, text=True, check=True).stdout


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _repo_base_only(tmp_path: Path) -> tuple[Path, str]:
    """Tmp repo with just the base commit (no second commit → empty diff)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git("init", "-q", "-b", "main", cwd=repo)
    _write(repo, "registry.md", "line 1\nline 2\n")
    _git("add", "-A", cwd=repo)
    _git("commit", "-q", "-m", "base", cwd=repo)
    return repo, _git("rev-parse", "HEAD", cwd=repo).strip()


def _repo_with(tmp_path: Path, second_content: str) -> tuple[Path, str]:
    """Tmp repo: base commit with `registry.md` (2 lines), then a second commit
    rewriting it to `second_content`. Returns (repo, base-sha)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git("init", "-q", "-b", "main", cwd=repo)
    _write(repo, "registry.md", "line 1\nline 2\n")
    _git("add", "-A", cwd=repo)
    _git("commit", "-q", "-m", "base", cwd=repo)
    base = _git("rev-parse", "HEAD", cwd=repo).strip()
    _write(repo, "registry.md", second_content)
    _git("add", "-A", cwd=repo)
    _git("commit", "-q", "-m", "second", cwd=repo)
    return repo, base


def test_three_line_addition_on_listed_path_is_mechanical(tmp_path):
    repo, base = _repo_with(tmp_path, "line 1\nline 2\na\nb\nc\n")
    assert registry_edit.is_mechanical_registry_edit(
        repo, base, "registry.md", ["registry.md"]) is True


def test_one_line_addition_on_listed_path_is_mechanical(tmp_path):
    repo, base = _repo_with(tmp_path, "line 1\nline 2\na\n")
    assert registry_edit.is_mechanical_registry_edit(
        repo, base, "registry.md", ["registry.md"]) is True


def test_four_line_addition_is_not_mechanical(tmp_path):
    repo, base = _repo_with(tmp_path, "line 1\nline 2\na\nb\nc\nd\n")
    assert registry_edit.is_mechanical_registry_edit(
        repo, base, "registry.md", ["registry.md"]) is False


def test_deletion_is_not_mechanical(tmp_path):
    repo, base = _repo_with(tmp_path, "line 1\n")
    assert registry_edit.is_mechanical_registry_edit(
        repo, base, "registry.md", ["registry.md"]) is False


def test_unlisted_path_is_not_mechanical(tmp_path):
    repo, base = _repo_with(tmp_path, "line 1\nline 2\na\nb\nc\n")
    assert registry_edit.is_mechanical_registry_edit(
        repo, base, "registry.md", ["other.md"]) is False


def test_unchanged_listed_path_is_not_mechanical(tmp_path):
    repo, base = _repo_base_only(tmp_path)
    assert registry_edit.is_mechanical_registry_edit(
        repo, base, "registry.md", ["registry.md"]) is False


def test_binary_file_is_not_mechanical(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git("init", "-q", "-b", "main", cwd=repo)
    _write(repo, "blob.bin", "first\n")
    _git("add", "-A", cwd=repo)
    _git("commit", "-q", "-m", "base", cwd=repo)
    base = _git("rev-parse", "HEAD", cwd=repo).strip()
    (repo / "blob.bin").write_bytes(b"\x00\x01\x02\xff")
    _git("add", "-A", cwd=repo)
    _git("commit", "-q", "-m", "second", cwd=repo)
    assert registry_edit.is_mechanical_registry_edit(
        repo, base, "blob.bin", ["blob.bin"]) is False
