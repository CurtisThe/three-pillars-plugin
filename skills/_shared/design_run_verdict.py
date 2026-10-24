"""design_run_verdict.py — what a run's frame says about a line sent into its input box.

design: fleet-watcher-reliability (Task 1.4). A run that is busy holds a typed line in its
box until the turn ends, so an unsent box does not mean the line was lost. These are pure
reads of one `capture-pane -p -e` frame (plus two booleans), used by `design_run_send.deliver`:

- `before_send(frame, line)` — judged before any key is typed. `None`: the box is empty or
  ghost text, go ahead. `queued`: the run is busy and the box already holds exactly `line`.
  `occupied`: the box holds any other text (busy or not), so a key would clear or mix it.
- `after_send(frame, *, was_busy, grew)` — judged after Enter. `queued` first (the run was
  busy and the box still holds the line, whatever the transcript did: a busy run's transcript
  grows anyway), then `delivered` (empty box, a grown transcript, or a run that turned busy);
  otherwise `None`: no evidence, keep the caller's own path.

"Busy" is `pane_activity.classify(frame).kind == "busy"`. `transcript_sizer` builds the
size seam the CLI hands to `deliver`. Stdlib only; every git and `/proc` read is injectable.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from typing import Callable, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pane_activity  # noqa: E402

__all__ = ["DELIVERED", "QUEUED", "OCCUPIED", "is_busy", "before_send", "after_send",
           "read_size", "grew", "transcript_sizer"]

DELIVERED, QUEUED, OCCUPIED = "delivered", "queued", "occupied"
_SGR = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def _box(frame: str) -> "Optional[tuple[str, bool]]":
    """`(text, ghost)` of the frame's input box, else None. Deferred import: `design_run_send`
    imports this module, so a module-level import here would be a cycle."""
    import design_run_send
    return design_run_send.box_text(frame)


def _empty(box: "Optional[tuple[str, bool]]") -> bool:
    return box is not None and (not box[0] or box[1])


def _same(a: str, b: str) -> bool:
    return " ".join(a.split()) == " ".join(b.split())


def is_busy(frame: str) -> bool:
    """True when the frame's activity is a working spinner (escape codes are ignored)."""
    return pane_activity.classify(_SGR.sub("", frame)).kind == "busy"


def before_send(frame: str, line: str) -> Optional[str]:
    """`None` for an empty/ghost box (or none found); `queued` for a busy run whose box holds
    exactly `line`; `occupied` for any other text in the box, busy or not."""
    box = _box(frame)
    if box is None or _empty(box):
        return None
    return QUEUED if is_busy(frame) and _same(box[0], line) else OCCUPIED


def after_send(frame: str, *, was_busy: bool, grew: bool) -> Optional[str]:
    """`queued` when the run was busy and the box still holds the (just typed) line; else
    `delivered` for an empty box, a grown transcript, or a run that was idle and is now busy;
    else `None`. The box was empty before typing, so any text still in it is the line."""
    box = _box(frame)
    if was_busy and box is not None and not _empty(box):
        return QUEUED
    if _empty(box) or grew or (is_busy(frame) and not was_busy):
        return DELIVERED
    return None


def read_size(size: Optional[Callable[[], Optional[int]]]) -> Optional[int]:
    """One reading of a transcript-size seam; None for no seam, no answer, or a seam that raises."""
    try:
        value = size() if size is not None else None
    except Exception:  # a probe must never take delivery down
        return None
    return value if isinstance(value, int) else None


def grew(before: Optional[int], after: Optional[int]) -> bool:
    """True when both readings exist and the transcript got bigger."""
    return before is not None and after is not None and after > before


def _git_worktree_list() -> Optional[str]:
    try:
        out = subprocess.run(["git", "worktree", "list", "--porcelain"], capture_output=True,
                             text=True, encoding="utf-8", timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout if out.returncode == 0 else None


def transcript_sizer(slug: str, runner, *,
                     listing: Callable[[], Optional[str]] = _git_worktree_list,
                     env=None, project_dir: Optional[Callable] = None
                     ) -> Optional[Callable[[], Optional[int]]]:
    """A callable giving the byte size of the newest `*.jsonl` under the run's transcript dir
    (None while there is none), or None when the dir cannot be found: no runner, no
    `tp/<slug>` worktree in `git worktree list --porcelain`, or any error. The size is read
    afresh on every call."""
    if runner is None:
        return None
    try:
        # Deferred imports: `launch_design_run` imports design_run_delivery -> design_run_send
        # -> this module: a module-level import is a cycle (context_rollover_drive does the same).
        from launch_design_run import find_worktree
        import run_config_dir
        porcelain = listing()
        worktree = find_worktree(porcelain, slug) if porcelain is not None else None
        if worktree is None:
            return None
        pdir = (project_dir or run_config_dir.project_dir)(
            slug, worktree, runner, os.environ if env is None else env)
    except Exception:  # fail-open: no seam means "not checked", never an error
        return None

    def size() -> Optional[int]:
        try:
            files = sorted(pdir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
            return files[-1].stat().st_size if files else None
        except OSError:
            return None

    return size
