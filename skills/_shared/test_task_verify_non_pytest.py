"""test_task_verify_non_pytest.py — a recorded `test.runner: "other"` reports unverified.

consumer-repo-parity impl-audit F4 (design Non-goals / Behaviour; tp-test-setup step 6b):
a repo whose `/tp-test-setup` recorded a non-pytest runner (`test.runner: "other"`) gets
the status `unverified (non-pytest runner)` from Targets verification — never the generic
`runner-not-node-targetable` / `no oracle` result, and never a pytest run against it.

  * `task_scope_runner.resolve_runner` reads the recorded runner: `"other"` →
    `(None, "unverified (non-pytest runner)")`, ahead of discovery and the pytest-config
    probe (the operator's declaration wins); an explicit override still wins over it;
  * `task_verify.py check` (the CLI the `--local` dispatcher runs) carries that status:
    PASS-unverified on `opus` with the status in its reason, and a cheap rung's
    `no oracle` FAIL names it — as it does any `resolve_runner` refusal verbatim
    (PR #170 r4: `runner-needs-shell`).

Real tmp repos only (`attempt_fixture`); the ambient repository is never read.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import task_scope_runner
from attempt_fixture import IDENTITY, DD, commit, make_seat
from task_scope import _git_env as clean_git_env

SCRIPT = str(Path(__file__).resolve().parent / "task_verify.py")
STATUS = "unverified (non-pytest runner)"
PLAN = f"""# demo plan

## Phase 1: Demo

### Task 1.1: Change A
**File**: `skills/a.py`
**Test**: `skills/test_a.py::test_a`
**Targets**: `skills/test_a.py::test_a`
**Red**: test_a asserts that A equals two.
**Green**: set A to two.
"""


def _config(test: dict) -> str:
    return json.dumps({"schema_version": 1, "test": test}, indent=2) + "\n"


def _repo(root: Path, test: dict, **files: str) -> Path:
    (root / ".three-pillars").mkdir(parents=True)
    (root / ".three-pillars" / "config.json").write_text(_config(test), encoding="utf-8")
    for name, text in files.items():
        (root / name).write_text(text, encoding="utf-8")
    return root


def test_status_constant_is_the_design_token():
    assert task_scope_runner.NON_PYTEST_RUNNER == STATUS


def test_recorded_other_runner_reports_unverified(tmp_path):
    npm = _repo(tmp_path / "npm", {"command": "npm test", "runner": "other"},
                **{"package.json": '{"scripts": {"test": "jest"}}'})
    assert task_scope_runner.resolve_runner(npm, None) == (None, STATUS)
    # The declaration wins over a stray pytest config the repo also carries …
    mixed = _repo(tmp_path / "mixed", {"command": "make test", "runner": "other"},
                  **{"pytest.ini": "[pytest]\n"})
    assert task_scope_runner.resolve_runner(mixed, None) == (None, STATUS)
    # … and an explicit override still wins over the declaration.
    assert task_scope_runner.resolve_runner(mixed, "python3 -m pytest") == (
        "python3 -m pytest", "override")


def test_unrecorded_or_pytest_runner_is_unchanged(tmp_path):
    npm = _repo(tmp_path / "npm", {"command": "npm test"})
    assert task_scope_runner.resolve_runner(npm, None) == (None, "runner-not-node-targetable")
    py = _repo(tmp_path / "py", {"command": "python3 -m pytest", "runner": "pytest"})
    runner, why = task_scope_runner.resolve_runner(py, None)
    assert (runner, why) == ("python3 -m pytest", "discovered")


def _cli(cwd: Path, *args: str) -> tuple[int, dict]:
    proc = subprocess.run([sys.executable, SCRIPT, *args], cwd=str(cwd), capture_output=True,
                          text=True, env=clean_git_env(**IDENTITY), timeout=300)
    return proc.returncode, json.loads(proc.stdout)


SHELL_CMD = "python3 -m pytest -q && echo lint-ok"
REFUSED = pytest.mark.parametrize("test,status", [
    ({"command": "npm test", "runner": "other"}, STATUS),
    ({"command": SHELL_CMD, "runner": "pytest"}, f"runner-needs-shell: '&' in {SHELL_CMD!r}")])


def _attempt(tmp_path: Path, test: dict) -> tuple[Path, str]:
    _seat, wt = make_seat(tmp_path)
    commit(wt, {f"{DD}/plan.md": PLAN, ".three-pillars/config.json": _config(test)}, "plan")
    rc, att = _cli(wt, "open", "--task", "1.1", "--design-dir", DD)
    assert rc == 0, att
    commit(Path(att["attempt_dir"]), {"skills/a.py": "A = 2\n"})
    return wt, att["attempt_id"]


def _check(wt: Path, att: str, rung: str) -> tuple[int, dict]:
    return _cli(wt, "check", "--attempt", att, "--plan", f"{DD}/plan.md", "--phase", "1",
                "--rung", rung)


@REFUSED
def test_check_on_opus_passes_unverified_with_the_status(tmp_path, test, status):
    wt, att = _attempt(tmp_path, test)
    rc, res = _check(wt, att, "opus")
    assert (rc, res["verdict"], res["unverified"]) == (0, "PASS", True), res
    assert status in res["logged"] and status in res["reason"]
    assert res["commands"] == []  # no pytest run against a non-pytest repo


@REFUSED
def test_check_on_a_cheap_rung_names_the_status(tmp_path, test, status):
    wt, att = _attempt(tmp_path, test)
    rc, res = _check(wt, att, "local")
    assert (rc, res["verdict"]) == (1, "FAIL"), res
    assert res["reason"] == f"no oracle: {status}"
