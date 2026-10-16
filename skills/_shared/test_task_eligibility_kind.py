"""Tests for task_eligibility.py's `kind` and `start_rung` fields.

design: run-throughput (Task 4.2).

`row["kind"]` comes from the task's `**Kind**` field (absent -> None); `start_rung`
is `ladder_rungs.task_start(row)[0]`, using the row's already-final `tier`. The
CLI's `effective` key stays family-level (`local`/`sonnet`/`opus`) even though
`start_rung` is a rung.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import task_eligibility as te  # noqa: E402
from task_scope import _git_env as clean_git_env  # noqa: E402 — git_env is dev-only

RED = "Calling `f()` returns 2, not 1."


def _task(tid, title, *, files, targets, kind=None, red=RED, status=None):
    lines = [f"### Task {tid}: {title}", f"**File**: {files}",
             f"**Targets**: {targets}", "**Test**: prose only, never parsed.", f"**Red**: {red}",
             "**Green**: implement it."]
    if kind is not None:
        lines.append(f"**Kind**: {kind}")
    lines.append("**Done when**: node passes.")
    if status:
        lines.append(f"**Status**: {status}")
    return "\n".join(lines) + "\n"


def _plan(*tasks, phase=1):
    return f"# P\n\n## Phase {phase}: Things\n\n" + "\n".join(tasks) + "\n"


EXISTING = {"pkg", "pkg/a.py", "pkg/test_a.py"}


def _classify(plan, *, runner_ok=True, max_files=3):
    return te.classify_phase(plan, 1, max_files=max_files, runner_ok=runner_ok,
                             exists=EXISTING.__contains__)


def _by_id(rows):
    return {r["task_id"]: r for r in rows}


def test_kind_and_start_rung_fixtures():
    many = "`pkg/h1.py`, `pkg/h2.py`, `pkg/h3.py`, `pkg/h4.py`"
    plan = _plan(
        _task("1.1", "clerical many", files=many, targets="`pkg/test_a.py::test_x`",
              kind="clerical"),
        _task("1.2", "plain many", files=many, targets="`pkg/test_a.py::test_x`"),
        _task("1.3", "local", files="`pkg/a.py`", targets="`pkg/test_a.py::test_x`"),
        _task("1.4", "no-oracle clerical", files="`pkg/a.py`", targets="none", kind="clerical"),
        _task("1.5", "no-oracle plain", files="`pkg/a.py`", targets="none"),
    )
    rows = _by_id(_classify(plan))
    # Too many files stays local; a local row ignores kind for its start rung.
    # A recorded reason starts local at xhigh, except a clerical row (medium).
    for tid, rung in (("1.1", "local-medium"), ("1.2", "local-xhigh")):
        assert rows[tid]["tier"] == "local" and "too-many-files" in rows[tid]["reasons"]
        assert rows[tid]["start_rung"] == rung
    assert rows["1.1"]["kind"] == "clerical" and rows["1.2"]["kind"] is None
    assert (rows["1.3"]["tier"], rows["1.3"]["kind"]) == ("local", None)
    assert rows["1.3"]["start_rung"] == "local-medium"
    # No oracle starts on Strata (an Opus diff review accepts it), never opus: the recorded
    # reason starts it at local-xhigh, except a clerical row (local-medium).
    assert (rows["1.4"]["tier"], rows["1.4"]["kind"]) == ("local", "clerical")
    assert rows["1.4"]["start_rung"] == "local-medium"
    assert (rows["1.5"]["tier"], rows["1.5"]["kind"]) == ("local", None)
    assert rows["1.5"]["start_rung"] == "local-xhigh"
    assert rows["1.5"]["reasons"][0] == "test-not-runnable:targets-none"


def test_excluded_row_still_gets_kind_and_start_rung():
    plan = _plan(
        _task("1.1", "blocked", files="`pkg/a.py`", targets="`pkg/test_a.py::test_x`",
              kind="clerical", status="Blocked (hook failed)"),
    )
    rows = _by_id(_classify(plan))
    assert rows["1.1"]["excluded"] is True
    assert rows["1.1"]["kind"] == "clerical"
    assert rows["1.1"]["start_rung"] == "opus-medium"


# --- CLI: effective stays family-level while start_rung is a rung -------------------

SCRIPT = Path(__file__).resolve().parent / "task_eligibility.py"


def _cli_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    for rel in ("pkg/a.py", "pkg/test_a.py"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("\n", encoding="utf-8")
    (root / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    plan = root / "three-pillars-docs" / "tp-designs" / "d" / "plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text(_plan(
        _task("1.1", "local", files="`pkg/a.py`", targets="`pkg/test_a.py::test_x`"),
    ), encoding="utf-8")
    return root


def _run_cli(root: Path, *extra: str):
    plan = root / "three-pillars-docs" / "tp-designs" / "d" / "plan.md"
    return subprocess.run([sys.executable, str(SCRIPT), str(plan), "--phase", "1",
                           "--root", str(root), *extra],
                          capture_output=True, text=True, cwd=str(root), env=clean_git_env())


def test_cli_route_effective_family_start_rung_is_a_rung(tmp_path):
    root = _cli_repo(tmp_path)
    routed = json.dumps({"schema": "tp-local-route/v1", "state": "routed", "reason": "ok",
                         "base_url": "http://127.0.0.1:3457",
                         "checked_at": "2026-09-27T00:00:00Z"})
    proc = _run_cli(root, "--route", routed)
    assert proc.returncode == 0, proc.stderr
    rows = _by_id(json.loads(proc.stdout))
    assert rows["1.1"]["tier"] == "local"
    assert rows["1.1"]["effective"] == "local"  # still a family, not rung-ified
    assert rows["1.1"]["start_rung"] == "local-medium"
