"""scratch_root.py — the one scratch base for attempt and child-spawn dirs.

design: launch-role-precedence (Task 3.1)

New scratch lives under ``.tp-scratch`` (no ``.claude`` component);
``.claude/worktrees`` is the legacy location, still scanned after the new one.
``ensure_excluded`` keeps ``.tp-scratch/`` out of ``git status`` in consumer
repos via ``<git-common-dir>/info/exclude``. Fail-open: never raises.
"""
import os
import subprocess
from pathlib import Path

SCRATCH_DIR = ".tp-scratch"
CHILD_SPAWN_DIR = ".tp-scratch/child-spawn"
LEGACY_DIR = ".claude/worktrees"


def parent(root):
    return os.path.join(str(root), SCRATCH_DIR)


def scan_parents(root):
    """New base first, then the legacy one."""
    return [parent(root), os.path.join(str(root), LEGACY_DIR)]


def is_under_scratch(path):
    return SCRATCH_DIR in Path(str(path)).parts


def ignore_line():
    return "/" + SCRATCH_DIR + "/"


def _git(root, *args):
    return subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True)


def ensure_excluded(root):
    """Ensure `/.tp-scratch/` is ignored; True on success, False on any failure."""
    try:
        if _git(root, "check-ignore", "-q", SCRATCH_DIR + "/x").returncode == 0:
            return True
        r = _git(root, "rev-parse", "--git-common-dir")
        if r.returncode != 0 or not r.stdout.strip():
            return False
        common = Path(r.stdout.strip())
        if not common.is_absolute():
            common = Path(str(root)) / common
        exclude = common / "info" / "exclude"
        exclude.parent.mkdir(parents=True, exist_ok=True)
        text = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
        if ignore_line() in text.splitlines():
            return True
        sep = "" if not text or text.endswith("\n") else "\n"
        exclude.write_text(text + sep + ignore_line() + "\n", encoding="utf-8")
        return True
    except (OSError, subprocess.SubprocessError, ValueError):
        return False
