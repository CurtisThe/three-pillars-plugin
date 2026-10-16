"""design_run_window_env.py — what a design-run window sets and unsets beyond the marker.

design: design-run-launch-fixes (Task 1.1)

`launch_design_run.py` runs in the seat's env, which its own Homelab launcher
planned for the seat's folder. The run's window must not inherit that route:

- `--local-mode M` exports `TP_LOCAL_MODE=M` (wait / fallback / exclusive), so a
  seat that cannot set the tmux global env can still ask for wait mode.
- With no launcher on the run (`launcher=False`, the default) the seat's profile
  is pinned as `CLAUDE_LAUNCHER_FORCE_PROFILE=<name>`: taken from the launching
  env, else derived from a launcher-owned `CLAUDE_CONFIG_DIR=…/.claude-profiles/<name>`.
  With a launcher (`launcher=True`) nothing is pinned and the unset list is every
  `launcher_which.SCRUB_NAMES` name plus every owned name, whatever the seat's env
  carries; `CLAUDE_LAUNCHER_ROLE` is unset too because the command applies its
  own role after the unsets.
- Every name in `CLAUDE_LAUNCHER_OWNED` is unset (`env -u`) so the run's own
  launcher plans from the worktree folder. Only shell names are kept (anything
  else is dropped with one note, so a hostile token never reaches the command),
  and never PATH/HOME or a name the window command sets itself.

`plan` returns `(assignments, unset_keys, notes)`; `design_run_command.env_prefix`
renders them. An env without the launcher and no `--local-mode` plans nothing,
so the command is unchanged. Stdlib only; no side effect.
"""
from __future__ import annotations

import os
import re
from typing import List, Mapping, Optional, Tuple

from launcher_env import OWNED_ENV, owned_keys
from launcher_which import SCRUB_NAMES

LOCAL_MODE_ENV = "TP_LOCAL_MODE"
LOCAL_MODES = ("wait", "fallback", "exclusive")
FORCE_PROFILE_ENV = "CLAUDE_LAUNCHER_FORCE_PROFILE"
CONFIG_DIR_ENV = "CLAUDE_CONFIG_DIR"
PROFILES_DIR = ".claude-profiles"
# The names the window command sets itself, plus the two a shell cannot lose.
NEVER_UNSET = frozenset({"CLAUDE_LAUNCHER_ROLE", CONFIG_DIR_ENV, FORCE_PROFILE_ENV,
                         LOCAL_MODE_ENV, "TP_DESIGN_RUN", "PATH", "HOME"})
_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def profile_name(env: Mapping[str, str]) -> Optional[str]:
    """The seat's profile name: `CLAUDE_LAUNCHER_FORCE_PROFILE`, else the last
    part of a launcher-owned `CLAUDE_CONFIG_DIR` whose parent is `.claude-profiles`,
    else None (an operator-set or other config dir derives nothing)."""
    forced = str(env.get(FORCE_PROFILE_ENV, "")).strip()
    if forced:
        return forced
    cfg = str(env.get(CONFIG_DIR_ENV, "")).strip()
    if not cfg or CONFIG_DIR_ENV not in owned_keys(env):
        return None
    path = os.path.normpath(cfg)
    if os.path.basename(os.path.dirname(path)) != PROFILES_DIR:
        return None
    return os.path.basename(path) or None


def plan(env: Mapping[str, str], local_mode: Optional[str] = None, launcher: bool = False
         ) -> Tuple[List[Tuple[str, str]], List[str], List[str]]:
    """`(assignments, unset_keys, notes)` for the run's window. `assignments` are
    `(name, value)` pairs (profile pin first, then `TP_LOCAL_MODE`); `unset_keys`
    is sorted and deduped; `notes` holds at most one line about dropped tokens.
    `ValueError` for a `local_mode` outside `LOCAL_MODES`."""
    if local_mode is not None and local_mode not in LOCAL_MODES:
        raise ValueError(f"invalid local mode {local_mode!r}; allowed: {' '.join(LOCAL_MODES)}")
    assignments: List[Tuple[str, str]] = []
    profile = None if launcher else profile_name(env)
    if profile:
        assignments.append((FORCE_PROFILE_ENV, profile))
    if local_mode:
        assignments.append((LOCAL_MODE_ENV, local_mode))
    owned = owned_keys(env)
    bad = sorted(name for name in owned if not _NAME_RE.match(name))
    if launcher:
        keep = frozenset({LOCAL_MODE_ENV, "TP_DESIGN_RUN", "PATH", "HOME"})
        unset = sorted(n for n in set(SCRUB_NAMES) | set(owned) if _NAME_RE.match(n) and n not in keep)
    else:
        unset = sorted(name for name in owned if _NAME_RE.match(name) and name not in NEVER_UNSET)
    notes = []
    if bad:
        notes.append(f"note: {OWNED_ENV} lists {len(bad)} entr{'y' if len(bad) == 1 else 'ies'} "
                     f"that are not shell names; not unset in the run's window: "
                     f"{', '.join(repr(name) for name in bad)}")
    return assignments, unset, notes
