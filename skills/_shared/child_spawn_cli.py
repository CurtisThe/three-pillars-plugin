#!/usr/bin/env python3
"""child_spawn_cli.py — the argument parser of the `child_spawn.py` CLI.

design: strata-session-isolation. Split out of `child_spawn.py` (file-size cap): `child_spawn.main`
builds its parser here and dispatches each subcommand to its `cmd_*` function. Flags only — no
behaviour lives in this module. Stdlib only.
"""
from __future__ import annotations

import argparse

import wait_budget

__all__ = ["CMDS", "_parser"]

CMDS = ("probe", "smoke", "start", "wait", "stop", "sweep")


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="child_spawn.py", description=(
        "Spawn a Strata agent as a child claude session (probe/smoke/start/wait/stop/sweep)."))
    sub = ap.add_subparsers(dest="cmd", metavar="|".join(CMDS))
    probe = sub.add_parser("probe", help="can this run spawn a child? (exit 0 / 4)")
    probe.add_argument("--run", help="run id to probe and cache under "
                                     "(default $CLAUDE_CODE_SESSION_ID)")
    probe.add_argument("--root", default=".", help="repo whose child-state dir holds the cache")
    stop = sub.add_parser("stop", help="stop the child recorded in a state file (exit 0)")
    stop.add_argument("--state", required=True, help="the child state file to stop and mark")
    sweep = sub.add_parser("sweep", help="stop this run's children, or stale ones (exit 0)")
    scope = sweep.add_mutually_exclusive_group()
    scope.add_argument("--run", help="run id whose children to stop "
                                     "(default $CLAUDE_CODE_SESSION_ID)")
    scope.add_argument("--stale", action="store_true",
                       help="stop only running children past deadline_at, in any run dir")
    sweep.add_argument("--root", default=".", help="repo whose child-state dirs to sweep")
    start = sub.add_parser("start", help="spawn one child session (exit 0 / 3 failed)")
    start.add_argument("--site", required=True, help="the calling site (S1-S4), for the record")
    start.add_argument("--agent-ref", required=True,
                       help="the inner agent's reference, as agent_ref.py resolves it")
    start.add_argument("--model", required=True, help="the inner agent's model")
    start.add_argument("--prompt-file", required=True,
                       help="file holding the prompt the inner agent runs")
    start.add_argument("--cwd", default=".", help="project the child works in (default .)")
    start.add_argument("--busy-policy", choices=("wait", "fallback"),
                       help="override this run's busy policy for the child's key")
    start.add_argument("--run", help="run id to record the child under "
                                     "(default $CLAUDE_CODE_SESSION_ID)")
    wait = sub.add_parser("wait", help="poll one child to done (exit 0) or report running (exit 4) or failed (exit 3)")
    wait.add_argument("--state", required=True, help="the child state file to poll")
    wait.add_argument("--budget-s", type=float, default=wait_budget.WAIT_BUDGET_S,
                      help="seconds to poll before reporting the child still running "
                           f"(default {wait_budget.WAIT_BUDGET_S}, inside the 300 s cache TTL)")
    wait.add_argument("--reply-out", help="file for the inner agent's last text "
                                          "(default the state path with .reply.txt)")
    smoke = sub.add_parser("smoke", help="spawn one throwaway child to prove the path works "
                                         "(exit 0 / 3)")
    smoke.add_argument("--model", help="the inner agent's model (default the local alias)")
    smoke.add_argument("--cwd", default=".", help="project the smoke child works in (default .)")
    smoke.add_argument("--run", help="run id to record the smoke child under "
                                     "(default $CLAUDE_CODE_SESSION_ID)")
    return ap
