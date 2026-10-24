"""launch_roster.py — register a launched design run on the fleet roster.

`launch_design_run.main` calls `register` once after it opens a run, so the
roster knows about every run the seat starts. It runs the roster CLI's
`adopt --update <slug>` and decides success from what `adopt` printed, never
from the exit code alone: `adopt` exits 0 on every refusal (not live, no
worktree, no tmux). The CLI is found beside this directory by its file name
(`skills/*/scripts/fleet_roster.py`), so a tree without one registers nothing
and says nothing. Fail-open: the returned line is printed, the launch's exit
code never changes.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Callable, Optional

_TIMEOUT = 60


def find_cli() -> Optional[Path]:
    """The roster CLI beside `_shared`, or None when this tree has none."""
    hits = sorted(Path(__file__).resolve().parent.parent.glob("*/scripts/fleet_roster.py"))
    return hits[0] if hits else None


def _confirms(slug: str, line: str) -> bool:
    """True when `line` is one of the `adopt` lines that mean `slug` is registered."""
    return line in (f"adopted: {slug}", f"updated: {slug}") or line.startswith(f"{slug}: unchanged")


def register(slug: str, root: str, *, run: Callable = subprocess.run) -> Optional[str]:
    """Run `adopt --update <slug>`; None when confirmed (or no CLI), else a `roster:` line."""
    cli = find_cli()
    if cli is None:
        return None
    cmd = [sys.executable, str(cli), "--root", root, "adopt", "--update", slug]
    try:
        proc = run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"roster: {slug} not registered ({exc})"
    lines = [ln.strip() for ln in (proc.stdout or "").splitlines() if ln.strip()]
    if proc.returncode == 0 and any(_confirms(slug, ln) for ln in lines):
        return None
    err = [ln.strip() for ln in (getattr(proc, "stderr", "") or "").splitlines() if ln.strip()]
    why = (lines or err or [f"exit {proc.returncode}, no confirmation"])[0]
    return f"roster: {slug} not registered ({why})"
