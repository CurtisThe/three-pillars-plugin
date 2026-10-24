"""test_attempt_salvage.py — attempt_salvage records an attempt before it is discarded.

design: ladder-diagnose-and-size-pins (plan Task 1.4). Real tmp repos via `attempt_fixture`.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import ladder_files  # noqa: E402
import task_attempts  # noqa: E402
from attempt_fixture import DD, IDENTITY, commit, git, make_seat, write  # noqa: E402
from task_scope import _git_env as clean_git_env  # noqa: E402


def _salvage(cwd: Path, attempt_id: str, ldir: Path, cfg: Path):
    env = clean_git_env(**IDENTITY, CLAUDE_CONFIG_DIR=str(cfg))
    proc = subprocess.run(
        [sys.executable, str(HERE / "attempt_salvage.py"), "salvage", "--attempt", attempt_id,
         "--ladder-dir", str(ldir), "--agent-id", "a0000014"],
        cwd=str(cwd), capture_output=True, text=True, env=env, timeout=120)
    out = json.loads(proc.stdout.strip().splitlines()[-1]) if proc.stdout.strip() else {}
    return proc, out


def _attempt(tmp_path: Path):
    _seat, wt = make_seat(tmp_path)
    rec = task_attempts.open_attempt(wt, "1.4", DD)
    return wt, rec, Path(rec["attempt_dir"]), tmp_path / "ldir"


def test_salvage_records_commits_patch_and_uncommitted_work(tmp_path):
    wt, rec, adir, ldir = _attempt(tmp_path)
    red = commit(adir, {"t/test_a.py": "def test_a(): assert 0\n"}, "Red: demo 1.4 — t")
    commit(adir, {"skills/a.py": "A = 2\n"}, "Implement: demo 1.4 — t")
    write(adir, "skills/a.py", "A = 3\n")
    write(adir, "skills/new.py", "NEW = 1\n")  # untracked
    proc, out = _salvage(wt, rec["attempt_id"], ldir, tmp_path / "cfg")
    assert proc.returncode == 0 and out["salvaged"] is True
    nonce = rec["attempt_id"].split("/")[1]
    path = ldir / "1.4.salvage" / f"{nonce}.json"
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["attempt_id"] == rec["attempt_id"] and saved["task_id"] == "1.4"
    assert saved["base_sha"] == rec["base_sha"] and saved["red_sha"] == red
    assert [c["subject"] for c in saved["commits"]] == ["Implement: demo 1.4 — t",
                                                        "Red: demo 1.4 — t"]
    patch = Path(saved["patch"]).read_text(encoding="utf-8")
    assert "A = 3" in patch and "NEW = 1" in patch and "test_a" in patch
    assert set(saved["digest"]) == {"test", "files", "calls"}


def test_empty_attempt_has_null_red_and_no_patch(tmp_path):
    wt, rec, _adir, ldir = _attempt(tmp_path)
    proc, out = _salvage(wt, rec["attempt_id"], ldir, tmp_path / "cfg")
    assert proc.returncode == 0 and out["salvaged"] is True
    saved = json.loads(Path(out["record"]).read_text(encoding="utf-8"))
    assert saved["red_sha"] is None and saved["patch"] is None and saved["commits"] == []
    assert "digest" in saved
    assert [p.suffix for p in (ldir / "1.4.salvage").iterdir()] == [".json"]


def test_errors_print_one_stderr_line_and_exit_zero(tmp_path):
    wt, rec, adir, ldir = _attempt(tmp_path)
    proc, out = _salvage(wt, "demo/9.9-deadbeef", ldir, tmp_path / "cfg")
    assert proc.returncode == 0 and out["salvaged"] is False
    assert len(proc.stderr.strip().splitlines()) == 1
    shutil.rmtree(adir)
    proc, out = _salvage(wt, rec["attempt_id"], ldir, tmp_path / "cfg")
    assert proc.returncode == 0 and out["salvaged"] is False
    assert len(proc.stderr.strip().splitlines()) == 1


def test_fresh_keeps_salvage_and_sweep_removes_it_once_no_live_attempt(tmp_path):
    _seat, wt = make_seat(tmp_path)
    ldir = ladder_files.ladder_dir(wt, "demo")
    sal = ldir / "1.4.salvage"
    sal.mkdir(parents=True)
    (sal / "x.json").write_text("{}\n")
    env = clean_git_env(**IDENTITY)
    subprocess.run([sys.executable, str(HERE / "ladder_files.py"), "paths", "--slug", "demo",
                    "--task", "1.4", "--fresh"], cwd=str(wt), env=env, check=True,
                   capture_output=True, text=True)
    assert (sal / "x.json").exists()
    rec = task_attempts.open_attempt(wt, "1.4", DD)  # a live attempt keeps it
    ladder_files.sweep(wt, "demo")
    assert (sal / "x.json").exists()
    task_attempts.discard(rec, root=wt)
    ladder_files.sweep(wt, "demo")
    assert not sal.exists()
    assert git(wt, "rev-parse", "--abbrev-ref", "HEAD") == "tp/demo"
