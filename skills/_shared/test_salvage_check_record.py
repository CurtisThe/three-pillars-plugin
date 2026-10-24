"""test_salvage_check_record.py — retry feedback survives `--fresh` via the salvage record.

design: ladder-diagnose-and-size-pins (plan Task 9.1)

`attempt_salvage.py salvage --check-json C` stores a FAIL check's reason and test tail as
`record["check"]`; `task_prompt_blocks.py render --ladder-dir L` falls back to it when no
`--check-json` is given, and a bad `--check-json` drops only the retry lines.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import task_attempts  # noqa: E402
from attempt_fixture import DD, IDENTITY, make_seat  # noqa: E402
from task_scope import _git_env as clean_git_env  # noqa: E402

BLOCKS = str(HERE / "task_prompt_blocks.py")
PLAN = """## Phase 1: Implementation

### Task 1.1: One
**File**: `skills/_shared/notes.md` (modify)
**Targets**: `skills/_shared/test_notes.py` (new)
"""
FAIL = {"verdict": "FAIL", "reason": "red-not-failing-9", "test_output_tail": "tail-line-9"}


def _salvage(cwd, attempt_id, ldir, cfg, check_arg=None):
    cmd = [sys.executable, str(HERE / "attempt_salvage.py"), "salvage", "--attempt", attempt_id,
           "--ladder-dir", str(ldir), "--agent-id", "a0000014"]
    if check_arg is not None:
        cmd += ["--check-json", str(check_arg)]
    env = clean_git_env(**IDENTITY, CLAUDE_CONFIG_DIR=str(cfg))
    proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, env=env, timeout=120)
    return proc, json.loads(proc.stdout.strip().splitlines()[-1])


def _record_for(tmp_path, check_arg_fn):
    wt = make_seat(tmp_path)[1]
    rec = task_attempts.open_attempt(wt, "1.4", DD)
    ldir = tmp_path / "ldir"
    proc, out = _salvage(wt, rec["attempt_id"], ldir, tmp_path / "cfg", check_arg_fn(tmp_path))
    nonce = rec["attempt_id"].split("/")[1]
    return proc, out, json.loads((ldir / "1.4.salvage" / f"{nonce}.json").read_text(encoding="utf-8"))


def test_salvage_stores_fail_check(tmp_path):
    def arg(tp):
        p = tp / "check.json"
        p.write_text(json.dumps(FAIL), encoding="utf-8")
        return p
    proc, out, saved = _record_for(tmp_path, arg)
    assert proc.returncode == 0 and out["salvaged"] is True
    assert saved["check"] == {"reason": "red-not-failing-9", "test_output_tail": "tail-line-9"}


def test_salvage_non_object_check_stores_none_and_still_salvages(tmp_path):
    def arg(tp):
        p = tp / "list.json"
        p.write_text("[1]", encoding="utf-8")
        return p
    proc, out, saved = _record_for(tmp_path, arg)
    assert proc.returncode == 0 and out["salvaged"] is True and "check" not in saved


def test_salvage_missing_check_stores_none_and_still_salvages(tmp_path):
    proc, out, saved = _record_for(tmp_path, lambda tp: tp / "missing.json")
    assert proc.returncode == 0 and out["salvaged"] is True and "check" not in saved


def _render(tmp_path, ldir, *extra):
    plan = tmp_path / "plan.md"
    plan.write_text(PLAN, encoding="utf-8")
    return subprocess.run(
        [sys.executable, BLOCKS, "render", "--plan", str(plan), "--phase", "1", "--task", "1.1",
         "--root", str(tmp_path), "--ladder-dir", str(ldir), *extra],
        capture_output=True, text=True, timeout=60)


def _ladder(tmp_path, check):
    sal = tmp_path / "ldir" / "1.1.salvage"
    sal.mkdir(parents=True)
    rec = {"attempt_id": "demo/1.1-aaaa1111", "task_id": "1.1", "red_sha": None, "patch": None,
           "digest": {}}
    if check is not None:
        rec["check"] = check
    (sal / "aaaa1111.json").write_text(json.dumps(rec), encoding="utf-8")
    return tmp_path / "ldir"


def test_render_uses_record_check_without_check_json(tmp_path):
    proc = _render(tmp_path, _ladder(tmp_path, {"reason": "rec-reason", "test_output_tail": "rec-tail"}))
    assert proc.returncode == 0
    assert "reason: rec-reason" in proc.stdout and "test_output_tail: rec-tail" in proc.stdout
    assert proc.stdout.index("reason: rec-reason") < proc.stdout.index("PRIOR ATTEMPT") \
        < proc.stdout.index("SIZE CAPS")


def test_record_without_check_prints_no_retry_lines(tmp_path):
    proc = _render(tmp_path, _ladder(tmp_path, None))
    assert proc.returncode == 0 and "reason:" not in proc.stdout


def test_explicit_fail_check_wins(tmp_path):
    ldir = _ladder(tmp_path, {"reason": "rec-reason", "test_output_tail": "rec-tail"})
    (tmp_path / "c.json").write_text(json.dumps(FAIL), encoding="utf-8")
    proc = _render(tmp_path, ldir, "--check-json", str(tmp_path / "c.json"))
    assert "reason: red-not-failing-9" in proc.stdout and "rec-reason" not in proc.stdout


def test_bad_check_json_drops_only_retry_lines(tmp_path):
    ldir = _ladder(tmp_path, {"reason": "rec-reason", "test_output_tail": "rec-tail"})
    (tmp_path / "obj.json").write_text("[1]", encoding="utf-8")
    for bad in (tmp_path / "missing.json", tmp_path / "obj.json"):
        proc = _render(tmp_path, ldir, "--check-json", str(bad))
        assert proc.returncode == 0 and proc.stderr.strip()
        assert "reason:" not in proc.stdout
        assert "PRIOR ATTEMPT" in proc.stdout and "SIZE CAPS" in proc.stdout


def test_unknown_task_still_exits_2(tmp_path):
    plan = tmp_path / "plan.md"
    plan.write_text(PLAN, encoding="utf-8")
    proc = subprocess.run([sys.executable, BLOCKS, "render", "--plan", str(plan), "--phase", "1",
                           "--task", "9.9", "--root", str(tmp_path)],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 2 and proc.stderr.strip()
