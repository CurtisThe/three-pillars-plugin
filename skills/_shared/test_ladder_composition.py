"""test_ladder_composition.py — the ladder and task_verify composed, as a dispatcher runs them.

design: local-implement-and-review (Behaviors 4, 5, 6)

A tmp repo with ``local_implement.max_retries: 0`` and a scripted fake worker: a red
commit → ``check`` exit 1 → ``discard`` → ``next FAIL`` escalates to local-xhigh → the
red/green pair → ``check`` exit 0 → ``land`` → ``next PASS`` → done. Exactly the pair lands
and no attempt is left. Both CLIs run as subprocesses; the ambient repo is never read (M23).
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

from attempt_fixture import IDENTITY, DD, branches, commit, commit_pair, git, make_seat
from task_scope import _git_env as clean_git_env  # shipped scrub; git_env is dev-only
from agent_ref import resolve as _ref  # the spawn reference (this install's plugin name)

SHARED = Path(__file__).resolve().parent
PLAN = """# demo plan

## Phase 1: Demo

### Task 1.1: Change A
**File**: `skills/a.py`
**Test**: `skills/test_a.py::test_a`
**Targets**: `skills/test_a.py::test_a` (new)
**Red**: test_a asserts that A equals two.
**Green**: set A to two.
"""
TEST = "import a\n\n\ndef test_a():\n    assert a.A == 2\n"
CONFIG = {"local_implement": {"enabled": True, "max_retries": 0}}
ROUTED = {"schema": "tp-local-route/v1", "state": "routed", "reason": "ok",
          "base_url": "http://127.0.0.1:3457", "checked_at": "2026-09-27T00:00:00Z"}


def run(cwd: Path, script: str, *args: str) -> tuple[int, dict]:
    proc = subprocess.run([sys.executable, str(SHARED / script), *args], cwd=str(cwd),
                          capture_output=True, text=True, env=clean_git_env(**IDENTITY),
                          timeout=300)
    return proc.returncode, json.loads(proc.stdout)


def attempt(wt: Path, red: dict, green: dict | None = None) -> tuple[dict, int, dict]:
    """Open an attempt, let the fake worker commit ``red`` (then ``green``, as the pair),
    and check it."""
    _rc, att = run(wt, "task_verify.py", "open", "--task", "1.1", "--design-dir", DD)
    if green:
        commit_pair(Path(att["attempt_dir"]), red, green)
    else:
        commit(Path(att["attempt_dir"]), red, "fake worker")
    rc, res = run(wt, "task_verify.py", "check", "--attempt", att["attempt_id"], "--plan",
                  f"{DD}/plan.md", "--phase", "1", "--rung", "local",
                  "--test-cmd", f"{shlex.quote(sys.executable)} -m pytest -q")
    return att, rc, res


def test_fail_retry_escalate_land(tmp_path):
    _seat, wt = make_seat(tmp_path)
    base = commit(wt, {".three-pillars/config.json": json.dumps(CONFIG),
                       f"{DD}/plan.md": PLAN}, "config + plan")
    record = str(tmp_path / "R.json")
    run(wt, "tier_ladder.py", "start", "--task", "1.1", "--tier", "local", "--record", record,
        "--route", json.dumps(ROUTED))

    att, rc, res = attempt(wt, {"skills/test_a.py": TEST})  # red: A is still 1
    assert (rc, res["reason"]) == (1, "red test")
    run(wt, "task_verify.py", "discard", "--attempt", att["attempt_id"])
    rc, step = run(wt, "tier_ladder.py", "next", "--record", record, "--outcome", "FAIL",
                   "--root", str(wt), "--reason", res["reason"])
    assert step == {"action": "escalate", "tier": "local", "rung": "local-xhigh",
                    "agent": "tp-task-worker-local-xhigh", "agent_ref": _ref("tp-task-worker-local-xhigh"), "model": "haiku"}

    att, rc, res = attempt(wt, {"skills/test_a.py": TEST}, {"skills/a.py": "A = 2\n"})
    assert (rc, res["verdict"]) == (0, "PASS"), res["reason"]
    rc, landed = run(wt, "task_verify.py", "land", "--attempt", att["attempt_id"])
    assert rc == 0 and landed["method"] == "ff"
    rc, step = run(wt, "tier_ladder.py", "next", "--record", record, "--outcome", "PASS",
                   "--root", str(wt), "--red-at-base", res["red_at_base"])
    assert step == {"action": "done", "tier": None, "rung": None, "agent": None, "agent_ref": None, "model": None}

    assert git(wt, "rev-list", "--count", f"{base}..HEAD") == "2"  # the red, then the green
    assert git(wt, "rev-parse", "HEAD") == landed["sha"]
    worktrees = wt / ".tp-scratch"
    assert not worktrees.exists() or not [n for n in os.listdir(worktrees)
                                          if n.startswith("tp-attempt-")]
    assert branches(wt) == []
    final = json.loads(Path(record).read_text(encoding="utf-8"))
    assert (final["final"], final["tier_path"]) == ("done", ["local-medium", "local-xhigh"])
