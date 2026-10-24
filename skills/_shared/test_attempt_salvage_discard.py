"""test_attempt_salvage_discard.py — salvage first, then discard: the work outlives the attempt.

design: ladder-diagnose-and-size-pins (plan Task 1.5)

The dispatcher runs `attempt_salvage.py salvage` before every `task_verify.py discard` of a
spawned attempt. This file runs both against a real tmp repo and pins what the next rung
relies on: the record and the patch remain under the ladder dir, the Red sha still
cherry-picks onto a fresh attempt opened at the same base, and `render --ladder-dir` names
that sha. Real repos via `attempt_fixture`; anchors only (`skills/_shared/test-fragility.md`).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import task_attempts  # noqa: E402
from attempt_fixture import DD, IDENTITY, branches, commit, git, make_seat, write  # noqa: E402
from task_scope import _git_env as clean_git_env  # noqa: E402

PLAN = """## Phase 1: Implementation

### Task 1.5: The one that failed
**File**: `skills/a.py` (modify)
**Targets**: `t/test_a.py` (new)
"""


def _run(cwd: Path, script: str, *args: str, cfg: Path) -> dict:
    env = clean_git_env(**IDENTITY, CLAUDE_CONFIG_DIR=str(cfg))
    proc = subprocess.run([sys.executable, str(HERE / script), *args], cwd=str(cwd),
                          capture_output=True, text=True, env=env, timeout=120)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return json.loads(proc.stdout) if script == "task_verify.py" \
        else json.loads(proc.stdout.strip().splitlines()[-1])


def _failed_attempt(tmp_path: Path):
    """A seat, a design worktree, and an open attempt that committed a Red and left work."""
    _seat, wt = make_seat(tmp_path)
    rec = task_attempts.open_attempt(wt, "1.5", DD)
    adir = Path(rec["attempt_dir"])
    red = commit(adir, {"t/test_a.py": "def test_a(): assert 0\n"}, "Red: demo 1.5 — t")
    write(adir, "skills/a.py", "A = 99\n")  # uncommitted work
    return wt, rec, adir, red


def test_discard_after_salvage_keeps_the_record_the_patch_and_a_cherry_pickable_red(tmp_path):
    wt, rec, adir, red = _failed_attempt(tmp_path)
    ldir, cfg = tmp_path / "ladder", tmp_path / "cfg"
    saved = _run(wt, "attempt_salvage.py", "salvage", "--attempt", rec["attempt_id"],
                 "--ladder-dir", str(ldir), "--agent-id", "a0000015", cfg=cfg)
    assert saved["salvaged"] is True

    out = _run(wt, "task_verify.py", "discard", "--attempt", rec["attempt_id"], cfg=cfg)
    assert out["removed_dir"] is True
    assert not adir.exists() and not branches(wt)           # the attempt is gone ...

    record = json.loads(Path(saved["record"]).read_text(encoding="utf-8"))
    assert record["red_sha"] == red                          # ... the record is not
    assert "A = 99" in Path(record["patch"]).read_text(encoding="utf-8")

    fresh = task_attempts.open_attempt(wt, "1.5", DD)        # a new attempt at the same base
    assert fresh["base_sha"] == rec["base_sha"]
    fresh_dir = Path(fresh["attempt_dir"])
    git(fresh_dir, "cherry-pick", red)
    assert (fresh_dir / "t" / "test_a.py").read_text(encoding="utf-8").startswith("def test_a")
    assert git(fresh_dir, "log", "-1", "--format=%s") == "Red: demo 1.5 — t"


def test_render_after_discard_names_the_saved_red_and_patch(tmp_path):
    wt, rec, _adir, red = _failed_attempt(tmp_path)
    ldir, cfg = tmp_path / "ladder", tmp_path / "cfg"
    saved = _run(wt, "attempt_salvage.py", "salvage", "--attempt", rec["attempt_id"],
                 "--ladder-dir", str(ldir), "--agent-id", "a0000015", cfg=cfg)
    _run(wt, "task_verify.py", "discard", "--attempt", rec["attempt_id"], cfg=cfg)

    plan = tmp_path / "plan.md"
    plan.write_text(PLAN, encoding="utf-8")
    env = clean_git_env(**IDENTITY)
    proc = subprocess.run(
        [sys.executable, str(HERE / "task_prompt_blocks.py"), "render", "--plan", str(plan),
         "--phase", "1", "--task", "1.5", "--root", str(wt), "--ladder-dir", str(ldir)],
        capture_output=True, text=True, env=env, timeout=120)
    assert proc.returncode == 0, proc.stderr
    assert "PRIOR ATTEMPT" in proc.stdout
    assert f"git cherry-pick {red}" in proc.stdout
    assert saved["patch"] in proc.stdout
