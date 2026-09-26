"""test_audit_targets.py — the plan audit validates every task's **Targets** field.

design: local-implement-and-review (operator rulings on #165, C3)

Behaviour: a malformed field fails the audit; a missing one is reported but the audit
still passes and writes its pass artifact; a valid field passes. Fixtures keep design.md
and plan.md frontmatter symmetric (both bare), as `test_audit_plan_exit_contract.py` does.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

import audit_plan  # noqa: E402
from audit_targets import check_targets  # noqa: E402

AUDIT = SCRIPTS / "audit_plan.py"
ARTIFACT = ".plan-audit-pass.json"
DESIGN = ("# Design: x\n\n## Scope\n### In scope\n- a thing\n\n"
          "## Behaviors\n- **does** the thing\n\n## Entities\n- **Thing** — a thing\n")


def _plan(targets_line: str) -> str:
    return ("# Plan: x\n\n## Phase 1: do it (~50k)\n\n### Task 1.1: the task\n"
            "**File**: `pkg/a.py` (new)\n**Test**: prose\n" + targets_line
            + "**Red**: fails first\n**Green**: passes after\n**Done when**: it works\n")


def _audit(tmp_path: Path, targets_line: str) -> subprocess.CompletedProcess:
    design = tmp_path / "d"
    design.mkdir()
    (design / "design.md").write_text(DESIGN, encoding="utf-8")
    (design / "plan.md").write_text(_plan(targets_line), encoding="utf-8")
    (tmp_path / "pkg").mkdir()
    return subprocess.run([sys.executable, str(AUDIT), str(design), "--light"],
                          capture_output=True, text=True, cwd=str(tmp_path))


@pytest.mark.parametrize("line", [
    "**Targets**: `pkg/test_a.py::test_x` (new)\n",
    "**Targets**: `pkg/test_a.py` (new), `pkg/test_a.py::test_x` (new)\n",
    "**Targets**: none\n",
], ids=["node", "file-and-node", "none"])
def test_valid_targets_pass_and_write_the_artifact(tmp_path, line):
    r = _audit(tmp_path, line)
    assert r.returncode == 0, r.stdout
    assert (tmp_path / "d" / ARTIFACT).is_file()


@pytest.mark.parametrize("line", [
    "**Targets**: pkg/test_a.py::test_x\n",
    "**Targets**: `pkg/test_a.py::test_*` (new)\n",
    "**Targets**: `pkg/test_a.py::a` (new), `pkg/test_a.py::b`\n",
], ids=["unquoted", "glob", "partial-marker"])
def test_malformed_targets_fail_the_audit(tmp_path, line):
    r = _audit(tmp_path, line)
    assert r.returncode == 1, r.stdout
    assert not (tmp_path / "d" / ARTIFACT).exists()


def test_missing_targets_is_reported_but_passes(tmp_path):
    r = _audit(tmp_path, "")
    assert r.returncode == 0, r.stdout
    assert (tmp_path / "d" / ARTIFACT).is_file()
    assert "Task 1.1" in r.stdout  # the non-canonical task is named


def test_check_targets_classes(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "test_old.py").write_text("\n", encoding="utf-8")
    plan = ("## Phase 1: p (~1k)\n\n"
            "### Task 1.1: a\n**Targets**: `pkg/test_old.py::test_x`\n"
            "### Task 1.2: b\n**Targets**: `pkg/test_new.py` (new)\n"
            "### Task 1.3: c\n**Targets**: `pkg/test_new.py::test_y`\n"
            "### Task 1.4: d\n**Targets**: `pkg/test_ghost.py`\n"
            "### Task 1.5: e\n**Targets**: `pkg/test_old.py` extra\n"
            "### Task 1.6: f\n**Test**: prose only\n")
    issues, notes = check_targets(audit_plan.extract_tasks(plan), root=tmp_path)
    by_task = {(typ, ctx.split(":")[0]) for typ, ctx, _ in issues}
    assert by_task == {("WARN", "Task 1.4"), ("ERROR", "Task 1.5")}
    assert [ctx.split(":")[0] for _, ctx, _ in notes] == ["Task 1.6"]
