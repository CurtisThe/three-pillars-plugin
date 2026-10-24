"""audit_plan.py wires task sizing in as advisory WARNs (exit stays 0)."""

import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
AUDIT = SCRIPTS / "audit_plan.py"

PLAN = """# Plan: x

## Phase 1: do it (~50k)

### Task 1.1: the task
**File**: `audit_plan.py`
**Test**: a test
**Red**: {red}
**Green**: passes after
**Done when**: it works
"""


def _run(tmp_path, red):
    (tmp_path / "design.md").write_text(
        "# Design: x\n\n## Scope\n### In scope\n- a thing\n\n"
        "## Behaviors\n- **does** the thing\n\n"
        "## Entities\n- **Thing** — a thing\n"
    )
    (tmp_path / "plan.md").write_text(PLAN.format(red=red))
    return subprocess.run(
        [sys.executable, str(AUDIT), str(tmp_path), "--light"],
        capture_output=True, text=True, cwd=tmp_path,
    )


def _clauses(n):
    return "; ".join(f"clause {i} asserts a thing" for i in range(1, n + 1))


def test_seven_clause_red_warns_and_exits_0(tmp_path):
    r = _run(tmp_path, _clauses(7))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "RESULT: PASS (1 WARN)" in r.stdout, r.stdout
    assert "sizing:" in r.stdout, r.stdout


def test_six_clause_red_is_clean(tmp_path):
    r = _run(tmp_path, _clauses(6))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "RESULT: ALL CHECKS PASSED" in r.stdout, r.stdout
