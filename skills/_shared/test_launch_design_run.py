"""Hermetic tests for launch_design_run.py — stub tmux, fixture repo + profile."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cheap_tier_default  # noqa: E402
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
        '#!/bin/sh\nfor a in "$@"; do printf "%s\\n" "$a" >> "' + str(log) + '"; done\n'
        'case "$1" in\n'
        '  has-session) exit 1 ;;\n'
        '  new-session) echo "@3 myfoo:1" ;;\n'
        '  display-message) echo seat ;;\n'
        '  *) exit 0 ;;\n'
        'esac\n',
        encoding="utf-8",
    )
    stub.chmod(0o755)
    plain = bindir / "claude"  # a plain claude (no lib/launcher/plan.py) shadows a host launcher
    plain.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    plain.chmod(0o755)
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
    # The cheap tier is always on: nothing is forwarded for it.
    cmd = drc.window_command("foo", rig["wt"], skip_design=True, config_dir=rig["cfg"])
    for arg in ("new-session", "-d", "-s", "foo", cmd):
        assert arg in logged
    assert "link-window" in logged and "=seat:" in logged
    assert _trusted(rig) is True
    out = capsys.readouterr().out
    assert "myfoo:1" in out and "tmux attach -t foo" in out


def test_live_run_refuses_without_a_second_launch_command(rig, capsys, monkeypatch):
    live = ldr.design_run_tmux.OpenResult(False, "a design run is already live", live=True)
    monkeypatch.setattr(ldr.design_run_tmux, "open", lambda *a, **k: live)
    assert _run(rig, ["foo", "--skip-design"]) == 2
    cap = capsys.readouterr()
    assert "already live" in cap.err and "/tp-run-full-design" not in cap.out


def test_mode_passthrough(rig):
    assert _run(rig, ["foo", "--mode", "build", "--skip-design"]) == 0
    logged = rig["log"].read_text(encoding="utf-8")
    assert "/tp-run-full-design foo --mode build --skip-design" in logged


def test_tmux_env_unset_prints_manual(rig, capsys):
    assert _run(rig, ["foo", "--model", "opus"], TMUX=None) == 2
    assert "new-session" not in rig["log"].read_text(encoding="utf-8")  # only the live probe
    out = capsys.readouterr().out
    assert "TP_DESIGN_RUN=1" in out and "claude --model opus" in out


def test_tmux_absent_prints_manual(rig, capsys):
    assert _run(rig, ["foo", "--model", "opus"], PATH="/nonexistent-dir") == 2
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
    # --no-cheap-tier keeps the tail about the cheap-tier default out of the way.
    assert _run(rig, ["foo", "--local", "--no-cheap-tier", "--dry-run"]) == 0
    out = capsys.readouterr().out.strip().splitlines()[-1]
    assert out.endswith("'/tp-run-full-design foo --local'; exec bash")
    assert seen == [True, True]  # the validation call and the real one
    seen.clear()
    assert _run(rig, ["foo", "--no-cheap-tier", "--dry-run"]) == 0
    assert "--local" not in capsys.readouterr().out
    assert seen == [False, False]
    assert not rig["log"].exists()


@pytest.mark.parametrize("argv,flag,tail", [
    (["--cheap-tier"], None, "foo'"),  # deprecated: parsed, never forwarded
    (["--cheap-tier=ab"], None, "foo'"),
    (["--cheap-tier", "on"], None, "foo'"),
    (["--local", "--cheap-tier=ab"], None, "foo --local'"),
    (["--no-cheap-tier"], None, "foo'"),
])
def test_cheap_tier_passthrough_dry_run(rig, capsys, monkeypatch, argv, flag, tail):
    seen = []
    real = drc.window_command

    def spy(*args, **kwargs):
        seen.append(kwargs.get("cheap_tier"))
        return real(*args, **kwargs)

    monkeypatch.setattr(drc, "window_command", spy)
    assert _run(rig, ["foo", *argv, "--dry-run"]) == 0
    out = capsys.readouterr().out.strip().splitlines()[-1]
    assert out.endswith(f"'/tp-run-full-design {tail}; exec bash")
    assert seen == [flag, flag]  # the validation call and the real one


@pytest.mark.parametrize("bad", ["--cheap-tier=off", "--cheap-tier=AB", "--cheap-tier=yes"])
def test_cheap_tier_rejects_other_values(rig, capsys, bad):
    with pytest.raises(SystemExit) as exc:
        _run(rig, ["foo", bad, "--dry-run"])
    assert exc.value.code == 2
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


def _set_design_run(rig, value):
    (Path(rig["repo"]) / ".three-pillars").mkdir(parents=True, exist_ok=True)
    (Path(rig["repo"]) / ".three-pillars" / "config.json").write_text(
        json.dumps({"schema_version": 1, "models": {"design_run": value}}),
        encoding="utf-8",
    )


def test_config_sonnet_applies_dry_run(rig, capsys):
    _set_design_run(rig, "sonnet")
    assert _run(rig, ["foo", "--dry-run"]) == 0
    cap = capsys.readouterr()
    assert "--model sonnet" in cap.out
    assert "WARNING" not in cap.err


def test_cli_model_overrides_config(rig, capsys):
    _set_design_run(rig, "sonnet")
    assert _run(rig, ["foo", "--model", "opus", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "--model opus" in out and "--model sonnet" not in out


def test_no_models_defaults_sonnet_no_warning(rig, capsys):
    # The model_policy design_run default (`sonnet[1m]`, shell-quoted by the builder).
    assert _run(rig, ["foo", "--dry-run"]) == 0
    cap = capsys.readouterr()
    assert "--model 'sonnet[1m]'" in cap.out
    assert "WARNING" not in cap.err


def test_cli_fable_without_config_refused(rig, capsys):
    assert _run(rig, ["foo", "--model", "fable", "--dry-run"]) == 2
    cap = capsys.readouterr()
    assert "fable" not in cap.out
    assert not rig["log"].exists()


def test_config_fable_dry_run_warns_once_no_write(rig, capsys):
    _set_design_run(rig, "fable")
    assert _run(rig, ["foo", "--dry-run"]) == 0
    cap = capsys.readouterr()
    warnings = [ln for ln in cap.err.splitlines() if "WARNING" in ln and "fable" in ln]
    assert len(warnings) == 1
    assert "--model fable" in cap.out
    decisions = Path(rig["wt"]) / "three-pillars-docs" / "tp-designs" / "foo" / "decisions.md"
    assert not decisions.exists()
    assert not rig["log"].exists()


def test_config_fable_real_launch_logs_once(rig, capsys):
    _set_design_run(rig, "fable")
    assert _run(rig, ["foo"]) == 0
    cap = capsys.readouterr()
    warnings = [ln for ln in cap.err.splitlines() if "WARNING" in ln and "fable" in ln]
    assert len(warnings) == 1
    assert "--model fable" in rig["log"].read_text(encoding="utf-8")
    decisions = Path(rig["wt"]) / "three-pillars-docs" / "tp-designs" / "foo" / "decisions.md"
    assert decisions.exists()
    text = decisions.read_text(encoding="utf-8")
    assert text.count("### [design-run] fable model") == 1


def test_config_dir_unset_warns(rig, capsys):
    assert _run(rig, ["foo"], CLAUDE_CONFIG_DIR=None) == 0
    cap = capsys.readouterr()
    assert "CLAUDE_CONFIG_DIR" in cap.err
    assert "CLAUDE_CONFIG_DIR=" not in rig["log"].read_text(encoding="utf-8")


def test_corrupt_profile_falls_back_to_manual(rig, capsys):
    prof = os.path.join(rig["cfg"], ".claude.json")
    with open(prof, "w", encoding="utf-8"):
        pass
    assert _run(rig, ["foo", "--model", "opus"]) == 2
    cap = capsys.readouterr()
    assert "claude --model opus" in cap.out and "could not pre-trust" in cap.err
    assert not rig["log"].exists()
    assert open(prof, encoding="utf-8").read() == ""


# --- cheap_tier.default_run_flag: this repo's runs carry --cheap-tier=ab -------------


def _config(rig, block):
    path = Path(rig["repo"]) / ".three-pillars" / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema_version": 1, **block}), encoding="utf-8")


@pytest.mark.parametrize("block,argv,tail", [
    # the repo default is deprecated: it never reaches the run's command
    ({"cheap_tier": {"default_run_flag": "ab"}}, [], "foo'"),
    ({"cheap_tier": {"default_run_flag": "on"}}, ["--local"], "foo --local'"),
    ({"cheap_tier": {"default_run_flag": "ab"}}, ["--cheap-tier"], "foo'"),
    ({}, [], "foo'"),
    ({"cheap_tier": {}}, [], "foo'"),
    ({"cheap_tier": {"default_run_flag": "AB"}}, [], "foo'"),
    ({"cheap_tier": {"default_run_flag": "off"}}, [], "foo'"),
    ({"cheap_tier": {"default_run_flag": "ab"}}, ["--no-cheap-tier"], "foo'"),
])
def test_config_default_run_flag(rig, capsys, block, argv, tail):
    _config(rig, block)
    assert _run(rig, ["foo", *argv, "--dry-run"]) == 0
    out = capsys.readouterr().out.strip().splitlines()[-1]
    assert out.endswith(f"'/tp-run-full-design {tail}; exec bash")


def test_default_cheap_tier_is_on_for_every_value():
    # one-cheap-engine 3.6: `cheap_tier.default_run_flag` is deprecated and changes nothing.
    for flag in ("ab", "on", "off"):
        assert ldr.default_cheap_tier({"cheap_tier": {"default_run_flag": flag}}) == "on"
    for cfg in (None, {}, {"cheap_tier": None}, {"cheap_tier": {}},
                {"cheap_tier": {"default_run_flag": "x"}},
                {"cheap_tier": {"default_run_flag": True}}, {"models": {"handoff": "x"}}):
        assert ldr.default_cheap_tier(cfg) == "on"


def test_no_cheap_tier_excludes_cheap_tier(rig, capsys):
    with pytest.raises(SystemExit) as exc:
        _run(rig, ["foo", "--no-cheap-tier", "--cheap-tier=ab", "--dry-run"])
    assert exc.value.code == 2


@pytest.mark.parametrize("block,argv,deprecated", [
    # The retired switches are reported from the raw config, even when the
    # loader prunes the value; nothing is ever added to the command.
    ({"cheap_tier": {"default_run_flag": "off", "extra": 1}}, [], 1),
    ({"cheap_tier": "ab"}, [], 0),
    ({"cheap_tier": {"default_run_flag": "AB"}}, ["--cheap-tier=ab"], 2),
])
def test_a_pruned_cheap_tier_key_is_reported(rig, capsys, block, argv, deprecated):
    _config(rig, block)
    assert _run(rig, ["foo", *argv, "--dry-run"]) == 0
    cap = capsys.readouterr()
    assert cap.out.strip().splitlines()[-1].endswith("'/tp-run-full-design foo'; exec bash")
    assert cap.err.count("deprecated:") == deprecated
    assert "no --cheap-tier added" not in cap.err


# --- local_implement.default_run_flag: a repo can default its runs to --local -----

LOCAL_ON = {"local_implement": {"enabled": True, "full_design": True,
                                "default_run_flag": "on"}}


def _tail(rig, capsys, argv):
    """The slash-command tail of the dry-run command for `argv`."""
    assert _run(rig, ["foo", *argv, "--dry-run"]) == 0
    return capsys.readouterr().out.strip().splitlines()[-1]


def test_local_default_from_config_dry_run(rig, capsys):
    _config(rig, LOCAL_ON)
    assert _tail(rig, capsys, ["--no-cheap-tier"]).endswith(
        "'/tp-run-full-design foo --local'; exec bash")


def test_no_local_removes_the_config_default(rig, capsys):
    _config(rig, LOCAL_ON)
    assert _tail(rig, capsys, ["--no-local", "--no-cheap-tier"]).endswith(
        "'/tp-run-full-design foo'; exec bash")


def test_explicit_local_wins_without_a_config_default(rig, capsys):
    assert _tail(rig, capsys, ["--local", "--no-cheap-tier"]).endswith(
        "'/tp-run-full-design foo --local'; exec bash")


def test_local_and_no_local_are_mutually_exclusive(rig, capsys):
    with pytest.raises(SystemExit) as exc:
        _run(rig, ["foo", "--local", "--no-local", "--dry-run"])
    assert exc.value.code == 2
    assert not rig["log"].exists()


def test_local_default_needs_enabled(rig, capsys):
    _config(rig, {"local_implement": {"enabled": False, "full_design": True,
                                      "default_run_flag": "on"}})
    assert _tail(rig, capsys, ["--no-cheap-tier"]).endswith(
        "'/tp-run-full-design foo'; exec bash")


def test_a_pruned_local_default_flag_is_reported(rig, capsys):
    _config(rig, {"local_implement": {"enabled": True, "full_design": True,
                                      "default_run_flag": "yes"}})
    assert _run(rig, ["foo", "--no-cheap-tier", "--dry-run"]) == 0
    cap = capsys.readouterr()
    assert "warning: config: dropped local_implement.default_run_flag" in cap.err
    assert cap.out.strip().splitlines()[-1].endswith("'/tp-run-full-design foo'; exec bash")


def test_local_default_rides_before_the_cheap_tier_default(rig, capsys):
    _config(rig, dict(LOCAL_ON, cheap_tier={"default_run_flag": "ab"}))
    assert _tail(rig, capsys, []).endswith(
        "'/tp-run-full-design foo --local'; exec bash")


def _pass_capability(monkeypatch):
    """Make the runaway-ceiling capability gate pass for `full_design`."""
    monkeypatch.setattr(
        cheap_tier_default.lic, "load_capability",
        lambda path: {"nested": {"background_spawn_ok": True, "done_detected": True}})


def test_a_malformed_local_block_is_not_forwarded(rig, capsys, monkeypatch):
    _pass_capability(monkeypatch)
    _config(rig, {"local_implement": {"enabled": True, "full_design": True,
                                      "default_run_flag": "on", "max_files": 0}})
    assert _run(rig, ["foo", "--no-cheap-tier", "--dry-run"]) == 0
    cap = capsys.readouterr()
    assert "--local" not in cap.out
    assert "max_files" in cap.err


def test_explicit_local_still_forwarded_with_a_malformed_block(rig, capsys, monkeypatch):
    _pass_capability(monkeypatch)
    _config(rig, {"local_implement": {"enabled": True, "full_design": True,
                                      "default_run_flag": "on", "max_files": 0}})
    assert _tail(rig, capsys, ["--local", "--no-cheap-tier"]).endswith(
        "'/tp-run-full-design foo --local'; exec bash")


def test_cheap_tier_warning_matches_the_block_or_its_keys():
    assert ldr.cheap_tier_warning("config: dropped cheap_tier (type 'object')")
    assert ldr.cheap_tier_warning("config: dropped cheap_tier.default_run_flag (not in ['on', 'ab'])")
    assert not ldr.cheap_tier_warning("config: dropped cheap_tier_x (unknown key)")
    assert not ldr.cheap_tier_warning("config: dropped models.task (type 'string')")
