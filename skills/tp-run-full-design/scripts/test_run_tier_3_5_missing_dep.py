"""test_run_tier_3_5_missing_dep.py — a missing Python dependency is exit 2, never 1.

design: run-throughput (seat ruling G3, PR #178 live check #2 Part B). Exit 1 is the
case-(c) retry code, so an import-time `ModuleNotFoundError` (no `jsonschema`) would make
the orchestrator retry an environment failure. The wrapper runs in a subprocess whose
`sys.modules["jsonschema"] = None` makes the import fail exactly as on a box without it.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "run_tier_3_5.py"

_RUN = ("import runpy, sys; sys.modules[{mod!r}] = None; "
        "runpy.run_path({script!r}, run_name='__main__')")


def _run(mod: str, stdin: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-c", _RUN.format(mod=mod, script=str(SCRIPT))],
                          input=stdin, capture_output=True, text=True, timeout=60)


def test_missing_jsonschema_is_exit_2_env_error_with_install_hint():
    proc = _run("jsonschema", '{"worker_response": "", "agent_meta": {"worktreePath": null}}')
    assert proc.returncode == 2, proc.stderr
    assert "Traceback" not in proc.stderr
    env = json.loads(proc.stdout)
    assert env["status"] == "escalate" and env["case"] is None
    assert env["event_token"] == "missing-dependency"
    assert "jsonschema" in env["detail"] and "pip install jsonschema" in env["detail"]


def test_missing_dependency_wins_before_stdin_is_read():
    """Even a malformed stdin reports the missing module, not stdin-invalid (exit 2 both)."""
    proc = _run("jsonschema", "not json")
    assert proc.returncode == 2
    assert json.loads(proc.stdout)["event_token"] == "missing-dependency"


def test_any_missing_helper_module_is_exit_2():
    proc = _run("rerun_budget", "{}")
    assert proc.returncode == 2, proc.stderr
    env = json.loads(proc.stdout)
    assert env["event_token"] == "missing-dependency" and "rerun_budget" in env["detail"]
