"""base_sync_window.py — the command for a base-sync window (design: one-cheap-engine 3.3).

A base-sync window is a top-level session that runs `/tp-merge-from-main <slug>`.
Under `--local` it runs on a Strata session (the local router's launcher, named
by `TP_STRATA_LAUNCHER`, default `claude-strata`); otherwise it runs on Sonnet.
The launcher chooses the engine — not seat memory (design.md Done-when 8, and
the `base_sync_window` cheap row in `cheap_classes`).

Pure builder: `window_command(slug, worktree, *, local, which)` returns
`(command, notes)`. `which` is an injected PATH probe (`shutil.which`-shaped) so
callers and tests decide whether the Strata launcher exists. No subprocess, no
side effect; the pre-trust it emits is a shell line the caller runs.
"""
from __future__ import annotations

import os
import re
import shlex
from typing import Callable, List, Optional, Sequence, Tuple

import design_run_command as drc

# The default Strata-session launcher name; `TP_STRATA_LAUNCHER` overrides it.
STRATA_LAUNCHER = "claude-strata"
SLASH = "/tp-merge-from-main"
_SLUG_RE = re.compile(r"^[a-z0-9-]+$")


def strata_launcher(env: Optional[Sequence[str]] = None) -> str:
    """The Strata-session launcher name: `TP_STRATA_LAUNCHER`, else STRATA_LAUNCHER."""
    if env is None:
        env = os.environ
    return (env.get("TP_STRATA_LAUNCHER") or "").strip() or STRATA_LAUNCHER


def slash_command(slug: str) -> str:
    """The `/tp-merge-from-main` invocation typed into the new session."""
    if not isinstance(slug, str) or not _SLUG_RE.match(slug):
        raise ValueError(f"invalid design slug {slug!r}; must match [a-z0-9-]+")
    return f"{SLASH} {slug}"


def window_command(
    slug: str,
    worktree: str,
    *,
    local: bool,
    which: Callable[[str], Optional[str]],
) -> Tuple[str, List[str]]:
    """`(command, notes)` for a base-sync window on `slug` in `worktree`.

    `local` and a Strata launcher on PATH -> a Strata session. Anything else ->
    `claude --model sonnet`; the `--local`-without-a-launcher case (M51) adds
    exactly one note line explaining the fallback.
    """
    slash = slash_command(slug)
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR") or None
    notes: List[str] = []
    name = strata_launcher()
    session = None
    if local and which(name):
        session = f"{shlex.quote(name)} {shlex.quote(slash)}"
    elif local:
        notes.append(f"note: no Strata session launcher ({name}) on PATH; "
                     f"the base-sync window opens on sonnet instead")
    if session is None:
        session = (f"{drc.env_prefix(config_dir)}claude --model sonnet "
                   f"{shlex.quote(slash)}")
    cmd = (f"cd {shlex.quote(worktree)} && "
           f"{drc.pretrust_shell_line(worktree, config_dir)} && {session}; exec bash")
    return cmd, notes
