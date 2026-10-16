"""Hermetic tests for base_sync_window.py (design: one-cheap-engine Task 3.3).

A base-sync window runs on a Strata session under `--local` and on Sonnet
otherwise — chosen by the launcher, not by seat memory (design.md Done-when 8).
`which` is injected so the PATH probe never depends on the developer's shell.
"""
from __future__ import annotations

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import base_sync_window as bsw  # noqa: E402
import launch_design_run as ldr  # noqa: E402


def _which(found: bool):
    """Injected `shutil.which` stand-in: finds the launcher only when `found`."""
    def probe(name: str):
        return f"/usr/local/bin/{name}" if found else None
    return probe


# --- the builder -----------------------------------------------------

def test_local_uses_strata_session():
    cmd, notes = bsw.window_command("foo", "/r/wt/foo", local=True, which=_which(True))
    assert "claude-strata" in cmd
    assert "/tp-merge-from-main foo" in cmd
    assert "--model sonnet" not in cmd
    assert cmd.startswith("cd ")
    assert "/r/wt/foo" in cmd
    assert notes == []


def test_no_local_is_sonnet():
    cmd, notes = bsw.window_command("foo", "/r/wt/foo", local=False, which=_which(True))
    assert "claude --model sonnet" in cmd
    assert "/tp-merge-from-main foo" in cmd
    assert "claude-strata" not in cmd
    assert notes == []


def test_local_without_strata_launcher_is_sonnet_with_note():
    cmd, notes = bsw.window_command("foo", "/r/wt/foo", local=True, which=_which(False))
    assert "claude --model sonnet" in cmd
    assert "claude-strata" not in cmd
    assert "/tp-merge-from-main foo" in cmd
    assert len(notes) == 1
    assert "sonnet" in notes[0].lower()


def test_strata_launcher_name_from_env_or_default(monkeypatch):
    assert bsw.STRATA_LAUNCHER == "claude-strata"
    monkeypatch.setenv("TP_STRATA_LAUNCHER", "claude-local")
    cmd, notes = bsw.window_command("foo", "/r/wt/foo", local=True, which=_which(True))
    assert "claude-local" in cmd
    assert "claude-strata" not in cmd
    assert notes == []


# --- the launcher flag -----------------------------------------------

def _git(*args, cwd):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
                   cwd=cwd, check=True, capture_output=True)


def _repo(tmp_path, monkeypatch):
    """A fixture repo with a worktree on `tp/foo`, and no inherited local/git state."""
    for var in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
                "TP_LOCAL", "TP_STRATA_LAUNCHER", "TMUX"):
        monkeypatch.delenv(var, raising=False)
    repo = tmp_path / "repo"
    repo.mkdir()
    _git("init", "-q", cwd=repo)
    _git("commit", "-q", "--allow-empty", "-m", "init", cwd=repo)
    _git("worktree", "add", "-q", "-b", "tp/foo", str(tmp_path / "wt" / "foo"), cwd=repo)
    return str(repo)


def test_launcher_base_sync_flag(tmp_path, monkeypatch, capsys):
    repo = _repo(tmp_path, monkeypatch)
    env = {"PATH": os.environ.get("PATH", "")}
    rc = ldr.main(["foo", "--base-sync"], env=env, cwd=repo)
    out = capsys.readouterr().out
    assert rc == 0
    assert "/tp-merge-from-main foo" in out
    assert "claude --model sonnet" in out  # no --local -> Sonnet
    assert "tp-run-full-design" not in out  # the flag replaces the design-run launch
