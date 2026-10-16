#!/usr/bin/env python3
"""scratch_reap.py — sweep the scratch root of the framework's own leftovers.

design: scratch-reaper task 1.1. Deletes entries directly under the scratch
root (`--root`, else `$TMPDIR`, else `/tmp`) whose whole name matches the
framework allowlist (`tp-angle-*`, `slotrel-*`, `vfy.*`, and a CI stage root:
`c` + 3 alphanumerics) AND that are older than `--hours` (default 24).

Age: an entry is old only when its own `lstat().st_mtime` and the mtimes of its
direct children are all more than `hours` old — a directory's mtime moves when
a child is written, so a root still being written to is kept.

The `c`+3 pattern (the stage root the framework's own CI gate makes with
`mktemp -d`) is deliberately narrow: it applies only to a real directory
(never a symlink) whose children are all single-lowercase-letter stage
directories or stage logs named `<digits>-<name>.log`, or that is empty. A
hand-made `core` or `cfg1` is kept. Everything else — generic `tmp*`,
`pytest-of-*`, foreign names — is kept.

Symlinks are unlinked, never followed. Fail-open: every error is one
`scratch_reap: ...` line on stderr and `main` returns 0, also on bad flags.
`--dry-run` lists the would-remove names and removes nothing. Stdlib only.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import time
from pathlib import Path

NAME_PATTERNS = (
    re.compile(r"tp-angle-.+"),
    re.compile(r"slotrel-.+"),
    re.compile(r"vfy\..+"),
)
STAGE_ROOT_NAME = re.compile(r"c[A-Za-z0-9]{3}")
STAGE_DIR = re.compile(r"[a-z]")
STAGE_LOG = re.compile(r"\d+-[a-z_]+\.log")


def _fail(msg: str) -> None:
    print(f"scratch_reap: {msg}", file=sys.stderr)


def _entry_mtime(path: Path) -> float:
    return path.lstat().st_mtime


def _is_old(path: Path, cutoff: float) -> bool:
    """Old when the entry and every direct child are older than `cutoff`."""
    try:
        if _entry_mtime(path) >= cutoff:
            return False
        if path.is_symlink():
            return True
        if not path.is_dir():
            return True
        for child in path.iterdir():
            if _entry_mtime(child) >= cutoff:
                return False
        return True
    except OSError as exc:
        _fail(f"{path}: {exc}")
        return False


def _is_stage_shaped(path: Path) -> bool:
    """A CI stage root: real dir, children all stage dirs/logs, or empty."""
    try:
        for child in path.iterdir():
            if child.is_dir() and not child.is_symlink():
                if not STAGE_DIR.fullmatch(child.name):
                    return False
            elif not STAGE_LOG.fullmatch(child.name):
                return False
        return True
    except OSError as exc:
        _fail(f"{path}: {exc}")
        return False


def _matches(name: str, path: Path) -> bool:
    """Allowlist check on the whole name (`re.fullmatch`)."""
    if any(p.fullmatch(name) for p in NAME_PATTERNS):
        return True
    if not STAGE_ROOT_NAME.fullmatch(name):
        return False
    return path.is_dir() and not path.is_symlink() and _is_stage_shaped(path)


def _remove(path: Path) -> None:
    if path.is_symlink() or not path.is_dir():
        path.unlink()
    else:
        shutil.rmtree(path)


def reap(root, hours: float, dry_run: bool) -> list[str]:
    """Remove (or, with `dry_run`, just list) aged allowlisted entries in `root`.

    Returns the names acted on. Errors are one stderr line each and never
    raise; the sweep is fail-open by design.
    """
    root = Path(root)
    removed: list[str] = []
    try:
        entries = sorted(root.iterdir(), key=lambda p: p.name)
    except OSError as exc:
        _fail(f"{root}: {exc}")
        return removed
    cutoff = time.time() - hours * 3600
    for entry in entries:
        try:
            if not _matches(entry.name, entry):
                continue
            if not _is_old(entry, cutoff):
                continue
            if not dry_run:
                _remove(entry)
            removed.append(entry.name)
            print(entry.name)
        except OSError as exc:
            _fail(f"{entry}: {exc}")
    print(f"scratch_reap: {len(removed)} "
          f"{'would be ' if dry_run else ''}removed from {root}")
    return removed


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="scratch_reap", description="Sweep aged framework scratch entries.")
    parser.add_argument("--root", default=os.environ.get("TMPDIR") or "/tmp")  # nosec B108 — documented scratch-root fallback
    parser.add_argument("--hours", type=float, default=24.0)
    parser.add_argument("--dry-run", action="store_true")
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        _fail("bad flags")
        return 0
    reap(args.root, args.hours, args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
