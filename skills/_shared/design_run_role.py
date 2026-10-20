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
import re
import shlex
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import launcher_which  # noqa: E402

__all__ = ["RUN_ROLE", "SEAT_ROLE", "ROLE_ENV", "assignment", "remote_control_args"]

RUN_ROLE = "run"
SEAT_ROLE = "seat"
ROLE_ENV = "CLAUDE_LAUNCHER_ROLE"
_SLUG_RE = re.compile(r"^[a-z0-9-]+$")


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


def remote_control_args(slug: str, backend_env: str) -> str:
    """`--remote-control=<slug> ` when `backend_env` assigns the launcher role, else "".

    A role launch (`CLAUDE_LAUNCHER_ROLE=<any value>`: the launcher's
    `REMOTE_CONTROL_BY_ROLE` is `{seat: True, run: True}`) turns Remote Control on, and an
    unnamed entry registers under a hash in the seat's picker. The `=` form carries the slug
    as its name, so the run's entry reads as the design. A bare `--remote-control` would let
    the launcher's own guard add a nameless one, and a non-role `backend_env` (a routed
    launch, plain `claude`) turns nothing on, so it adds nothing. The flag rides with its
    trailing space so the caller inlines it straight into the command."""
    if not any(w.startswith(f"{ROLE_ENV}=") for w in backend_env.split()):
        return ""
    if not isinstance(slug, str) or not _SLUG_RE.match(slug):
        raise ValueError(f"invalid design slug {slug!r}; must match [a-z0-9-]+")
    return f"--remote-control={shlex.quote(slug)} "
