"""The seat-side transcript lookups follow the run's route profile, not the seat's.

design: launch-role-precedence (PR #293 review round 1). A launched run comes up on the
profile `claude-which` names for its worktree (`design_run_launch_plan.build`), so the run
watcher (`design_run_observe.discover_session`) and the rollover drive
(`context_rollover_drive._newest_transcript`) must look there. No launcher on PATH: the
seat's `CLAUDE_CONFIG_DIR` stays the answer.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import context_rollover_drive as crd  # noqa: E402
import design_run_launch_plan as launch_plan  # noqa: E402
import design_run_observe as dro  # noqa: E402

WHICH = "#!/bin/sh\nprintf 'profile: aris\\nbackend: direct\\neffective: direct\\n'\n"
SID = "abcdef12-0000-0000-0000-000000000000"


def _launcher(tmp_path, which=WHICH):
    home = tmp_path / "launcher"
    (home / "bin").mkdir(parents=True)
    (home / "lib" / "launcher").mkdir(parents=True)
    for name, text in (("claude", "#!/bin/sh\nexit 0\n"), ("claude-which", which)):
        (home / "bin" / name).write_text(text)
        (home / "bin" / name).chmod(0o755)
    (home / "lib" / "launcher" / "plan.py").write_text("")
    (home / "lib" / "launcher" / "role.py").write_text('RUN = "run"\n')
    pdir = tmp_path / "pathdir"
    pdir.mkdir()
    (pdir / "claude").symlink_to(home / "bin" / "claude")
    return str(pdir)


def _transcript(profile: Path, wt: Path) -> None:
    proj = profile / "projects" / re.sub(r"[^A-Za-z0-9]", "-", os.path.abspath(wt))
    proj.mkdir(parents=True)
    (proj / f"{SID}.jsonl").write_text("{}\n")


def _seat(tmp_path, path_prefix=None):
    home = tmp_path / "home"
    wt = tmp_path / "repo-wt" / "foo"
    wt.mkdir(parents=True)
    path = "/usr/bin:/bin" if path_prefix is None else path_prefix + os.pathsep + "/usr/bin:/bin"
    env = {"PATH": path, "HOME": str(home),
           "CLAUDE_CONFIG_DIR": str(home / ".claude-profiles" / "personal")}
    return home, wt, env


def test_seat_side_lookup_finds_the_run_transcript_in_the_route_profile(tmp_path):
    home, wt, seat_env = _seat(tmp_path, _launcher(tmp_path))
    plan = launch_plan.build(seat_env, {}, True, None, str(wt), home=str(home))
    assert plan.command_config_dir is None  # the run's window gets no CLAUDE_CONFIG_DIR
    run_profile = Path(plan.profile_dir)    # it comes up on the worktree's route profile
    assert run_profile.name == "aris"
    _transcript(run_profile, wt)
    assert dro.project_dir(str(wt), seat_env).parent.parent == run_profile
    assert dro.discover_session(str(wt), seat_env) == "abcdef12"
    assert crd._newest_transcript(str(wt), seat_env)[0] == SID


def test_no_launcher_keeps_the_seat_profile(tmp_path):
    home, wt, seat_env = _seat(tmp_path)
    _transcript(Path(seat_env["CLAUDE_CONFIG_DIR"]), wt)
    assert dro.discover_session(str(wt), seat_env) == "abcdef12"
    assert crd._newest_transcript(str(wt), seat_env)[0] == SID


def test_launcher_without_an_answer_keeps_the_seat_profile(tmp_path):
    home, wt, seat_env = _seat(tmp_path, _launcher(tmp_path, "#!/bin/sh\nexit 1\n"))
    _transcript(Path(seat_env["CLAUDE_CONFIG_DIR"]), wt)
    assert dro.discover_session(str(wt), seat_env) == "abcdef12"
