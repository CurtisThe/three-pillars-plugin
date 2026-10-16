"""Tests for task_eligibility.phase_rows — the CLI's own row derivation, importable.

design: cheap-tier-offload (Task 3.3; plan.md Deviations 6). `cheap_tier_cli.py
task-table` imports it, so the lever never re-derives `max_files`, `runner_ok` or
`exists`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import task_eligibility as te  # noqa: E402
import task_scope  # noqa: E402


def _task(tid: str, files: str, targets: str, *extra: str) -> str:
    return "\n".join([f"### Task {tid}: t{tid}", f"**File**: {files}",
                      f"**Targets**: {targets}", "**Red**: r", "**Green**: g", *extra]) + "\n"


PLAN = "# P\n\n## Phase 1: Things\n\n" + "\n".join([
    _task("1.1", "`pkg/a.py`", "`pkg/test_a.py::test_x`"),
    _task("1.2", "`pkg/a.py`, `pkg/b.py`", "`pkg/test_a.py::test_y`"),
    _task("1.3", "`pkg/z.py`", "`gone/test_z.py::test_z`"),
]) + "\n## Phase 2: Other\n\n" + _task("2.1", "`pkg/a.py`", "`pkg/test_a.py::test_q`")


def repo(tmp_path: Path, *, config: str | None = None) -> tuple[Path, Path]:
    """A tmp repo with a pytest runner, two source files and the fixture plan."""
    root = tmp_path / "repo"
    for rel in ("pkg/a.py", "pkg/b.py", "pkg/test_a.py"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("\n", encoding="utf-8")
    (root / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    plan = root / "plan.md"
    plan.write_text(PLAN, encoding="utf-8")
    if config is not None:
        (root / ".three-pillars").mkdir()
        (root / ".three-pillars" / "config.json").write_text(config, encoding="utf-8")
    return root, plan


def _cli(capsys, plan: Path, root: Path, *extra: str) -> list[dict]:
    assert te.main([str(plan), "--phase", "1", "--root", str(root), *extra]) == 0
    return json.loads(capsys.readouterr().out)


def test_phase_rows_equals_the_cli_output(tmp_path, capsys):
    root, plan = repo(tmp_path)
    rows = te.phase_rows(PLAN, 1, root)
    assert json.loads(json.dumps(rows, sort_keys=True)) == _cli(capsys, plan, root)
    assert [r["task_id"] for r in rows] == ["1.1", "1.2", "1.3"]


def test_phase_rows_derives_the_cli_arguments(tmp_path):
    root, _plan = repo(tmp_path, config='{"local_implement": {"max_files": 1}}')
    runner, _why = task_scope.resolve_runner(root, None)
    want = te.classify_phase(PLAN, 1, max_files=te.configured_max_files(root),
                             runner_ok=runner is not None,
                             exists=lambda p: (root / p).exists())
    assert te.phase_rows(PLAN, 1, root) == want
    by = {r["task_id"]: r for r in want}
    # max_files 1: too-many-files is recorded, but the row stays local.
    assert by["1.2"]["tier"] == "local" and "too-many-files" in by["1.2"]["reasons"]


def test_phase_rows_max_files_override(tmp_path, capsys):
    root, plan = repo(tmp_path, config='{"local_implement": {"max_files": 1}}')
    rows = te.phase_rows(PLAN, 1, root, max_files=3)
    assert {r["task_id"]: r["tier"] for r in rows}["1.2"] == "local"
    assert json.loads(json.dumps(rows)) == _cli(capsys, plan, root, "--max-files", "3")
