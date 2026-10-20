"""design_run_resume.py — find the conversation a rebooted design run should resume.

design: fleet-windows-reboot-resume (Task 1.2). A machine restart kills every run's `claude`;
`launch_design_run.py <slug> --resume` puts the run back on its own transcript. This module is
the part that decides what to resume and keeps the run's bookkeeping honest:

- `resolve_session` / `list_candidates`: the newest top-level transcript under the run's project
  dir (a sid is the whole file stem), or a named `--session`; the worktrees a reboot left idle.
- `pane_pid` / `refresh_run_state`: `run.pid` is a process-group id (teardown and
  `kill_supervisor` `killpg` it), so the caller passes the run window's `#{pane_pid}`, the group
  leader, never the deepest `claude` pid. Only a run that already has a `run.pid` is rewritten.
- `ledger_claimed`: a rollover cut off at reboot leaves a `claimed` ledger entry, so none will
  fire for that session again.

Read-only except `refresh_run_state`, which writes two files with temp-file-then-`os.replace`.
Nothing here signals a process. Stdlib plus its `_shared` siblings.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import stat
import sys
import tempfile
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import child_state as cs  # noqa: E402
import context_rollover_state as crs  # noqa: E402
import design_run_observe as dro  # noqa: E402
import design_run_tmux as drt  # noqa: E402

__all__ = ["ResumeError", "resolve_session", "list_candidates", "pane_pid",
           "refresh_run_state", "ledger_claimed"]

_SID = re.compile(r"[A-Za-z0-9-]+")
_DIGITS = re.compile(r"[0-9]+")
_RUN_DIR = (".three-pillars", "run")


class ResumeError(ValueError):
    """There is no session to resume, or the named one does not exist."""


def _slug(worktree: str) -> str:
    return os.path.basename(os.path.abspath(worktree))


def _child_sessions(worktree: str) -> "frozenset[str]":
    """Every `child_session` recorded under the worktree's `<git common dir>/tp-children/`.

    A `child_spawn.py start` runs `claude -p` in the design worktree, so its transcript lands
    beside the run's own; these ids are the ones to skip. Fail open: any git or read failure
    leaves the set empty (nothing is excluded)."""
    try:
        common = cs._git_common_dir(worktree)
        if common is None:
            return frozenset()
        found = set()
        for rdir in cs.all_run_dirs(common):
            for state in cs.children(rdir):
                sid = cs.read(state).get("child_session")
                if isinstance(sid, str) and sid:
                    found.add(sid)
        return frozenset(found)
    except (OSError, ValueError):
        return frozenset()


def _newest(pdir: Path, worktree: str = "") -> "Optional[tuple[str, float]]":
    """(sid, mtime) of the newest top-level `*.jsonl` file in `pdir`, else None.

    Subdirectories (subagent transcripts live in `<sid>/subagents/`), anything that is not
    a regular `.jsonl` file, and a recorded child's transcript are skipped; an unreadable dir
    has no session."""
    try:
        names = list(pdir.iterdir())
    except OSError:
        return None
    skip = _child_sessions(worktree) if worktree else frozenset()
    best: "Optional[tuple[float, str]]" = None
    for path in names:
        if path.suffix != ".jsonl" or path.stem in skip:
            continue
        try:
            st = path.stat()
        except OSError:
            continue
        if stat.S_ISREG(st.st_mode) and (best is None or (st.st_mtime, path.stem) > best):
            best = (st.st_mtime, path.stem)
    return None if best is None else (best[1], best[0])


def resolve_session(worktree: str, env: Mapping[str, str],
                    override: Optional[str] = None) -> "tuple[str, float]":
    """`(sid, mtime)` of the session to resume in `worktree`; ResumeError when there is none.

    Without `override`: the newest transcript that is not a recorded child's. With it: that sid, after checking that
    `<project_dir>/<override>.jsonl` is a file (a bare sid only, so it cannot leave the dir)."""
    pdir = dro.project_dir(worktree, env)
    if override is None:
        found = _newest(pdir, worktree)
        if found is None:
            raise ResumeError(f"no session to resume for {_slug(worktree)}")
        return found
    unknown = ResumeError(f"unknown session {override!r}: no {override}.jsonl in {pdir}")
    if not _SID.fullmatch(override):
        raise unknown
    try:
        st = (pdir / f"{override}.jsonl").stat()
    except OSError:
        raise unknown from None
    if not stat.S_ISREG(st.st_mode):
        raise unknown
    return override, st.st_mtime


def list_candidates(worktrees: "Sequence[tuple[str, str]]", env: Mapping[str, str],
                    boot: Optional[float],
                    live: Callable[[str], object]) -> "Optional[list[tuple[str, str, float]]]":
    """`(slug, sid, mtime)` for each `(slug, path)` worktree a reboot left without a run.

    A candidate's newest transcript predates `boot` and `live(slug)` is falsy. None when
    `boot` is None: with the boot time unknown nothing can be called interrupted."""
    if boot is None:
        return None
    rows = []
    for slug, path in worktrees:
        found = _newest(dro.project_dir(path, env), path)
        if found is not None and found[1] < boot and not live(slug):
            rows.append((slug, found[0], found[1]))
    return rows


def pane_pid(runner: drt.Runner, slug: str) -> Optional[int]:
    """The integer `#{pane_pid}` of `=<slug>`'s run window, else None (read-only tmux queries).

    That pid is the pane shell, the process-group leader `run.pid` must hold."""
    try:
        wid = drt.run_window(runner, slug)
        if wid is None:
            return None
        rc, out = runner(["display-message", "-p", "-t", wid, "#{pane_pid}"])
    except (OSError, ValueError, IndexError):
        return None
    out = out.strip() if rc == 0 else ""
    return int(out) if _DIGITS.fullmatch(out) and int(out) > 0 else None


def _atomic_write(path: Path, text: str) -> bool:
    """Replace `path` with `text` via a temp file in the same dir; False when the write fails."""
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        try:
            shutil.copymode(path, tmp)  # keep the file's own mode, not mkstemp's 0600
        except OSError:
            pass
        os.replace(tmp, path)
        tmp = None
        return True
    except OSError:
        return False
    finally:
        if tmp is not None:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def _refresh_state(path: Path, pgid: int) -> None:
    """Set `supervisor.pid` in state.json. A missing or unusable file is left alone."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    sup = data.get("supervisor") if isinstance(data, dict) else None
    if isinstance(sup, dict):
        sup["pid"] = pgid
        _atomic_write(path, json.dumps(data, indent=2))


def refresh_run_state(worktree: str, pgid: int) -> bool:
    """Point `run.pid` and `state.json`'s `supervisor.pid` at the resumed run's group.

    Only when `.three-pillars/run/run.pid` already exists (a fleet worker): a plain run is
    never given a run dir. `pgid` must be a positive int (`killpg(0, ...)` or a negative
    value would signal the wrong group). True when `run.pid` was rewritten."""
    if type(pgid) is not int or pgid <= 0:
        return False
    run = Path(worktree).joinpath(*_RUN_DIR)
    if not (run / "run.pid").is_file():
        return False
    if not _atomic_write(run / "run.pid", f"{pgid}\n"):
        return False
    _refresh_state(run / "state.json", pgid)
    return True


def ledger_claimed(worktree: str, sid: str) -> bool:
    """True when the rollover ledger holds a `claimed` entry for `sid` (a cut-off rollover)."""
    found = crs.entry(Path(worktree).joinpath(*_RUN_DIR, "context-rollover.json"), sid)
    return found is not None and found.get("state") == crs.CLAIMED
