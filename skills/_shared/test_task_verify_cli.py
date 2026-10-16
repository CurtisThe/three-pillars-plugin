"""test_task_verify_cli.py — the ``task_verify.py`` CLI (open/check/land/discard/sweep).

design: local-implement-and-review (Behavior 5)

Every subcommand prints JSON; ``check`` exits 0 PASS / 1 FAIL / 2 env-error and
``land`` exits 2 on an env-error, each exit-2 JSON carrying ``recover``. Each attempt
commits the red/green pair (``commit_pair``). The script runs as a subprocess against
real tmp repos only (M23).
"""
from __future__ import annotations

import json
import shlex
import subprocess
import sys
from pathlib import Path

from attempt_fixture import IDENTITY, DD, commit, commit_pair, make_seat, write
from task_scope import _git_env as clean_git_env  # shipped scrub; git_env is dev-only

SCRIPT = str(Path(__file__).resolve().parent / "task_verify.py")
PLAN = f"""# demo plan

## Phase 1: Demo

### Task 1.1: Change A
**File**: `skills/a.py`
**Test**: `skills/test_a.py::test_a`
**Targets**: `skills/test_a.py::test_a`
**Red**: test_a asserts that A equals two.
**Green**: set A to two.

### Task 1.2: Change A again
**File**: `skills/a.py`
**Test**: `skills/test_a.py::test_a`
**Targets**: `skills/test_a.py::test_a`
**Red**: test_a asserts that A equals three.
**Green**: set A to three.
"""
GREEN = "import a\n\n\ndef test_a():\n    assert a.A == 2\n"


def cli(cwd: Path, *args: str) -> tuple[int, dict]:
    proc = subprocess.run([sys.executable, SCRIPT, *args], cwd=str(cwd), capture_output=True,
                          text=True, env=clean_git_env(**IDENTITY), timeout=300)
    return proc.returncode, json.loads(proc.stdout)


def _dispatcher(tmp_path: Path) -> Path:
    _seat, wt = make_seat(tmp_path)
    commit(wt, {f"{DD}/plan.md": PLAN}, "plan")
    return wt


def _check(wt: Path, att: str, rung: str = "local") -> tuple[int, dict]:
    return cli(wt, "check", "--attempt", att, "--plan", f"{DD}/plan.md", "--phase", "1",
               "--rung", rung, "--test-cmd", f"{shlex.quote(sys.executable)} -m pytest -q")


def test_cli_round_trip(tmp_path):
    wt = _dispatcher(tmp_path)
    rc, att = cli(wt, "open", "--task", "1.1", "--design-dir", DD)
    assert rc == 0 and att["status"] == "open" and att["attempt_id"].startswith("demo/1.1-")
    _red, tip = commit_pair(Path(att["attempt_dir"]), {"skills/test_a.py": GREEN},
                            {"skills/a.py": "A = 2\n"})
    rc, res = _check(wt, att["attempt_id"])
    assert (rc, res["verdict"], res["unverified"]) == (0, "PASS", False), res["reason"]
    assert res["red_at_base"] == "meaningful"
    rc, out = cli(wt, "land", "--attempt", att["attempt_id"])
    assert (rc, out["method"], out["sha"]) == (0, "ff", tip)

    rc, other = cli(wt, "open", "--task", "1.2", "--design-dir", DD, "--root", str(wt))
    rc, out = cli(tmp_path, "discard", "--attempt", other["attempt_id"], "--root", str(wt))
    assert (rc, out["attempt_id"], out["removed_dir"]) == (0, other["attempt_id"], True)
    assert not Path(other["attempt_dir"]).exists()
    rc, out = cli(wt, "sweep", "--design-dir", DD)
    assert rc == 0 and out == {"discarded": [], "landed": [], "log": [],
                               "scratch": {"worktrees": [], "branches": []},
                               "ladder": {"removed": [], "kept_orphans": []}}


def test_cli_exit_codes(tmp_path):
    wt = _dispatcher(tmp_path)
    _rc, one = cli(wt, "open", "--task", "1.1", "--design-dir", DD)
    _rc, two = cli(wt, "open", "--task", "1.2", "--design-dir", DD)
    rc, res = _check(wt, one["attempt_id"])
    assert (rc, res["verdict"], res["reason"]) == (1, "FAIL", "no commit")
    commit_pair(Path(one["attempt_dir"]), {"skills/test_a.py": GREEN},
                {"skills/a.py": "A = 2\n"})
    commit_pair(Path(two["attempt_dir"]), {"skills/test_a.py": GREEN.replace("== 2", "== 3")},
                {"skills/a.py": "A = 3\n"})
    assert _check(wt, one["attempt_id"])[0] == 0

    write(wt, "skills/stray.py")
    rc, res = _check(wt, one["attempt_id"])
    assert (rc, res["reason"]) == (2, "dispatcher dirtied")
    assert res["recover"].endswith(f"discard --attempt {one['attempt_id']}")
    rc, res = cli(wt, "open", "--task", "1.3", "--design-dir", DD)
    assert (rc, res["error"], res["paths"]) == (2, "dirty-tree", ["skills/stray.py"])
    (wt / "skills/stray.py").unlink()
    # land needs a PASS check of the landed commit; the last check was an env-error.
    assert cli(wt, "land", "--attempt", one["attempt_id"])[1]["reason"] == "not-passed: env-error"
    assert _check(wt, one["attempt_id"])[0] == 0
    assert _check(wt, two["attempt_id"])[0] == 0

    assert cli(wt, "land", "--attempt", one["attempt_id"])[0] == 0
    rc, out = cli(wt, "land", "--attempt", two["attempt_id"])
    assert (rc, out["reason"]) == (2, "land-conflict") and "recover" in out
    rc, out = cli(wt, "check", "--attempt", "demo/nope-0", "--plan", f"{DD}/plan.md",
                  "--phase", "1", "--rung", "local")
    assert rc == 2 and out["error"] == "unknown-attempt"
    rc, out = cli(wt, "sweep", "--design-dir", DD)
    assert rc == 0 and out["discarded"] == [two["attempt_id"]] and out["landed"] == []
