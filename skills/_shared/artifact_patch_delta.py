"""artifact_patch_delta.py — working-tree patch-overreach measurement.

design: run-throughput (detailed-design-part-c.md, "Patch delta helper", Task 5.4).

``delta(path, base, cwd=None)`` measures how much the working tree changed a file
relative to commit ``base``, via ``git diff --numstat <base> -- <path>``:

- ``changed`` = ``max(added, deleted)`` — a line edited in place (1 added + 1
  deleted) counts as one changed line;
- ``total`` = the file's line count at ``base`` (``git show <base>:<path>``), or
  the current file's line count when the file is missing at base — a brand-new
  file therefore has ratio 1.0;
- ``ratio`` = ``round(changed / total, 4)``; when ``total`` is 0, ratio is
  0.0 when nothing changed and 1.0 when something did (an empty base file that
  gained lines is fully new content — documented choice).

The CLI ``python3 artifact_patch_delta.py --path P --base SHA`` prints the dict
as one JSON line and exits 0; a usage or git error exits 2 with a stderr line.
The consumer that logs ``flag: patch-overreach`` when ``ratio > 0.5`` (the
orchestrator's audit-retry logging) is a separate concern and not implemented
here — this module is only the measurement helper.

Stdlib only; uses ``task_scope._git_env`` for the scrubbed git env.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

_SHARED = str(Path(__file__).resolve().parent)
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

from task_scope import _git_env  # noqa: E402


class DeltaError(RuntimeError):
    """A git invocation failed (bad base sha, not a repo, ...) or output was malformed."""


def _run_git(args: list[str], cwd) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=str(cwd) if cwd is not None else None,
        env=_git_env(), capture_output=True, text=True)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip().splitlines()
        raise DeltaError(f"git {' '.join(args)} failed: {detail[-1] if detail else 'unknown error'}")
    return proc.stdout


def _lines(text: str) -> int:
    return len(text.splitlines())


def delta(path, base, cwd=None) -> dict:
    """``{changed, total, ratio}`` for ``path`` in the working tree vs ``base``.

    ``cwd`` is the directory of the git repository holding ``path``; ``None``
    falls back to the process working directory (the documented choice — the
    helper never guesses a repo root, so callers with an absolute ``path``
    outside the cwd must pass ``cwd``)."""
    added = deleted = 0
    seen = False
    for line in _run_git(["diff", "--numstat", base, "--", str(path)], cwd).splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            raise DeltaError(f"malformed numstat line: {line!r}")
        if parts[1] == "-":
            continue  # binary file: numstat prints "-" for both counts
        added, deleted = int(parts[0]), int(parts[1])
        seen = True
    changed = max(added, deleted)
    if not seen:
        # ``git diff --numstat`` prints no row when the file is unchanged vs
        # base — an unchanged file is a legitimate zero delta, not an error:
        # report {changed: 0, total: <lines at base>, ratio: 0.0}.
        base_lines = _lines(_run_git(["show", f"{base}:{path}"], cwd))
        return {"changed": 0, "total": base_lines, "ratio": 0.0}
    total = 0
    try:
        total = _lines(_run_git(["show", f"{base}:{path}"], cwd))
    except DeltaError:
        # File missing at base (brand-new): total is the current line count.
        p = Path(str(path))
        if not p.is_absolute():
            base_dir = Path(os.getcwd()) if cwd is None else Path(str(cwd))
            p = base_dir / p
        total = _lines(p.read_text(encoding="utf-8")) if p.is_file() else 0
    ratio = round(changed / total, 4) if total else (1.0 if changed else 0.0)
    return {"changed": changed, "total": total, "ratio": ratio}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="artifact_patch_delta.py",
        description="print {changed, total, ratio} for a working-tree file vs a base commit")
    parser.add_argument("--path", required=True, help="file path (repo-relative or absolute)")
    parser.add_argument("--base", required=True, help="base commit sha")
    args = parser.parse_args(argv)
    try:
        result = delta(args.path, args.base)
    except (DeltaError, OSError, ValueError) as exc:
        print(f"artifact_patch_delta: error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
