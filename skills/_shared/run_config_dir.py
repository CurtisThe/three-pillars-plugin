"""run_config_dir.py — the config dir a design run's `claude` really writes to.

design: fleet-watcher-reliability (Task 1.2). A run launched from a personal seat can come
up on another profile (classicai, aris): its transcripts live under that profile's
`projects/`, not under the seat's `CLAUDE_CONFIG_DIR`. The one honest source is the run's own
process: the deepest `claude` under the slug's run window (under the Homelab launcher the
first is its wrapper) and the `CLAUDE_CONFIG_DIR` in its `/proc/<pid>/environ` — found the
way `design_run_routing.wait_for_run` finds it, without its polling.

`config_dir` answers that path, or None; `project_dir` turns it into the transcript
directory and otherwise falls back, exactly, to `design_run_observe.project_dir`. Nothing
here raises: an unreadable source is "no answer", never an error (design-run-launch.md).
Every tmux, process-table and `/proc` read is an injectable seam; stdlib only.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Callable, Mapping, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import design_run_observe as dro  # noqa: E402
import design_run_routing as drr  # noqa: E402
import design_run_tmux as drt  # noqa: E402

__all__ = ["config_dir", "project_dir"]

CONFIG_KEY = "CLAUDE_CONFIG_DIR"


def config_dir(slug: str, runner: Optional[drt.Runner], *, table: drr.Table = drt._ps_table,
               read: Callable[[str], bytes] = drr._read_proc) -> Optional[str]:
    """`CLAUDE_CONFIG_DIR` of the deepest `claude` under `<slug>`'s run window; else None.

    None for no tmux runner, no run window, no live pane, no `claude` under it, an unreadable
    process table or environ, or an environ without the key (or with it empty). Never raises.
    """
    if runner is None:
        return None
    try:
        rows = table() if callable(table) else table
        panes = drr._pane_pids(runner, slug)
        if rows is None or not panes:
            return None
        for pane in panes:
            pid = drt.find_run_pid(pane, rows, deepest=True)
            if pid is not None:
                value = drr.parse_environ(read(f"/proc/{pid}/environ")).get(CONFIG_KEY, "")
                return value or None
    except Exception:  # fail-open by contract: a probe must never take its caller down
        return None
    return None


def project_dir(slug: str, worktree: str, runner: Optional[drt.Runner],
                env: Mapping[str, str], *, table: drr.Table = drt._ps_table,
                read: Callable[[str], bytes] = drr._read_proc) -> Path:
    """The run's transcript directory for `worktree`.

    `<config dir>/projects/<abspath(worktree), non-alphanumerics -> '-'>` when `config_dir`
    answers, else exactly `design_run_observe.project_dir(worktree, env)`.
    """
    config = config_dir(slug, runner, table=table, read=read)
    if not config:
        return dro.project_dir(worktree, env)
    # The same mangling as `design_run_observe.project_dir` (kept local: that one resolves the
    # config dir itself, so it cannot take the run's answer).
    return Path(config) / "projects" / re.sub(r"[^A-Za-z0-9]", "-", os.path.abspath(worktree))
