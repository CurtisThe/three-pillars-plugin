#!/usr/bin/env python3
"""design_run_launch_plan.py — one pure plan for a design run's role, env scrub and profile.

launch-role-precedence task 1.4. `build` composes `design_run_backend.resolve`,
`design_run_role.assignment`, `design_run_window_env.plan` and `launcher_which`.

With a launcher on PATH the run's own launcher plans from the worktree: the command assigns no
`CLAUDE_CONFIG_DIR`, every launcher name is unset, and the profile pretrust and the MCP read is
the worktree's route profile (never the seat's). With no launcher (nothing on PATH, or a plain
`claude`) nothing could route the run, so today's behaviour holds: the seat's `CLAUDE_CONFIG_DIR`
passes through, with the old profile pin and the old scrub of the owned names (and the old
warning when that is unset; the default profile is still pre-trusted). With a launcher whose answer
names no profile, `pretrust` is False: the run starts untrusted rather than trusting a guess.
No side effect beyond the injected `which`. Stdlib only.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import design_run_backend  # noqa: E402
import design_run_command as drc  # noqa: E402
import design_run_role  # noqa: E402
import design_run_window_env as dwe  # noqa: E402
import launcher_which  # noqa: E402
import run_scratch  # noqa: E402

__all__ = ["LaunchPlan", "build"]


@dataclass
class LaunchPlan:
    backend_env: str = ""
    extra_env: list = field(default_factory=list)  # (name, value) pairs
    unset: list = field(default_factory=list)
    profile_dir: object = None  # what pretrust and the MCP read use
    command_config_dir: object = None  # what the command assigns
    notes: list = field(default_factory=list)
    pretrust: bool = True  # False: a launcher run whose route profile is unknown


def build(env, cfg, direct, local_mode, worktree, home=None, which=launcher_which.which,
          scratch=False) -> LaunchPlan:
    """The plan for one launch. `direct` is the CLI flag; `home` is the HOME directory.
    A true `scratch` adds the run's TMPDIR and cache pairs (`run_scratch.env_pairs` of the
    worktree) after the other pairs; `main` passes it once the worktree is provisioned."""
    launcher = launcher_which.launcher_home(env)
    is_direct = design_run_backend.resolve(cfg, direct) == "direct"
    plan = LaunchPlan()
    pairs = run_scratch.env_pairs(worktree, env) if scratch else None
    plan.extra_env, plan.unset, plan.notes = dwe.plan(
        env, local_mode, launcher=launcher is not None, scratch=pairs)
    if is_direct or launcher is None:
        plan.backend_env, note = design_run_role.assignment(is_direct, launcher)
        if note:
            plan.notes.append(note)
    if launcher is None:
        plan.command_config_dir = plan.profile_dir = env.get("CLAUDE_CONFIG_DIR") or None
        if plan.command_config_dir is None:
            plan.notes.append(drc.resolve_config_dir(env)[1])
        return plan
    answer = which(worktree, env)
    profile = (answer or {}).get("profile")
    if profile:
        base = Path(home) if home else Path(env.get("HOME") or Path.home())
        plan.profile_dir = base / dwe.PROFILES_DIR / profile
    else:
        plan.pretrust = False
        plan.notes.append("note: could not determine the run's route profile; skipping pretrust")
    return plan
