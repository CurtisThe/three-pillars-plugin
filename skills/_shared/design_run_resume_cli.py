"""design_run_resume_cli.py — what `launch_design_run.py --resume` and `--list-resumable` run.

design: fleet-windows-reboot-resume (Task 1.5). The launcher parses the flags and builds the
launch plan; the two entry points here take it from there, so the launcher keeps no resume
logic of its own:

- `resume` builds the window command for a session id (`design_run_command.resume_window_command`,
  carrying the plan's profile, backend, MCP and env) and hands over to `design_run_resume_run`.
  Under `--dry-run` it only resolves the session and prints that command. Neither path writes
  the seat brief, logs a fable notice or types the fresh `/tp-run-full-design` line.
- `list_resumable` reads `git worktree list --porcelain` for the `tp/*` worktrees and prints the
  ones a reboot left without a run. It has no slug and is read-only.

A missing `tmux` binary never falls through to the default server: no run is live without one.
Nothing here signals a process. Stdlib plus its `_shared` siblings.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from typing import Mapping, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import design_run_command as drc  # noqa: E402
import design_run_resume as drr  # noqa: E402
import design_run_resume_run as rr  # noqa: E402
import design_run_tmux as drt  # noqa: E402

__all__ = ["probe", "tp_worktrees", "list_resumable", "resume"]

_BRANCH = "branch refs/heads/tp/"


def probe(env: Mapping[str, str]) -> Optional[drt.Runner]:
    """A tmux runner for the `tmux` on `env`'s PATH, else None."""
    tmux = shutil.which("tmux", path=env.get("PATH"))
    return drt.subprocess_runner(tmux) if tmux else None


def tp_worktrees(porcelain: str) -> "list[tuple[str, str]]":
    """`(slug, path)` for each worktree checked out on a `tp/<slug>` branch."""
    rows, path = [], None
    for line in porcelain.splitlines():
        if line.startswith("worktree "):
            path = line[len("worktree "):]
        elif line.startswith(_BRANCH) and path:
            rows.append((line[len(_BRANCH):], path))
    return rows


def list_resumable(env: Mapping[str, str], cwd: Optional[str] = None) -> int:
    """`--list-resumable`: print the `tp/*` worktrees a reboot left without a run; 0 or 2."""
    listing = subprocess.run(["git", "worktree", "list", "--porcelain"], cwd=cwd,
                             capture_output=True, text=True, encoding="utf-8")
    if listing.returncode != 0:
        print(f"error: git worktree list failed: {listing.stderr.strip()}", file=sys.stderr)
        return 2
    runner = probe(env) or (lambda args: (1, ""))  # no tmux: no run is live
    return rr.list_resumable(tp_worktrees(listing.stdout), env, runner=runner)


def resume(args, wt: str, env: Mapping[str, str], plan, mcp_args: str, model: str,
           configured: Optional[str]) -> int:
    """`--resume`: put `args.slug`'s run back on its newest (or `--session`) conversation.

    `plan` is `design_run_launch_plan.build`'s result; `mcp_args` the MCP allow-list argv."""
    def build(sid: str) -> str:
        return drc.resume_window_command(
            args.slug, wt, sid, config_dir=plan.command_config_dir, model=model,
            configured=configured, backend_env=plan.backend_env, mcp=mcp_args,
            extra_env=plan.extra_env, unset=plan.unset)

    if args.dry_run:
        try:
            sid, _ = drr.resolve_session(wt, env, args.session)
            cmd = build(sid)
        except ValueError as exc:  # no such session (ResumeError), or an unusable sid / model
            print(exc, file=sys.stderr)
            return 2
        print(f"would resume {args.slug}: session {sid}")
        print(cmd)  # last, so callers can take the final line as the command
        return 0
    try:  # fail-open: the worktree was trusted when the run began
        if plan.pretrust:
            drc.pretrust(wt, plan.profile_dir)
    except (OSError, ValueError) as exc:
        print(f"warning: could not pre-trust worktree: {exc}", file=sys.stderr)
    tmux = probe(env)
    return rr.resume(args.slug, wt, session=args.session, wait=args.wait, env=env,
                     cmd_builder=build, runner=tmux if env.get("TMUX") else None, probe=tmux)
