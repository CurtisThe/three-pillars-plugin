"""registry_edit.py — mechanical registry-edit detection (design: run-throughput).

`is_mechanical_registry_edit` recognises the one class of off-list change the
run-throughput phase rules may absorb without failing `unlisted file`: a small,
purely additive edit to a path the dispatcher already listed as a registry file.
Anything else — an unlisted path, any deletion, more than 3 added lines, a binary
(`-` numstat) or missing file, or a git error — returns False. Stdlib only; the
git env scrub comes from `task_scope._git_env` so no repo-local env (GIT_DIR,
GIT_WORK_TREE, ...) leaks into the subprocess.
"""
from __future__ import annotations

import subprocess

from task_scope import _git_env

_MAX_ADDED = 3


def is_mechanical_registry_edit(adir, base, path, registry_files) -> bool:
    """True iff ``path`` is in ``registry_files`` and its ``base..HEAD`` diff in
    ``adir`` adds 1..3 lines with zero deletions.

    ``registry_files`` is any container of path strings (e.g. the task's
    listed registry paths). Binary files report ``-`` in `git diff --numstat`
    and never satisfy the line-count predicate.
    """
    if path not in registry_files:
        return False
    try:
        out = subprocess.run(
            ["git", "-C", str(adir), "diff", "--numstat", str(base), "HEAD", "--", str(path)],
            capture_output=True, text=True, check=True, env=_git_env(),
        ).stdout
    except (subprocess.CalledProcessError, OSError):
        return False

    added_total = 0
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:  # unparseable numstat line
            return False
        added, deleted = parts[0], parts[1]
        if added == "-" or deleted == "-":  # binary numstat
            return False
        if int(deleted) != 0:  # any deletion is not a mechanical addition
            return False
        added_total += int(added)
    return 1 <= added_total <= _MAX_ADDED  # empty output (unchanged) is 0 -> False
