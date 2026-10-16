"""Tests for the design-run window env (design-run-launch-fixes Task 1.1).

`design_run_window_env.plan(env, local_mode)` decides what the run's window
command sets and unsets beyond the marker: `TP_LOCAL_MODE` from `--local-mode`,
the seat's profile pinned as `CLAUDE_LAUNCHER_FORCE_PROFILE`, and every
launcher-owned name of the seat's env unset so the run's own launcher plans
from the worktree folder. Assertions read the command's env words through
`shlex` (structure, not wording; test-fragility.md section 1). The launcher
cases reuse `test_launch_design_run.py`'s hermetic rig.
"""
from __future__ import annotations

import os
import re
import shlex
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import design_run_command as drc  # noqa: E402
import design_run_window_env as dwe  # noqa: E402
from test_launch_design_run import _run, _trusted, rig  # noqa: F401,E402
from test_launch_design_run_roles import fake_launcher  # noqa: E402

NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# The names the window command sets itself (the spec's fixed list), plus PATH/HOME.
NEVER_UNSET = {"CLAUDE_LAUNCHER_ROLE", "CLAUDE_CONFIG_DIR", "CLAUDE_LAUNCHER_FORCE_PROFILE",
               "TP_LOCAL_MODE", "TP_DESIGN_RUN", "PATH", "HOME"}


def _words(cmd):
    """The `env …` words between `cd <wt> &&` and `claude`."""
    return shlex.split(cmd.split(" && ", 1)[1].split(" claude ", 1)[0])


def _unsets(words):
    return [words[i + 1] for i, w in enumerate(words) if w == "-u"]


def _assigns(words):
    return dict(w.split("=", 1) for w in words if "=" in w)


def _last(rig_, capsys, argv, **env_over):
    """(dry-run command = last stdout line, stderr) for `argv` with env overrides."""
    assert _run(rig_, ["foo", *argv, "--dry-run"], **env_over) == 0
    cap = capsys.readouterr()
    return cap.out.strip().splitlines()[-1], cap.err


# --- (a) --local-mode ---------------------------------------------------------------

@pytest.mark.parametrize("mode", ["wait", "fallback", "exclusive"])
def test_local_mode_is_exported_into_the_window(rig, capsys, mode):
    cmd, _ = _last(rig, capsys, ["--local-mode", mode])
    assert _assigns(_words(cmd))["TP_LOCAL_MODE"] == mode


def test_an_unknown_local_mode_is_a_usage_error_with_no_side_effect(rig, capsys):
    with pytest.raises(SystemExit) as exc:
        _run(rig, ["foo", "--local-mode", "sometimes"])
    assert exc.value.code == 2
    assert not rig["log"].exists()  # tmux never called
    assert _trusted(rig) is None  # worktree never pre-trusted
    assert not (Path(rig["wt"]) / "three-pillars-docs").exists()  # no brief written


def test_the_module_refuses_an_unknown_local_mode():
    with pytest.raises(ValueError):
        dwe.plan({}, "sometimes")


def test_no_local_mode_adds_nothing(rig, capsys):
    cmd, _ = _last(rig, capsys, [])
    assert "TP_LOCAL_MODE" not in _assigns(_words(cmd))
    assert dwe.plan({}, None) == ([], [], [])


def test_with_no_extras_the_command_is_unchanged(rig, capsys):
    cmd, _ = _last(rig, capsys, [])
    assert cmd == drc.window_command("foo", rig["wt"], config_dir=rig["cfg"])
    assert drc.env_prefix("/p", extra_env=[], unset=[]) == drc.env_prefix("/p")


# --- (b) the seat's profile is pinned -------------------------------------------------

def test_force_profile_in_the_launching_env_is_pinned(rig, capsys):
    cmd, _ = _last(rig, capsys, [], CLAUDE_LAUNCHER_FORCE_PROFILE="aris")
    assert _assigns(_words(cmd))["CLAUDE_LAUNCHER_FORCE_PROFILE"] == "aris"


def test_an_owned_profile_config_dir_derives_the_profile_name(rig, capsys, tmp_path):
    prof = tmp_path / "home" / ".claude-profiles" / "aris"
    prof.mkdir(parents=True)
    cmd, _ = _last(rig, capsys, [], CLAUDE_CONFIG_DIR=str(prof),
                   CLAUDE_LAUNCHER_OWNED="CLAUDE_CONFIG_DIR,TP_LOCAL")
    assert _assigns(_words(cmd))["CLAUDE_LAUNCHER_FORCE_PROFILE"] == "aris"


def test_the_derived_name_ignores_a_trailing_slash():
    env = {"CLAUDE_CONFIG_DIR": "/h/.claude-profiles/aris/",
           "CLAUDE_LAUNCHER_OWNED": "CLAUDE_CONFIG_DIR"}
    assert ("CLAUDE_LAUNCHER_FORCE_PROFILE", "aris") in dwe.plan(env)[0]


def test_an_explicit_force_profile_wins_over_the_derived_one():
    env = {"CLAUDE_LAUNCHER_FORCE_PROFILE": "ripley",
           "CLAUDE_CONFIG_DIR": "/h/.claude-profiles/aris",
           "CLAUDE_LAUNCHER_OWNED": "CLAUDE_CONFIG_DIR"}
    pinned = [v for k, v in dwe.plan(env)[0] if k == "CLAUDE_LAUNCHER_FORCE_PROFILE"]
    assert pinned == ["ripley"]


@pytest.mark.parametrize("cfg_dir", ["/h/.claude", "/h/profiles/aris",
                                     "/h/.claude-profiles/aris/sub", "/h/.claude-profiles"])
def test_a_config_dir_outside_claude_profiles_derives_nothing(cfg_dir):
    env = {"CLAUDE_CONFIG_DIR": cfg_dir, "CLAUDE_LAUNCHER_OWNED": "CLAUDE_CONFIG_DIR"}
    assert "CLAUDE_LAUNCHER_FORCE_PROFILE" not in dict(dwe.plan(env)[0])


def test_a_config_dir_outside_claude_profiles_derives_nothing_at_launch(rig, capsys):
    cmd, _ = _last(rig, capsys, [], CLAUDE_LAUNCHER_OWNED="CLAUDE_CONFIG_DIR")
    assert "CLAUDE_LAUNCHER_FORCE_PROFILE" not in _assigns(_words(cmd))


# --- (c) launcher-owned names are unset -----------------------------------------------

def test_owned_names_are_unset_before_every_assignment(rig, capsys):
    cmd, _ = _last(rig, capsys, ["--local-mode", "wait"],
                   CLAUDE_LAUNCHER_FORCE_PROFILE="aris",
                   CLAUDE_LAUNCHER_OWNED="TP_LOCAL,CLAUDE_LAUNCHER_BACKEND ANTHROPIC_BASE_URL")
    words = _words(cmd)
    unset = _unsets(words)
    assert {"TP_LOCAL", "CLAUDE_LAUNCHER_BACKEND", "ANTHROPIC_BASE_URL"} <= set(unset)
    last_u = max(i for i, w in enumerate(words) if w == "-u")
    first_assign = min(i for i, w in enumerate(words) if "=" in w)
    assert last_u < first_assign


def test_unset_keys_are_sorted_and_deduped():
    _, unset, _ = dwe.plan({"CLAUDE_LAUNCHER_OWNED": "TP_LOCAL,B_VAR TP_LOCAL:A_VAR"})
    assert unset == sorted(set(unset))
    assert set(unset) == {"TP_LOCAL", "B_VAR", "A_VAR"}


def test_path_home_and_the_commands_own_names_are_never_unset(rig, capsys):
    owned = ",".join(sorted(NEVER_UNSET | {"TP_LOCAL"}))
    cmd, _ = _last(rig, capsys, ["--local-mode", "wait"], CLAUDE_LAUNCHER_OWNED=owned)
    unset = set(_unsets(_words(cmd)))
    assert "TP_LOCAL" in unset
    assert not unset & NEVER_UNSET
    assert not set(dwe.plan({"CLAUDE_LAUNCHER_OWNED": owned})[1]) & NEVER_UNSET


def test_an_owned_effort_pin_is_unset_once(rig, capsys):
    cmd, _ = _last(rig, capsys, [], CLAUDE_LAUNCHER_OWNED="CLAUDE_CODE_EFFORT_LEVEL,TP_LOCAL")
    assert _unsets(_words(cmd)).count("CLAUDE_CODE_EFFORT_LEVEL") == 1


# --- (d) the owned config dir survives only when no launcher can route the run --------

OWNED_ROLE = "CLAUDE_CONFIG_DIR,CLAUDE_LAUNCHER_ROLE,TP_LOCAL"


def test_without_a_launcher_the_owned_config_dir_is_kept_and_no_role_is_set(rig, capsys):
    cmd, _ = _last(rig, capsys, ["--direct"], CLAUDE_LAUNCHER_OWNED=OWNED_ROLE)
    words = _words(cmd)
    assigns = _assigns(words)
    assert "CLAUDE_LAUNCHER_ROLE" not in assigns  # nothing would honour it
    assert assigns["CLAUDE_CONFIG_DIR"] == rig["cfg"]
    assert not {"CLAUDE_CONFIG_DIR", "CLAUDE_LAUNCHER_ROLE"} & set(_unsets(words))
    assert "TP_LOCAL" in _unsets(words)


def test_with_a_launcher_the_run_role_is_set_and_the_owned_config_dir_unset(rig, capsys, tmp_path):
    # launch-role-precedence 1.5: the run's own launcher plans from the worktree, so the
    # seat's profile is unset (never assigned) and the role is assigned after the unsets.
    path = fake_launcher(tmp_path) + os.pathsep + rig["env"]["PATH"]
    cmd, _ = _last(rig, capsys, ["--direct"], CLAUDE_LAUNCHER_OWNED=OWNED_ROLE, PATH=path)
    words = _words(cmd)
    assigns = _assigns(words)
    assert assigns["CLAUDE_LAUNCHER_ROLE"] == "run"
    assert "CLAUDE_CONFIG_DIR" not in assigns
    assert {"CLAUDE_CONFIG_DIR", "TP_LOCAL"} <= set(_unsets(words))


# --- (e) a hostile owned token never reaches the command ------------------------------

@pytest.mark.parametrize("bad", ["X;rm", "1BAD", "A$(id)", "B`id`", "C-D", "E=F", "'G'"])
def test_a_hostile_owned_token_never_reaches_the_command(rig, capsys, bad):
    cmd, _ = _last(rig, capsys, [], CLAUDE_LAUNCHER_OWNED=f"TP_LOCAL,{bad}")
    assert bad not in cmd
    words = _words(cmd)
    assert all(NAME_RE.match(name) for name in _unsets(words))
    assert "TP_LOCAL" in _unsets(words)


def test_non_name_tokens_are_dropped_with_one_note(rig, capsys):
    _, err = _last(rig, capsys, [], CLAUDE_LAUNCHER_OWNED="TP_LOCAL,X;rm,1BAD")
    _, unset, notes = dwe.plan({"CLAUDE_LAUNCHER_OWNED": "TP_LOCAL,X;rm,1BAD"})
    assert unset == ["TP_LOCAL"]
    assert len(notes) == 1
    assert sum(1 for ln in err.splitlines() if ln == notes[0]) == 1


def test_an_unowned_env_plans_nothing_to_unset():
    env = {"TP_LOCAL": "off", "PATH": "/bin", "HOME": "/h", "CLAUDE_CONFIG_DIR": "/h/x"}
    assert dwe.plan(env) == ([], [], [])


def test_the_launching_env_is_not_mutated():
    env = {"CLAUDE_LAUNCHER_OWNED": "TP_LOCAL", "TP_LOCAL": "off",
           "CLAUDE_CONFIG_DIR": "/h/.claude-profiles/aris"}
    before = dict(env)
    dwe.plan(env, "wait")
    assert env == before


def test_rendered_values_are_shell_quoted():
    prefix = drc.env_prefix(None, extra_env=[("CLAUDE_LAUNCHER_FORCE_PROFILE", "my prof")],
                            unset=["TP_LOCAL"])
    words = shlex.split(prefix)
    assert _assigns(words)["CLAUDE_LAUNCHER_FORCE_PROFILE"] == "my prof"
    assert _unsets(words) == ["CLAUDE_CODE_EFFORT_LEVEL", "TP_LOCAL"]
    assert os.path.basename(words[0]) == "env"
