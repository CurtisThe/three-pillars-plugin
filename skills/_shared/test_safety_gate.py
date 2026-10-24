"""test_safety_gate.py - the one gate-path list and its predicates (design light-run-ceremony-diet 1.1)."""
from __future__ import annotations

import fnmatch
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import safety_gate  # noqa: E402


@pytest.mark.parametrize("path", [
    "skills/_shared/delete_fence_hook.py",
    "skills/tp-merge-from-main/scripts/merge_gate.py",
    "skills/_shared/deterministic_gate.py",
    "skills/_shared/human_approval.py",
    "skills/_shared/create_fence_hook.py",
    "skills/_shared/create_fence_targets.py",
    "skills/_shared/create_fence_py.py",
    "skills/_shared/run_scratch.py",
    "skills/_shared/scratch_leftovers.py",
])
def test_gate_paths_touch(path):
    assert safety_gate.touches_gate([path]) is True


@pytest.mark.parametrize("paths", [
    ["README.md", "skills/_shared/run_retro.py"],
    ["skills/_shared/test_delete_fence_hook.py"],
    ["skills/_shared/slot_entry.py"],
    [],
])
def test_non_gate_paths(paths):
    assert safety_gate.touches_gate(paths) is False


def test_unreadable_diff_counts_as_gate():
    assert safety_gate.touches_gate(None) is True


def _design(tmp_path, text):
    if text is not None:
        (tmp_path / "design.md").write_text(text)
    return tmp_path


def test_declares_true(tmp_path):
    assert safety_gate.declares_safety_gate(
        _design(tmp_path, "---\nsafety-gate: true\n---\nbody\n")) is True


def test_declares_absent_false_missing(tmp_path):
    a = tmp_path / "a"; a.mkdir()
    b = tmp_path / "b"; b.mkdir()
    c = tmp_path / "c"; c.mkdir()
    assert safety_gate.declares_safety_gate(_design(a, "---\nweight: light\n---\n")) is False
    assert safety_gate.declares_safety_gate(_design(b, "---\nsafety-gate: false\n---\n")) is False
    assert safety_gate.declares_safety_gate(_design(c, None)) is False


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def test_changed_paths(tmp_path):
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "t@t")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "z.txt").write_text("z")
    _git(tmp_path, "add", "z.txt")
    _git(tmp_path, "commit", "-qm", "base")
    _git(tmp_path, "checkout", "-qb", "feat")
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "x.py").write_text("x")
    _git(tmp_path, "add", "a/x.py")
    _git(tmp_path, "commit", "-qm", "add")
    assert safety_gate.changed_paths(tmp_path, "main", "feat") == ["a/x.py"]
    assert safety_gate.changed_paths(tmp_path, "main", "nope-ref") is None


def test_no_stale_gate_glob():
    root = Path(__file__).resolve().parents[2]
    if not (root / "framework-check.sh").exists():
        pytest.skip("not the framework checkout")
    out = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard"],
        capture_output=True, text=True, check=True).stdout.split("\n")
    files = [f for f in out if f]
    stale = [g for g in safety_gate.GATE_PATHS
             if not any(fnmatch.fnmatch(f, g) for f in files)]
    assert stale == []
