"""ci_gate_run.py — run the repo's declared gate command, then stamp the head.

design: consumer-repo-parity (Phase 2, H1)

A consumer repo declares its local CI gate command as `ci.gate_command` in
`.three-pillars/config.json`. This wrapper runs that command through the shell
at the repo root and — only on exit 0 — writes the head stamp via
`ci_local_stamp.write_stamp`, seeding it with the HEAD and working-tree dirty
state captured BEFORE the command ran so `write_stamp`'s drift guards catch a
commit-lands-mid-run or a dirty start.

Exit codes:
  * the command's returncode — passed through as-is on any non-zero rc
    (nothing is stamped);
  * 1 — a `StampError` refusal from `write_stamp` (head moved, a tracked file
    changed mid-run, or the run started dirty — untracked files count) — its
    text, listing the offending paths and pointing untracked ones at
    `.gitignore`, is printed to stderr. Both samples list untracked files
    per file (`--untracked-files=all`). An untracked path that only appears
    DURING a clean run is stamped (and reported as needing an ignore rule)
    only when it is a known test/bytecode cache (`__pycache__/**/*.pyc`,
    `.pytest_cache/**`, `.coverage` / `.coverage.*`); any other new untracked
    path (a conftest.py, build output, ...) refuses — it could have altered
    the result;
  * 2 — no `ci.gate_command` declared (the key is missing or `null`) — a
    pointer to the first-run offer is printed to stderr.

The command is the operator's own declared text (e.g. `make ci`, a pytest
invocation), run with `shell=True` like a Makefile target — not parsed or
sanitised by this wrapper.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

# Ensure _shared/ is on sys.path so sibling modules are importable when run as
# a script (same bootstrap as ci_local_stamp.py / deterministic_gate.py).
_SHARED_DIR = Path(__file__).resolve().parent
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

from ci_local_stamp import StampError, _get_head_sha, _is_dirty, write_stamp  # noqa: E402
from hot_patch_check import main as _hot_patch_check_main  # noqa: E402
from repo_config_load import load_repo_config  # noqa: E402


def _resolve_repo(repo_arg: "str | None") -> Path:
    """`--repo <path>` if given, else `git rev-parse --show-toplevel` from cwd.

    Raises ValueError when the repo cannot be resolved (not inside a git
    repository and no `--repo` given).
    """
    if repo_arg:
        return Path(repo_arg).resolve()
    proc = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        raise ValueError(
            "not inside a git repository (and no --repo given); pass --repo <path>"
        )
    return Path(proc.stdout.strip())


def _declared_gate_command(repo_root: Path) -> "str | None":
    """`ci.gate_command` from the repo config, or None when absent/null.

    A missing file, a fatal `schema_version`, a missing `ci` object, a missing
    `gate_command` key, or an explicit `null` all resolve to None (declared
    absent, or offered-and-declined) — the exit-2 no-command path.
    """
    config = load_repo_config(repo_root).config
    ci = config.get("ci")
    if not isinstance(ci, dict):
        return None
    command = ci.get("gate_command")
    if not isinstance(command, str) or not command:
        return None
    return command


def main(argv: "list[str] | None" = None) -> int:
    """CLI: run the gate command (resolved from `--command` else config) at the
    repo root and, on exit 0, stamp the head. See the module docstring for exit
    codes (command rc / 1 StampError refusal / 2 no command declared)."""
    parser = argparse.ArgumentParser(
        description="ci_gate_run — run the repo's declared gate command, then stamp",
    )
    parser.add_argument(
        "--repo", metavar="P", default=None,
        help="Repository root (default: git rev-parse --show-toplevel from cwd)",
    )
    parser.add_argument(
        "--command", metavar="CMD", default=None,
        help="Gate command to run (default: ci.gate_command from the repo config)",
    )
    args = parser.parse_args(argv)

    try:
        repo = _resolve_repo(args.repo)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    command = args.command if args.command else _declared_gate_command(repo)
    if command is None:
        print(
            "no ci.gate_command declared — declare one in "
            ".three-pillars/config.json (see skills/_shared/first-run.md)",
            file=sys.stderr,
        )
        return 2

    # H3's branch-trailered backstop, run before the gate command: a
    # hot-patch-trailered commit on this branch that dodged commit-msg
    # (--amend, rebase pick, cherry-pick) refuses the stamp here too.
    if _hot_patch_check_main(["--repo-root", str(repo), "--branch-trailered"]) != 0:
        return 1

    # Capture HEAD and dirty state BEFORE the command runs — these seed
    # write_stamp's drift guards (a commit landing mid-run, or a dirty start,
    # both refuse the stamp).
    start_head = _get_head_sha(repo)
    start_dirty = _is_dirty(repo)

    proc = subprocess.run(command, shell=True, cwd=str(repo))  # nosec B602 — operator's own declared command
    if proc.returncode != 0:
        return proc.returncode

    try:
        write_stamp(
            repo,
            expect_head=start_head,
            expect_start_dirty=start_dirty,
        )
    except StampError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
