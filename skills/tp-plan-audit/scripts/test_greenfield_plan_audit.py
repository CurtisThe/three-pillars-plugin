"""Behavior 2 acceptance: a canonical all-``(new)`` GREENFIELD plan passes.

Seed H4 was "``/tp-plan-audit`` can never pass a greenfield plan, so
``/tp-phase-implement`` refuses every greenfield implementation." This test is
the post-H4 acceptance: a fresh project whose modules and a dotfile
(``.python-version``) are all declared ``(new)`` must audit to exit 0 with a
current pass artifact carrying ``warn_count: 0`` (no false WARNs / NOTEs for the
greenfield files), which is what lets ``/tp-phase-implement`` proceed.

The design dir is its own "repo": the ``tmp_path`` is passed as both the design
dir and the subprocess ``cwd``, so ``repo_root`` falls back to ``cwd`` (no git
repo above it) and none of the ``(new)`` files exist there — exactly the
greenfield situation.
"""

import json
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
AUDIT = SCRIPTS / "audit_plan.py"
ARTIFACT_SCRIPT = SCRIPTS / "audit_artifact.py"
ARTIFACT = ".plan-audit-pass.json"

DESIGN = """# Design: greenfield

## Scope
### In scope
- a fresh package with a runtime pin

## Behaviors
- **exposes** a core value

## Entities
- **Module** — the greenfield package
"""

DETAILED = """# Detailed Design: greenfield

## Module Structure
- `src/pkg/__init__.py` (new)
- `.python-version`

## Interfaces

## Implementation Order
1. **Build** — write the tests, then implement the module.
"""

PLAN = """# Plan: greenfield

## Phase 1: Build (~50k)

### Task 1.1: add the module
**File**: `src/pkg/__init__.py` (new)
**Test**: `tests/test_core.py` test_core
**Targets**: `tests/test_core.py` (new)
**Red**: assert the module exposes the core value.
**Green**: implement the module.
**Done when**: the tests pass.

### Task 1.2: pin the runtime
**File**: `.python-version` (new)
**Test**: `tests/test_core.py` test_runtime
**Targets**: `tests/test_core.py` (new)
**Red**: assert the runtime pin is present.
**Green**: add the .python-version pin.
**Done when**: the pin is in place.
"""


def _write(design_dir, name, body):
    (design_dir / name).write_text(body, encoding="utf-8")


def _run_audit(design_dir):
    # cwd == design_dir so repo_root falls back to it (no git repo above a
    # fresh tmp dir) and the (new) files do not exist there.
    return subprocess.run(
        [sys.executable, str(AUDIT), str(design_dir)],
        capture_output=True, text=True, cwd=str(design_dir),
    )


def _run_check(design_dir):
    return subprocess.run(
        [sys.executable, str(ARTIFACT_SCRIPT), "--check", str(design_dir)],
        capture_output=True, text=True,
    )


def test_greenfield_plan_passes_with_zero_warns(tmp_path):
    for name, body in (("design.md", DESIGN),
                       ("detailed-design.md", DETAILED),
                       ("plan.md", PLAN)):
        _write(tmp_path, name, body)

    r = _run_audit(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr

    # Behavior 2: no MISSING module, and no NOTE naming .python-version
    # (the greenfield dotfile is covered by its declared (new) File item, so
    # neither the file-existence check nor module coverage flags it).
    assert "MISSING" not in r.stdout, r.stdout
    for line in r.stdout.splitlines():
        if "NOTE" in line:
            assert ".python-version" not in line, r.stdout

    # The pass artifact is current and carries a zero WARN count.
    record = json.loads((tmp_path / ARTIFACT).read_text(encoding="utf-8"))
    assert record["verdict"] == "pass"
    assert record["warn_count"] == 0
    assert record["warnings"] == []

    # The gate passes: --check exits 0 and reports the zero WARN count.
    c = _run_check(tmp_path)
    assert c.returncode == 0, c.stdout + c.stderr
    assert "plan-audit: current pass (0 WARN(s))" in c.stdout
