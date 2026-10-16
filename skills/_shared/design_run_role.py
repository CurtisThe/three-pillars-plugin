#!/usr/bin/env python3
"""design_run_role.py — the explicit launcher role a design run is launched with.

launch-role-precedence task 1.2. `assignment` returns `(env_assignment, note)`. A direct
launch on a launcher that knows the `run` role gets `CLAUDE_LAUNCHER_ROLE=run`; one that lacks it
gets `seat` with a one-line fallback note; a non-direct launch gets nothing (routes.conf decides);
no launcher at all gets nothing plus one `W:` line. The role is never read from the environment.
Stdlib only.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import launcher_which  # noqa: E402

__all__ = ["RUN_ROLE", "SEAT_ROLE", "ROLE_ENV", "assignment"]

RUN_ROLE = "run"
SEAT_ROLE = "seat"
ROLE_ENV = "CLAUDE_LAUNCHER_ROLE"


def assignment(direct: bool, home, supports=launcher_which.supports_run) -> tuple[str, str]:
    """(`CLAUDE_LAUNCHER_ROLE=<role>` or "", one note line or "")."""
    if home is None:
        return "", "W: no claude-launcher found; launching with plain claude"
    if not direct:
        return "", ""
    if supports(home):
        return f"{ROLE_ENV}={RUN_ROLE}", f"launcher: using the {RUN_ROLE} role"
    return (f"{ROLE_ENV}={SEAT_ROLE}",
            f"launcher lacks the {RUN_ROLE} role; falling back to the {SEAT_ROLE} role")
