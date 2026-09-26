"""Hermetic tests for launch_design_run.py — stub tmux, fixture repo + profile."""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import design_run_command as drc  # noqa: E402
import launch_design_run as ldr  # noqa: E402

PORCELAIN = (
    "worktree /r/main\nHEAD abc\nbranch refs/heads/master\n\n"
    "worktree /r/wt/foo\nHEAD def\nbranch refs/heads/tp/foo\n\n"
    "worktree /r/wt/bar\nHEAD 123\ndetached\n"
)


def _git(*args, cwd):
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=cwd, check=True, capture_output=True,
    )


@pytest.fixture
def rig(tmp_path, monkeypatch):
    for var in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    repo = tmp_path / "repo"
    repo.mkdir()
    _git("init", "-q", cwd=repo)
    _git("commit", "-q", "--allow-empty", "-m", "init", cwd=repo)
    wt = tmp_path / "wt" / "foo"
    _git("worktree", "add", "-q", "-b", "tp/foo", str(wt), cwd=repo)
    wt = os.path.realpath(str(wt))
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "tmux.log"
    stub = bindir / "tmux"
    stub.write_text(
        '#!/bin/sh\nfor a in "$@"; do printf "%s\\n" "$a" >> "' + str(log)
        + '"; done\necho sess:3\n',
        encoding="utf-8",
    )
    stub.chmod(0o755)
    cfg = tmp_path / "prof"
    cfg.mkdir()
    (cfg / ".claude.json").write_text(json.dumps({"keep": 1}), encoding="utf-8")
    env = {
        "PATH": f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}",
        "TMUX": f"{tmp_path}/tmux-sock,1,0",
        "CLAUDE_CONFIG_DIR": str(cfg),
    }
    return {"repo": str(repo), "wt": wt, "log": log, "cfg": str(cfg), "env": env}


def _run(rig, argv, **env_over):
    env = dict(rig["env"])
    for k, v in env_over.items():
        if v is None:
            env.pop(k, None)
        else:
            env[k] = v
    return ldr.main(argv, env=env, cwd=rig["repo"])


def _trusted(rig):
    data = json.loads(open(os.path.join(rig["cfg"], ".claude.json"), encoding="utf-8").read())
    return data.get("projects", {}).get(rig["wt"], {}).get("hasTrustDialogAccepted")


def test_find_worktree_matches_branch():
    assert ldr.find_worktree(PORCELAIN, "foo") == "/r/wt/foo"
    assert ldr.find_worktree(PORCELAIN, "bar") is None
    assert ldr.find_worktree(PORCELAIN, "nope") is None


def test_launch_opens_detached_window(rig, capsys):
    assert _run(rig, ["foo", "--skip-design"]) == 0
    logged = rig["log"].read_text(encoding="utf-8").splitlines()
    cmd = drc.window_command("foo", rig["wt"], skip_design=True, config_dir=rig["cfg"])
    assert logged == ["new-window", "-d", "-n", "foo", "-P", "-F",
                      "#{session_name}:#{window_index}", cmd]
    assert _trusted(rig) is True
    out = capsys.readouterr().out
    assert "sess:3" in out and "tmux link-window -s sess:3" in out


def test_mode_passthrough(rig):
    assert _run(rig, ["foo", "--mode", "build", "--skip-design"]) == 0
    logged = rig["log"].read_text(encoding="utf-8")
    assert "/tp-run-full-design foo --mode build --skip-design" in logged


def test_tmux_env_unset_prints_manual(rig, capsys):
    assert _run(rig, ["foo"], TMUX=None) == 2
    assert not rig["log"].exists()
    out = capsys.readouterr().out
    assert "TP_DESIGN_RUN=1" in out and "claude --model opus" in out


def test_tmux_absent_prints_manual(rig, capsys):
    assert _run(rig, ["foo"], PATH="/nonexistent-dir") == 2
    assert "claude --model opus" in capsys.readouterr().out


def test_dry_run_does_not_call_tmux(rig, capsys):
    assert _run(rig, ["foo", "--dry-run"]) == 0
    assert not rig["log"].exists()
    assert "TP_DESIGN_RUN=1" in capsys.readouterr().out


def test_local_passthrough_dry_run(rig, capsys, monkeypatch):
    seen = []
    real = drc.window_command

    def spy(*args, **kwargs):
        seen.append(kwargs.get("local"))
        return real(*args, **kwargs)

    monkeypatch.setattr(drc, "window_command", spy)
    assert _run(rig, ["foo", "--local", "--dry-run"]) == 0
    out = capsys.readouterr().out.strip().splitlines()[-1]
    assert out.endswith("'/tp-run-full-design foo --local'; exec bash")
    assert seen == [True, True]  # the validation call and the real one
    seen.clear()
    assert _run(rig, ["foo", "--dry-run"]) == 0
    assert "--local" not in capsys.readouterr().out
    assert seen == [False, False]
    assert not rig["log"].exists()


def test_missing_worktree(rig, capsys):
    assert _run(rig, ["nope"]) == 2
    err = capsys.readouterr().err
    assert "git worktree add" in err and "tp/nope" in err
    assert not rig["log"].exists()


def test_fable_refused_before_side_effects(rig):
    assert _run(rig, ["foo", "--model", "fable"]) == 2
    assert not rig["log"].exists()
    assert _trusted(rig) is None


def test_config_dir_unset_warns(rig, capsys):
    assert _run(rig, ["foo"], CLAUDE_CONFIG_DIR=None) == 0
    cap = capsys.readouterr()
    assert "CLAUDE_CONFIG_DIR" in cap.err
    assert "CLAUDE_CONFIG_DIR=" not in rig["log"].read_text(encoding="utf-8")


def test_corrupt_profile_falls_back_to_manual(rig, capsys):
    prof = os.path.join(rig["cfg"], ".claude.json")
    with open(prof, "w", encoding="utf-8"):
        pass
    assert _run(rig, ["foo"]) == 2
    cap = capsys.readouterr()
    assert "claude --model opus" in cap.out and "could not pre-trust" in cap.err
    assert not rig["log"].exists()
    assert open(prof, encoding="utf-8").read() == ""
