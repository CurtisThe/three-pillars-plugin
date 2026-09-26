"""test_task_scope_resolve.py — dirty-tree, runner and argv resolution.

design: local-implement-and-review

`task_scope`'s filesystem/git-facing helpers. Git-touching cases build a real tmp repo
with a scrubbed env and never read the ambient repository (M23).
"""
from __future__ import annotations

import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from task_scope import _git_env as clean_git_env  # shipped scrub; git_env is dev-only

import task_scope

_IDENTITY = {
    "GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture@test",
    "GIT_COMMITTER_NAME": "fixture", "GIT_COMMITTER_EMAIL": "fixture@test",
}
_DD = "three-pillars-docs/tp-designs/demo"


def _git(*args: str, cwd: Path) -> str:
    env = clean_git_env(**_IDENTITY)
    out = subprocess.run(["git", *args], cwd=str(cwd), env=env,
                         capture_output=True, text=True, check=True)
    return out.stdout


def _write(root: Path, rel: str, text: str = "x\n") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# --- Task 1.4: the dirty-tree probe --------------------------

def test_dirty_outside_ignores_design_dir_and_worktrees(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git("init", "-q", "-b", "main", cwd=repo)
    _write(repo, f"{_DD}/lock.json", "{}\n")
    _write(repo, "skills/keep.py")
    _git("add", "-A", cwd=repo)
    _git("commit", "-q", "-m", "init", cwd=repo)

    _write(repo, f"{_DD}/lock.json", '{"owner": null}\n')  # dispatcher's own lock
    _write(repo, f"{_DD}/decisions.md", "appended\n")
    _write(repo, ".claude/worktrees/tp-attempt-1/skills/x.py")  # nested attempt dir
    assert task_scope.dirty_outside(repo, _DD) == []
    assert task_scope.dirty_outside(repo, _DD + "/") == []

    _write(repo, "skills/a.py")
    assert task_scope.dirty_outside(repo, _DD) == ["skills/a.py"]
    _write(repo, "skills/keep.py", "changed\n")
    assert task_scope.dirty_outside(repo, _DD) == ["skills/a.py", "skills/keep.py"]


# --- Task 1.5: runner resolution with fall-through ---------------------------------

_PYTEST = "python3 -m pytest"  # never bare `python` (impl-audit-1 #2)


def _repo_with(tmp_path: Path, **files: str) -> Path:
    root = tmp_path / "r"
    root.mkdir(parents=True)
    for name, text in files.items():
        _write(root, name.replace("__", "."), text)
    return root


def test_resolve_runner_order(tmp_path, monkeypatch):
    real_which = shutil.which

    def _python_on_path(present: bool) -> None:
        monkeypatch.setattr(shutil, "which", lambda name, *a, **k: (
            ("/usr/bin/python" if present else None) if name == "python"
            else real_which(name, *a, **k)))

    ini = _repo_with(tmp_path / "ini", pytest__ini="[pytest]\n")
    assert task_scope.resolve_runner(ini, "python3 -m pytest -x") == (
        "python3 -m pytest -x", "override")
    assert task_scope.resolve_runner(ini, None) == (_PYTEST, "pytest-config")
    assert task_scope.resolve_runner(ini, "") == (_PYTEST, "pytest-config")
    pyproject = _repo_with(tmp_path / "pp", pyproject__toml="[tool.pytest.ini_options]\n")
    _python_on_path(False)
    assert task_scope.resolve_runner(pyproject, None) == (_PYTEST, "discovered")
    # impl-audit-2 #10: where `python` exists, the discovered command is kept as declared.
    _python_on_path(True)
    assert task_scope.resolve_runner(pyproject, None) == ("python -m pytest", "discovered")
    tox = _repo_with(tmp_path / "tox", tox__ini="[tox]\n\n[pytest]\naddopts = -q\n")
    assert task_scope.resolve_runner(tox, None) == (_PYTEST, "pytest-config")
    cfg = _repo_with(tmp_path / "cfg", setup__cfg="[metadata]\n[tool:pytest]\n")
    assert task_scope.resolve_runner(cfg, None) == (_PYTEST, "pytest-config")
    tox_only = _repo_with(tmp_path / "tox2", tox__ini="[tox]\nenvlist = py3\n")
    assert task_scope.resolve_runner(tox_only, None) == (None, "no-runner")
    empty = _repo_with(tmp_path / "none")
    assert task_scope.resolve_runner(empty, None) == (None, "no-runner")


def test_resolve_runner_make_test_falls_through(tmp_path):
    make = "test:\n\tpytest\n"
    both = _repo_with(tmp_path / "both", Makefile=make, pytest__ini="[pytest]\n")
    assert task_scope.resolve_runner(both, None) == (_PYTEST, "pytest-config")
    alone = _repo_with(tmp_path / "alone", Makefile=make)
    assert task_scope.resolve_runner(alone, None) == (None, "runner-not-node-targetable")
    npm = _repo_with(tmp_path / "npm", package__json='{"scripts": {"test": "jest"}}')
    assert task_scope.resolve_runner(npm, None) == (None, "runner-not-node-targetable")


# --- Task 1.6: the runner argv -----------------------------------------------------

def test_runner_argv_is_runner_plus_targets():
    """No flag is inferred from the repo or the runner (no ``-n0``, no probe): the
    verdict is per node from the junit report (PR #165 ruling, A29)."""
    runner = f"{shlex.quote(sys.executable)} -m pytest -p no:xdist -x"
    assert task_scope.runner_argv(runner, ["t.py::a", "t.py::test_b[x y]"]) == [
        sys.executable, "-m", "pytest", "-p", "no:xdist", "-x", "t.py::a", "t.py::test_b[x y]"]
    assert task_scope.runner_argv("make test", ["t.py"]) == ["make", "test", "t.py"]
    assert not hasattr(task_scope, "xdist_loaded")
