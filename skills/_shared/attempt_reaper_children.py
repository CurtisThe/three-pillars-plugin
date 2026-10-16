#!/usr/bin/env python3
"""attempt_reaper_children.py — is a child-session attempt of this design still running?

design: reaper-false-worker-done. A Strata attempt runs as a child `claude -p` session
(`child_spawn.py start`), so `sweep` (armed ladder states read through the worker's own
transcript) can miss it, and a tp-worker's end of turn then reads as the worker's end.
`live_child` is the second question `watch` asks before it calls the worker done: does any
child state file of this design still say `running` with its recorded pid alive (start-ticks
check through `child_proc.alive`, never a name match)?

The state dirs live under the git common dir, beside the ladder dir
(`<common>/tp-ladder/<slug>` -> `<common>/tp-children/<run8>/*.json`); a child is this design's
when its `cwd` basename starts `tp-attempt-<slug>-`. A ladder dir that is not under a
`tp-ladder/` parent has no state dir to read, so it is "no child" (the in-process path). A state
dir that exists but cannot be listed counts as a live child: the watch keeps watching, never a
false done. A dead pid with a stale `running` record is not live; `child_spawn.py sweep` owns that
record. Stdlib only; never raises.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import child_proc  # noqa: E402
import child_state  # noqa: E402
import task_attempts  # noqa: E402 - DIR_PREFIX, the attempt dir's name prefix


def children_base(ladder_dir) -> Path | None:
    """`<common>/tp-children` for a ladder dir shaped `<common>/tp-ladder/<slug>`, else None."""
    lad = Path(ladder_dir)
    if lad.parent.name != "tp-ladder":
        return None
    return lad.parent.parent / child_state.CHILDREN_DIR


def live_child(ladder_dir) -> bool:
    """True when a `running` child state of this ladder's design has a live recorded process."""
    base = children_base(ladder_dir)
    if base is None:
        return False
    prefix = f"{task_attempts.DIR_PREFIX}{Path(ladder_dir).name}-"
    try:
        if not base.is_dir():
            return False
        run_dirs = [p for p in base.iterdir() if p.is_dir()]
    except OSError:
        return True  # unreadable state dir: not done, never a false done
    for run in run_dirs:
        try:
            files = child_state.children(run)
        except OSError:
            return True
        for path in files:
            st = child_state.read(path)
            if st.get("state") != "running":
                continue
            if not os.path.basename(str(st.get("cwd") or "").rstrip("/")).startswith(prefix):
                continue
            try:
                if child_proc.alive(int(st["pid"]), int(st.get("start_ticks") or -1)):
                    return True
            except (KeyError, TypeError, ValueError):
                continue
    return False
