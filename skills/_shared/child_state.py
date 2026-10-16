#!/usr/bin/env python3
"""child_state.py — the per-run child state dir and its atomic state files.

design: strata-session-isolation (task 2.2). Every child a framework site spawns
records its pid/pgid/start-ticks, deadline and state in one JSON file, and a
later `stop` / `sweep` must find that file again from a *different* worktree of
the same repo. So the base is the git **common** dir (`git -C <root> rev-parse
--git-common-dir`), which a linked worktree shares with its seat — the child's
state outlives the worktree that made it. Outside a repo the base is
`tempfile.gettempdir()` instead, so a site with no git still has somewhere to
write. The base holds `tp-children/<run8>/` — one directory per run, plus one
file per repo (`smoke.json`) — and the run id
is `CLAUDE_CODE_SESSION_ID` (or the caller's `--run`), truncated to 8 chars,
`norun` when there is none, and the directory is created mode 0700 because the
state inside names a process this machine may later signal.

A state file is written atomically — a uniquely-named tmp file in the same
directory, then `os.replace` — so a child killed mid-write leaves the previous
state readable rather than a truncated file `sweep` would misread. `read`
answers `{}` for anything it cannot parse, so a corrupt file is "no
information", never a crash. `children` and `all_run_dirs` are exactly what
`sweep` iterates: every state file of one run (the per-run `probe.json` cache is
not a child), and every run directory of one repo (`smoke.json` sits beside them,
so a directory-only listing ignores it).

The two verdict caches (task 2.3) keep their cost off the hot path. A smoke
**pass** is cached per claude version **and** permission mode (task 1.4) in
`tp-children/smoke.json` — one entry, the last pass, because a newer claude can
break a child that worked yesterday, so the key is `claude --version` +
`permission_mode` and a mismatch on either is a miss. A probe result, and a
smoke **failure**, are cached only in that run's `probe.json`: a failure never
reaches `smoke.json`, so the next run re-smokes instead of inheriting a verdict
that might now pass. Both readers answer `None` (re-probe) rather than `{}`, and
both writers go through `write`, so neither can leave a half-written cache.

The module's own git call runs with the repo-local git env scrubbed
(`task_scope._git_env` — `git_env` itself is dev-only and never ships), so a
hook-exported `GIT_DIR` can never point it at the committing repo. Stdlib only;
never raises past a return value.
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
import sys
import tempfile
from pathlib import Path

_SHARED = str(Path(__file__).resolve().parent)
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

import task_scope  # noqa: E402 — the shipped git-env scrub; git_env is dev-only

__all__ = ["CHILDREN_DIR", "PROBE_CACHE", "SMOKE_CACHE", "DIR_MODE", "run_dir",
           "write", "read", "probe_cache", "write_probe", "smoke_cache",
           "write_smoke", "children", "all_run_dirs"]

CHILDREN_DIR = "tp-children"
PROBE_CACHE = "probe.json"      # per-run probe/smoke cache — never a child state file
SMOKE_CACHE = "smoke.json"      # per-repo smoke pass, keyed by claude version
RUN_ENV = "CLAUDE_CODE_SESSION_ID"
RUN_LEN = 8                     # run ids are uuid-ish: 8 hex chars collide at ~4.3 billion
DEFAULT_RUN = "norun"           # no session id (a bare script, a hook, a test)
DIR_MODE = 0o700
STATE_GLOB = "*.json"
GIT_TIMEOUT_S = 10
_SAFE = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")


def _run_name(run: str | None) -> str:
    """The directory name for a run: `run` (else `$CLAUDE_CODE_SESSION_ID`), 8 chars, path-safe.

    A run id arrives from the environment, so anything that is not alphanumeric
    or `.` `_` `-` becomes `_` before it names a directory; an empty or unset id
    is `norun`. A name of only dots is excluded too — `.` and `..` are the two
    path components that must never be a directory this code creates.
    """
    raw = str(run if run is not None else os.environ.get(RUN_ENV, ""))
    name = "".join(c if c in _SAFE else "_" for c in raw.strip())[:RUN_LEN]
    return name if name and name.strip(".") else DEFAULT_RUN


def _git_common_dir(root) -> Path | None:
    """The git common dir of `root` (absolute), or None when `root` is not in a repo.

    `--git-common-dir` is the seat's `.git` for a linked worktree — the one path
    every worktree of the repo agrees on. Git prints it relative to `root`, so it
    is joined and resolved. Any failure (no git, not a repo, timeout) is None.
    """
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--git-common-dir"],
            capture_output=True, text=True, timeout=GIT_TIMEOUT_S,
            env=task_scope._git_env(),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    out = proc.stdout.strip()
    if not out:
        return None
    path = Path(out)
    return path.resolve() if path.is_absolute() else (Path(root) / path).resolve()


def run_dir(run: str | None = None, root=".") -> Path:
    """`<git common dir>/tp-children/<run8>/` (mode 0700), else `$TMPDIR/tp-children/<run8>/`.

    Creates the directory (and its parents) but returns the path either way: an
    unwritable base is a state write that fails, not an exception. Callers pass
    no `run` to mean "this session" (`$CLAUDE_CODE_SESSION_ID`).
    """
    base = _git_common_dir(root)
    if base is None:
        base = Path(tempfile.gettempdir())
    path = base / CHILDREN_DIR / _run_name(run)
    try:
        os.makedirs(path, mode=DIR_MODE, exist_ok=True)
    except OSError:
        pass  # the caller's next `write` reports it; `read` answers {}
    return path


def write(path, state) -> None:
    """Replace `path` with JSON `state` atomically: a tmp file in the same dir, then `os.replace`.

    Same directory because `os.replace` cannot cross one. A crash before the
    rename leaves the previous file intact plus one stray `*.tmp` (which is not
    a state file: `children` globs `*.json`). Any error — unwritable dir,
    unserializable `state`, a failed rename — returns None: a site that cannot
    persist a child still has the child in memory and must stop it.
    """
    path = Path(path)
    tmp: Path | None = None
    try:
        fd, name = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".",
                                    suffix=".tmp")
        tmp = Path(name)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(state, fh)
            fh.write("\n")
        os.replace(tmp, path)
    except (OSError, TypeError, ValueError):
        if tmp is not None:
            try:
                tmp.unlink()
            except OSError:
                pass


def read(path) -> dict:
    """The JSON object in `path`; `{}` when it is missing, unreadable, unparsable or not an object."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def probe_cache(run_dir_path) -> dict | None:
    """This run's cached probe verdict from `<run dir>/probe.json`, or None to mean "re-probe".

    None is the whole point: a missing, unreadable or unparsable file (and a run
    dir that was never written) makes the caller run the probe again, which is
    cheaper and safer than trusting a verdict from a run that may since have had
    its child killed or its claude upgraded.
    """
    data = read(Path(run_dir_path) / PROBE_CACHE)
    return data or None


def write_probe(run_dir_path, verdict) -> None:
    """Cache this run's probe `verdict` (`{"mode", "why"}`) in `<run dir>/probe.json`.

    Per-run on purpose — including a smoke *failure*, which never reaches
    `smoke.json`. Unwritable dir or unserializable `verdict` returns None like
    every other `write`; the caller then simply probes again next time.
    """
    write(Path(run_dir_path) / PROBE_CACHE, verdict)


def smoke_cache(common_dir, claude_version, *, mode: str) -> dict | None:
    """The cached smoke pass for `claude_version` **and** `mode`, or None to re-probe.

    One entry only — the last pass — so an upgrade is a miss for free: the file
    names the version it was recorded against and a different `claude_version` is
    simply not that entry. The mode is part of the key for the same reason (task
    1.4): a pass earned launching in `auto` proves nothing about a `dontAsk`
    launch, and an entry written before that key existed (no `permission_mode`)
    is a miss too.
    """
    data = read(Path(common_dir) / CHILDREN_DIR / SMOKE_CACHE)
    if (data.get("ok") and data.get("claude_version") == claude_version
            and data.get("permission_mode") == mode):
        return data
    return None


def write_smoke(common_dir, claude_version, result, *, mode: str) -> None:
    """Record a smoke **pass** for `claude_version` + `mode` in `<common>/tp-children/smoke.json`.

    Writes only when `result["ok"]` is true. A failure is deliberately dropped
    here — the caller caches it with `write_probe` instead — because a failure
    cached per repo would make every later run on this machine believe a child
    cannot work, when the thing that broke may have been transient. `at` is the
    ISO-8601 UTC time of the pass, for a human reading the file.
    """
    if not result.get("ok"):
        return
    write(Path(common_dir) / CHILDREN_DIR / SMOKE_CACHE, {
        "claude_version": claude_version,
        "permission_mode": mode,
        "ok": True,
        "why": str(result.get("why", "")),
        "at": datetime.now(timezone.utc).isoformat(),
    })


def children(run_dir_path) -> list[Path]:
    """Every child state file of one run dir, sorted: each `*.json` except `probe.json`."""
    found = (p for p in Path(run_dir_path).glob(STATE_GLOB) if p.is_file())
    return sorted((p for p in found if p.name != PROBE_CACHE), key=lambda p: p.name)


def all_run_dirs(common_dir) -> list[Path]:
    """Every run directory under `<common_dir>/tp-children/`, sorted — the whole of `sweep --stale`."""
    base = Path(common_dir) / CHILDREN_DIR
    try:
        entries = list(base.iterdir())
    except OSError:
        return []
    return sorted((p for p in entries if p.is_dir()), key=lambda p: p.name)
