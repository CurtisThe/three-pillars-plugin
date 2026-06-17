"""project_root.py — Resolve the project repo root via git rev-parse.

Provides find_project_root(start=None) -> Path | None.

The resolver always queries git from the invocation cwd (or an explicit start
path), never from the module's own location. This ensures gate tools read the
config of the PROJECT under operation, not the framework checkout hosting them.

Stdlib-only. Never raises — any failure (non-zero git exit, git missing,
exception) returns None so callers can fail-closed.
"""
from __future__ import annotations

import subprocess
from pathlib import Path


def find_project_root(start: "Path | None" = None) -> "Path | None":
    """Resolve the git toplevel for the repo containing `start`.

    Args:
        start: directory to begin the search. Defaults to Path.cwd() when None.

    Returns:
        The resolved absolute Path to the repo root, or None on any failure
        (not a git repo, git not installed, permission error, etc.).
    """
    try:
        cwd = Path(start) if start is not None else Path.cwd()
        result = subprocess.run(
            ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return None
        toplevel = result.stdout.strip()
        if not toplevel:
            return None
        return Path(toplevel).resolve()
    except Exception:
        return None
