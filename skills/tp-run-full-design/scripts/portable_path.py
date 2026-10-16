"""Turn a host path into the form a committed artifact may carry.

Runtime callers keep absolute paths (``run_tier_3_5.py`` requires one so
``cleanup_worker_worktree`` can never target the repo itself). Two committed
writers pass host paths through :func:`portable_path` first:
``write_candidate_artifacts`` (top-level path values in ``telemetry.json``)
and ``cleanup_worker_worktree`` (the ``worktree-cleanup-locked`` line in
``decisions.md``). Other committed output (e.g. ``test-results.json``'s raw
test text, nested values) is not scrubbed. The forms:

- a path inside the anchor repo -> its POSIX path relative to that repo;
- anything else (or no anchor)   -> ``outside-repo:<basename>`` — one-way,
  keeps the agent id for debugging, drops the tree above it, and has no
  ``<``/``>`` so a markdown render of ``decisions.md`` shows it.

Never raises: a logging path must not turn a successful step into an error.
"""
from __future__ import annotations

import os
from pathlib import Path, PurePath

OUTSIDE_MARKER = "outside-repo"
_UNNAMED = {"", ".", ".."}
_ERRORS = (OSError, ValueError, RuntimeError, TypeError)


def find_anchor(start: str | os.PathLike) -> Path | None:
    """Nearest ancestor of ``start`` (inclusive) holding a ``.git`` dir or file."""
    try:
        here = Path(start).resolve(strict=False)
        for candidate in (here, *here.parents):
            if (candidate / ".git").exists():
                return candidate
    except _ERRORS:
        pass
    return None


def is_abs_path_str(value: object) -> bool:
    """True only for a non-empty ``str`` that is an absolute path."""
    return isinstance(value, str) and bool(value) and os.path.isabs(value)


def portable_path(path: str | os.PathLike, anchor: str | os.PathLike | None) -> str:
    """``path`` relative to ``anchor`` when strictly inside it, else the marker.

    The anchor itself also gets the marker: a bare ``.`` would drop the name
    the record exists to keep.
    """
    try:
        name = PurePath(path).name
    except _ERRORS:
        name = ""
    marker = f"{OUTSIDE_MARKER}:{'unknown' if name in _UNNAMED else name}"
    if anchor is None:
        return marker
    try:
        rel = Path(path).resolve(strict=False).relative_to(
            Path(anchor).resolve(strict=False)
        )
    except _ERRORS:
        return marker
    return rel.as_posix() if rel.parts else marker
