"""run-scratch-in-fence 1.6 -- the launcher's env plan carries the run's scratch pairs.

`dwe.plan(..., scratch=pairs)` and `drc.env_prefix(..., scratch=pairs)` append the run's
`TMPDIR`/`TMP`/`TEMP`/cache pairs and never unset them; `design_run_launch_plan.build` computes
them from the worktree; `launch_design_run.main` provisions the worktree once before the command
is built (not on --dry-run) and, when that fails, adds one note and drops the pairs; resume gets
the same pairs. The rig is test_launch_design_run.py's; it masks the pairs for the older tests,
so `srig` here puts the real function back.
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import design_run_command as drc  # noqa: E402
import design_run_launch_plan as lp  # noqa: E402
import design_run_window_env as dwe  # noqa: E402
import launch_design_run as ldr  # noqa: E402
import run_scratch  # noqa: E402
from test_launch_design_run import _run, rig  # noqa: E402,F401
from test_launch_design_run_resume_flags import SID_NEW, _two  # noqa: E402

REAL_PAIRS = run_scratch.env_pairs
WT = "/r/wt/foo"
PAIRS = REAL_PAIRS(WT, {})
NAMES = [name for name, _ in PAIRS]
OWNED_ALL = ",".join([*NAMES, "TP_LOCAL"])


@pytest.fixture
def srig(rig, monkeypatch):  # noqa: F811
    monkeypatch.setattr(run_scratch, "env_pairs", REAL_PAIRS)
    return rig


def _common(srig):
    out = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
                         cwd=srig["wt"], capture_output=True, text=True, check=True)
    return out.stdout.strip()


def _baseline(srig):
    return os.path.join(_common(srig), "tp-scratch", "foo", "baseline.json")


def _spy_provision(monkeypatch):
    calls = []
    real = ldr.scratch_leftovers.main

    def spy(argv=None, *a, **k):
        calls.append(list(argv or []))
        return real(argv, *a, **k)

    monkeypatch.setattr(ldr.scratch_leftovers, "main", spy)
    return calls


# --- dwe.plan / drc.env_prefix ------------------------------------------------------------


def test_plan_appends_the_pairs_after_the_pin_and_the_mode():
    env = {"CLAUDE_LAUNCHER_FORCE_PROFILE": "aris"}
    got, _, _ = dwe.plan(env, "wait", scratch=PAIRS)
    assert got == [(dwe.FORCE_PROFILE_ENV, "aris"), (dwe.LOCAL_MODE_ENV, "wait"), *PAIRS]


def test_plan_in_launcher_mode_appends_the_pairs_after_the_mode():
    got, _, _ = dwe.plan({}, "fallback", launcher=True, scratch=PAIRS)
    assert got == [(dwe.LOCAL_MODE_ENV, "fallback"), *PAIRS]


@pytest.mark.parametrize("launcher", [False, True])
@pytest.mark.parametrize("scratch", [PAIRS, None])
def test_plan_never_unsets_a_scratch_name(launcher, scratch):
    env = {"CLAUDE_LAUNCHER_OWNED": OWNED_ALL, "CLAUDE_CONFIG_DIR": "/x"}
    _, unset, _ = dwe.plan(env, None, launcher=launcher, scratch=scratch)
    assert not set(NAMES) & set(unset)
    assert "TP_LOCAL" in unset or launcher  # the owned list is still read in plain mode
    assert set(NAMES) <= dwe.NEVER_UNSET


@pytest.mark.parametrize("launcher", [False, True])
@pytest.mark.parametrize("mode", [None, "wait"])
def test_plan_without_scratch_is_todays(launcher, mode):
    env = {"CLAUDE_LAUNCHER_FORCE_PROFILE": "aris", "CLAUDE_LAUNCHER_OWNED": "TP_LOCAL,A_VAR"}
    assert dwe.plan(env, mode, launcher, scratch=None) == dwe.plan(env, mode, launcher)
    assert dwe.plan(env, mode, launcher, scratch=()) == dwe.plan(env, mode, launcher)


def test_env_prefix_puts_the_pairs_last():
    got = drc.env_prefix("/p", "R=1", extra_env=[("A", "b")], unset=["Z"],
                         scratch=[("TMPDIR", "/w x/run")])
    assert got == ("env -u CLAUDE_CODE_EFFORT_LEVEL -u Z TP_DESIGN_RUN=1 R=1 "
                   "CLAUDE_CONFIG_DIR=/p A=b TMPDIR='/w x/run' ")


def test_env_prefix_without_scratch_is_todays():
    want = "env -u CLAUDE_CODE_EFFORT_LEVEL TP_DESIGN_RUN=1 CLAUDE_CONFIG_DIR=/p "
    assert drc.env_prefix("/p") == drc.env_prefix("/p", scratch=None) == want


# --- design_run_launch_plan.build -----------------------------------------------------------


def test_build_computes_the_pairs_from_the_worktree():
    p = lp.build({}, {}, False, "wait", WT, scratch=True)
    assert p.extra_env == [(dwe.LOCAL_MODE_ENV, "wait"), *PAIRS]
    assert not set(NAMES) & set(p.unset)
    assert lp.build({}, {}, False, None, WT).extra_env == []  # off unless asked


def test_build_with_a_launcher_keeps_the_pairs_and_unsets_none_of_them(monkeypatch):
    monkeypatch.setattr(lp.launcher_which, "launcher_home", lambda env: "/launcher")
    env = {"CLAUDE_LAUNCHER_OWNED": OWNED_ALL}
    p = lp.build(env, {}, False, None, WT, home="/h", scratch=True,
                 which=lambda cwd, e: {"profile": "aris"})
    assert p.extra_env == PAIRS and not set(NAMES) & set(p.unset)
    assert "CLAUDE_CONFIG_DIR" in p.unset  # the launcher scrub is still in force


# --- launch_design_run.main -----------------------------------------------------------------


def test_a_real_launch_provisions_once_before_the_command_and_carries_the_pairs(
        srig, monkeypatch):
    calls = _spy_provision(monkeypatch)
    seen = []
    real = drc.window_command
    monkeypatch.setattr(drc, "window_command",
                        lambda *a, **k: (seen.append((a[1], len(calls))), real(*a, **k))[1])
    assert _run(srig, ["foo", "--skip-design"]) == 0
    assert [c[0] for c in calls] == ["provision"] and "foo" in calls[0]
    assert srig["wt"] in calls[0]
    assert seen[-1] == (srig["wt"], 1)  # the real command was built after the one provision
    run = run_scratch.run_dir(srig["wt"])
    assert stat.S_IMODE(os.stat(run).st_mode) == 0o700 and os.path.isfile(_baseline(srig))
    logged = srig["log"].read_text(encoding="utf-8").splitlines()
    want = drc.window_command("foo", srig["wt"], skip_design=True, config_dir=srig["cfg"],
                              extra_env=REAL_PAIRS(srig["wt"], {}))
    assert want in logged
    assert want.index("CLAUDE_CONFIG_DIR=") < want.index(f"TMPDIR={run} ")


def test_dry_run_prints_the_pairs_but_does_not_provision(srig, capsys, monkeypatch):
    calls = _spy_provision(monkeypatch)
    assert _run(srig, ["foo", "--dry-run"]) == 0
    line = capsys.readouterr().out.strip().splitlines()[-1]
    run = run_scratch.run_dir(srig["wt"])
    assert f"TMPDIR={run} " in line and f"UV_CACHE_DIR={run}/uv " in line
    assert calls == [] and not os.path.exists(run) and not os.path.exists(_baseline(srig))


@pytest.mark.parametrize("how", ["exit-1", "oserror"])
def test_a_provision_failure_adds_one_note_and_drops_the_pairs(srig, capsys, monkeypatch, how):
    def broken(argv=None, *a, **k):
        if how == "oserror":
            raise OSError("read-only file system")
        print("scratch-leftover: cannot create run dir")
        return 1

    monkeypatch.setattr(ldr.scratch_leftovers, "main", broken)
    assert _run(srig, ["foo", "--skip-design"]) == 0
    err = capsys.readouterr().err
    notes = [ln for ln in err.splitlines() if "provision" in ln and "scratch" in ln]
    assert len(notes) == 1 and "TMPDIR" in notes[0]
    logged = srig["log"].read_text(encoding="utf-8").splitlines()
    assert drc.window_command("foo", srig["wt"], skip_design=True, config_dir=srig["cfg"]) in logged
    assert "TMPDIR=" not in srig["log"].read_text(encoding="utf-8")


def test_resume_builds_the_same_pairs_for_the_same_worktree(srig, monkeypatch, capsys):
    _two(srig)
    calls = _spy_provision(monkeypatch)
    pairs = REAL_PAIRS(srig["wt"], {})
    want = drc.resume_window_command("foo", srig["wt"], SID_NEW, config_dir=srig["cfg"],
                                     extra_env=pairs)
    assert _run(srig, ["foo", "--resume", "--dry-run"]) == 0
    assert capsys.readouterr().out.strip().splitlines()[-1] == want and calls == []
    assert _run(srig, ["foo", "--resume", "--wait", "0"]) == 0
    assert want in srig["log"].read_text(encoding="utf-8").splitlines()
    assert [c[0] for c in calls] == ["provision"] and os.path.isfile(_baseline(srig))


def test_base_sync_creates_the_run_dir_but_never_recreates_a_pruned_worktree(srig, capsys):
    run = run_scratch.run_dir(srig["wt"])
    assert _run(srig, ["foo", "--base-sync"]) == 0 and os.path.isdir(run)
    shutil.rmtree(srig["wt"])  # registered with git, directory gone (not yet pruned)
    assert _run(srig, ["foo", "--base-sync"]) == 0
    assert not os.path.exists(srig["wt"]), "an empty dir was recreated at the pruned worktree"
    assert capsys.readouterr().out.strip()
