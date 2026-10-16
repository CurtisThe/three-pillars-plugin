"""design_run_observe.py — the read-only observers behind design_run_watch.py.

Each observer is one injectable callable returning what `design_run_watch.step` folds:
the `tp/<slug>` / `candidate/<slug>/*` refs (`git for-each-ref`), the run window's pane
text (`capture-pane -p`), liveness (`design_run_tmux.live`) and new router.log lines.
Nothing here writes or signals anything: every tmux call is a read-only query. A source
that cannot be read yields None / [] (skipped), never an exception (design-run-launch.md).
"""
from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Optional

import design_run_tmux as drt
import design_run_window_env as dwe
import launcher_which
import router_stats


@dataclass
class Observers:
    refs: Callable[[], "Optional[dict[str, tuple[str, str]]]"]
    pane: Callable[[], Optional[str]]
    live: Callable[[], bool]
    router: Callable[[], "list[str]"]
    router_path: Optional[Path] = None  # for the one "log missing" notice


_ROUTE_PROFILE: "dict[tuple, str]" = {}  # (worktree, PATH, HOME) -> profile; answers only


def _route_profile_dir(worktree: str, env: Mapping[str, str]) -> Optional[Path]:
    """The run's route profile dir, as `design_run_launch_plan.build` resolves it; else None.

    With a launcher on PATH the run comes up on the profile `claude-which` names for its
    worktree, not on the seat's. No launcher, or no answer: None (the caller keeps the seat's).
    """
    home = env.get("HOME") or str(Path.home())
    key = (os.path.abspath(worktree), env.get("PATH", ""), home)
    if key not in _ROUTE_PROFILE:
        if launcher_which.launcher_home(dict(env)) is None:
            return None
        profile = (launcher_which.which(worktree, dict(env)) or {}).get("profile")
        if not profile:
            return None
        _ROUTE_PROFILE[key] = profile
    return Path(home) / dwe.PROFILES_DIR / _ROUTE_PROFILE[key]


def project_dir(worktree: str, env: Mapping[str, str]) -> Path:
    """The run's transcript directory for `worktree` (`projects/<path, non-alnum -> '-'>`)."""
    config = (_route_profile_dir(worktree, env) or env.get("CLAUDE_CONFIG_DIR")
              or os.path.join(env.get("HOME") or str(Path.home()), ".claude"))
    return Path(config) / "projects" / re.sub(r"[^A-Za-z0-9]", "-", os.path.abspath(worktree))


def discover_session(worktree: Optional[str], env: Mapping[str, str]) -> Optional[str]:
    """First 8 chars of the newest transcript's id under the worktree's project dir, else None."""
    if not worktree:
        return None
    try:
        files = sorted(project_dir(worktree, env).glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
    except OSError:
        return None
    return files[-1].stem[:8] if files else None


def git_refs(worktree: str, slug: str) -> "Optional[dict[str, tuple[str, str]]]":
    """{ref: (sha, subject)} for `tp/<slug>` and `candidate/<slug>/*`; None if git fails."""
    try:
        proc = subprocess.run(
            ["git", "-C", worktree, "for-each-ref", "--format=%(refname:short)%09%(objectname)%09"
             "%(contents:subject)", f"refs/heads/tp/{slug}", f"refs/heads/candidate/{slug}/"],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    refs = {}
    for row in proc.stdout.splitlines():
        name, _, rest = row.partition("\t")
        sha, _, subject = rest.partition("\t")
        if name and sha:
            refs[name] = (sha, subject)
    return refs


def pane_text(runner: drt.Runner, slug: str) -> Optional[str]:
    """The run window's visible text, or None when the window cannot be read."""
    wid = drt.run_window(runner, slug)
    if wid is None:
        return None
    rc, out = runner(["capture-pane", "-p", "-t", wid])
    return out if rc == 0 else None


class RouterTail:
    """New whole lines of router.log since construction (a log that appears later is read
    from its start; a truncated one restarts). A missing or unreadable file yields []."""

    def __init__(self, path: Path):
        self.path = path
        self.offset = self._size() or 0

    def _size(self) -> Optional[int]:
        try:
            return self.path.stat().st_size
        except OSError:
            return None

    def __call__(self) -> "list[str]":
        size = self._size()
        if size is None:
            return []
        if size < self.offset:
            self.offset = 0
        try:
            with open(self.path, "rb") as fh:
                fh.seek(self.offset)
                data = fh.read()
        except OSError:
            return []
        end = data.rfind(b"\n") + 1
        self.offset += end
        return data[:end].decode("utf-8", errors="replace").splitlines()


def real_observers(slug: str, worktree: str, runner: drt.Runner,
                   env: Mapping[str, str]) -> Observers:
    path = router_stats.log_path(env)
    return Observers(
        refs=lambda: git_refs(worktree, slug),
        pane=lambda: pane_text(runner, slug),
        live=lambda: bool(drt.live(slug, runner)),
        router=RouterTail(path),
        router_path=path)
