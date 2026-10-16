"""Tests for child_spawn_ops.py — the prompt copy and smoke file live under `.tp-scratch/`.

design: launch-role-precedence (Task 3.5). `PROMPT_SUBDIR` is the scratch base's child-spawn dir
(`scratch_root.CHILD_SPAWN_DIR`, no `.claude` component), `_copy_prompt` lands the host's prompt at
`<cwd>/.tp-scratch/child-spawn/<child8>.prompt.md`, and it is the first writer into that dir, so
it calls `scratch_root.ensure_excluded(cwd)` before the mkdir: a consumer repo without the
`.gitignore` line stays clean for `task_verify`'s dirty-tree check. Nothing here starts a `claude`.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import child_spawn  # noqa: E402
import child_spawn_ops  # noqa: E402
import scratch_root  # noqa: E402
from attempt_fixture import commit, git  # noqa: E402

CHILD8 = "ab12cd34"
BODY = "Run `git status --porcelain` and report the output.\n"


def _repo(tmp_path: Path) -> Path:
    """A fresh git repo with one commit and no `.gitignore` line for the scratch base."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    commit(repo, {"README.md": "demo\n"}, "base")
    return repo


def _prompt(tmp_path: Path) -> str:
    src = tmp_path / "site.prompt.md"
    src.write_text(BODY, encoding="utf-8")
    return str(src)


def test_prompt_subdir_is_the_scratch_child_spawn_dir() -> None:
    assert child_spawn_ops.PROMPT_SUBDIR == scratch_root.CHILD_SPAWN_DIR
    assert child_spawn_ops.PROMPT_SUBDIR == ".tp-scratch/child-spawn"
    assert ".claude" not in Path(child_spawn_ops.PROMPT_SUBDIR).parts
    assert child_spawn.PROMPT_SUBDIR == child_spawn_ops.PROMPT_SUBDIR  # the smoke path's base


def test_copy_prompt_lands_under_the_scratch_dir(tmp_path) -> None:
    repo = _repo(tmp_path)
    dest = child_spawn_ops._copy_prompt(repo, CHILD8, _prompt(tmp_path))
    assert dest == repo / ".tp-scratch" / "child-spawn" / f"{CHILD8}.prompt.md"
    assert dest.read_text(encoding="utf-8") == BODY


def test_copy_prompt_excludes_the_scratch_base_first(monkeypatch, tmp_path) -> None:
    """`ensure_excluded(cwd)` runs once, before the scratch dir exists (before the mkdir)."""
    repo = _repo(tmp_path)
    seen: list = []

    def spy(root):
        seen.append((Path(str(root)), (repo / ".tp-scratch").exists()))
        return True

    monkeypatch.setattr(scratch_root, "ensure_excluded", spy)
    child_spawn_ops._copy_prompt(repo, CHILD8, _prompt(tmp_path))
    assert seen == [(repo, False)]


def test_repo_without_the_ignore_line_stays_clean_after_the_copy(tmp_path) -> None:
    repo = _repo(tmp_path)
    assert not (repo / ".gitignore").exists()
    dest = child_spawn_ops._copy_prompt(repo, CHILD8, _prompt(tmp_path))
    assert dest.is_file()
    status = subprocess.run(["git", "status", "--porcelain"], cwd=str(repo),
                            capture_output=True, text=True, check=True)
    assert status.stdout == "", status.stdout
