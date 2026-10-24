"""Hermetic tests for jdi_plan.py splitting a Scope that is over the file cap.

A 6-file Scope (3 code files, each with its test_<stem>.py) under max_files 3
renders one task per code+test group; each task has its own Targets and Entry
point, **Growth** sits on Task 1.1 only, and the plan passes jdi-mechanical.
A Scope at or under the cap still renders one task.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

_SHARED = Path(__file__).resolve().parent
sys.path.insert(0, str(_SHARED))
import jdi_plan  # noqa: E402

_ROOT = _SHARED.parent.parent
_AUDIT = _ROOT / "skills" / "tp-plan-audit" / "scripts"

TAIL = ("## Behaviors\n\nIt works.\n\n## Done when\n\nThe targets pass.\n")


def _design_text(paths, est=30):
    scope = "".join(f"- `{p}`\n" for p in paths)
    return ("---\nweight-class: just-do-it\nslug: fixture\n"
            f"estimated-lines: {est}\n---\n\n# fixture — design\n\n"
            "## Scope\n\n" + scope + "\n" + TAIL)


SIX = ["skills/a/one.py", "skills/a/test_one.py",
       "skills/a/two.py", "skills/a/test_two.py",
       "skills/a/three.py", "skills/a/test_three.py"]


def _design(tmp_path, paths):
    d = tmp_path / "design"
    d.mkdir(exist_ok=True)
    (d / "design.md").write_text(_design_text(paths), encoding="utf-8")
    return d


@pytest.fixture
def repo(tmp_path, monkeypatch):
    for var in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
                "GIT_PREFIX"):
        monkeypatch.delenv(var, raising=False)
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "init", "-q"],
                   cwd=str(r), check=True, capture_output=True)
    return r


def _tasks(text):
    parts = re.split(r"^### Task ", text, flags=re.M)[1:]
    return parts


def _field(task, name):
    m = re.search(rf"^\*\*{re.escape(name)}\*\*:\s*(.*)$", task, re.M)
    return m.group(1) if m else None


def test_six_file_scope_splits_into_tasks_of_at_most_three_paths(tmp_path, repo):
    d = _design(tmp_path, SIX)
    tasks = _tasks(jdi_plan.render(str(d), str(repo)))
    assert len(tasks) >= 2, "a 6-file scope over max_files 3 must split"
    seen = []
    for i, t in enumerate(tasks, 1):
        assert t.startswith(f"1.{i}:")
        paths = re.findall(r"`([^`]+)`", _field(t, "File"))
        assert 1 <= len(paths) <= 3
        seen += paths
        for p in paths:
            stem = p.rsplit("/", 1)[1]
            if not stem.startswith("test_"):
                assert f"skills/a/test_{stem}" in paths
        targets = re.findall(r"`([^`]+)`", _field(t, "Targets"))
        assert targets == [p for p in paths if p.rsplit("/", 1)[1].startswith("test_")]
        assert _field(t, "Entry point") != "none"
    assert sorted(seen) == sorted(SIX)


def test_growth_only_on_first_task(tmp_path, repo):
    d = _design(tmp_path, SIX)
    tasks = _tasks(jdi_plan.render(str(d), str(repo)))
    assert _field(tasks[0], "Growth") == "+30"
    for t in tasks[1:]:
        assert _field(t, "Growth") is None


def test_split_plan_passes_jdi_mechanical(tmp_path, repo):
    d = _design(tmp_path, SIX)
    assert jdi_plan.write(str(d), str(repo))[0] == 0
    w = subprocess.run([sys.executable, str(_AUDIT / "audit_artifact.py"), "--write",
                        str(d), "--mode", "jdi-mechanical"],
                       capture_output=True, text=True, cwd=str(repo))
    assert w.returncode == 0, w.stdout + w.stderr


def test_scope_at_cap_renders_one_task(tmp_path, repo):
    d = _design(tmp_path, SIX[:2] + ["skills/a/extra.py"])
    assert len(_tasks(jdi_plan.render(str(d), str(repo)))) == 1


def test_code_without_test_gets_none_fields(tmp_path, repo):
    paths = SIX + ["skills/a/lone.py"]
    d = _design(tmp_path, paths)
    tasks = _tasks(jdi_plan.render(str(d), str(repo)))
    lone = [t for t in tasks if "skills/a/lone.py" in _field(t, "File")]
    assert len(lone) == 1
    assert _field(lone[0], "Targets") == "none"
    assert _field(lone[0], "Entry point") == "none"
