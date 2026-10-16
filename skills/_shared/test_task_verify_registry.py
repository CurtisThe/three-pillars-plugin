"""test_task_verify_registry.py — `_step_scope` absorbs a mechanical registry edit.

design: run-throughput (Task 5.2). Real tmp git repos only.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import task_verify

REG = "skills/_shared/hot_patch.py"
ROW = {"files": ["skills/other.py"]}


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@t",
                           *args], capture_output=True, text=True, check=True).stdout.strip()


def _repo(tmp_path: Path, registry=(REG,)) -> tuple[Path, str]:
    (tmp_path / ".three-pillars").mkdir()
    (tmp_path / ".three-pillars/config.json").write_text(json.dumps(
        {"schema_version": 1, "local_implement": {"registry_files": list(registry)}}))
    (tmp_path / "skills/_shared").mkdir(parents=True)
    (tmp_path / REG).write_text("A = 1\n")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "base")
    return tmp_path, _git(tmp_path, "rev-parse", "HEAD")


def _edit(adir: Path, add: int = 0, delete: bool = False) -> None:
    text = "" if delete else "A = 1\n"
    (adir / REG).write_text(text + "".join(f"B{i} = {i}\n" for i in range(add)))
    _git(adir, "commit", "-qam", "edit")


def _scope(adir, base, rung="sonnet"):
    return task_verify._step_scope([REG], ROW, "docs/d", rung, str(adir), base)


def test_mechanical_registry_edit_logged_not_failed(tmp_path):
    adir, base = _repo(tmp_path)
    _edit(adir, add=3)
    assert _scope(adir, base) == [f"registry-edit-logged: {REG}"]


def test_four_added_lines_still_fail(tmp_path):
    adir, base = _repo(tmp_path)
    _edit(adir, add=4)
    with pytest.raises(task_verify._Fail, match=f"unlisted file: {REG}"):
        _scope(adir, base)


def test_deletion_still_fails(tmp_path):
    adir, base = _repo(tmp_path)
    _edit(adir, add=1, delete=True)
    with pytest.raises(task_verify._Fail, match="unlisted file"):
        _scope(adir, base)


def test_unregistered_path_still_fails(tmp_path):
    adir, base = _repo(tmp_path, registry=())
    _edit(adir, add=1)
    with pytest.raises(task_verify._Fail, match="unlisted file"):
        _scope(adir, base)


def test_missing_config_means_no_registry(tmp_path):
    adir, _base = _repo(tmp_path)
    (adir / ".three-pillars/config.json").unlink()
    assert task_verify._registry_files(str(adir)) == []
