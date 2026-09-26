"""launch_design_run.py — open a design run in its own top-level tmux window.

The one sanctioned way to start `/tp-run-full-design` from another session
(see design-run-launch.md). Resolves the `tp/<slug>` worktree, pre-trusts it
in the active profile's `.claude.json`, and opens a detached tmux window named
`<slug>` running the command built by `design_run_command.window_command`.
When tmux is unavailable (or on --dry-run) it prints the manual command.

Usage:
    python3 launch_design_run.py <slug> [--mode M] [--skip-design]
                                 [--model opus] [--local] [--dry-run]

Exit codes: 0 launched (or dry-run printed), 2 refused (manual command printed
when one could be built).
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from typing import Mapping, Optional, Sequence

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import design_run_command as drc  # noqa: E402


def find_worktree(porcelain: str, slug: str) -> Optional[str]:
    """Return the worktree path checked out on `refs/heads/tp/<slug>`, else None."""
    want = f"refs/heads/tp/{slug}"
    path = None
    for line in porcelain.splitlines():
        if line.startswith("worktree "):
            path = line[len("worktree "):]
        elif line.startswith("branch ") and line[len("branch "):] == want:
            return path
    return None


def _manual(cmd: str, reason: str) -> int:
    print(f"{reason} Run this in a new terminal / tmux window:")
    print(cmd)
    return 2


def main(
    argv: Optional[Sequence[str]] = None,
    *,
    env: Optional[Mapping[str, str]] = None,
    cwd: Optional[str] = None,
) -> int:
    env = os.environ if env is None else env
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("slug")
    ap.add_argument("--mode", default=None)
    ap.add_argument("--skip-design", action="store_true")
    ap.add_argument("--model", default=drc.DEFAULT_MODEL)
    ap.add_argument("--local", action="store_true", help="forward --local to the run")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    try:  # validate before any side effect
        drc.window_command(args.slug, ".", mode=args.mode, skip_design=args.skip_design,
                           model=args.model, local=args.local)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    listing = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=cwd, capture_output=True, text=True, encoding="utf-8",
    )
    wt = find_worktree(listing.stdout, args.slug) if listing.returncode == 0 else None
    if not wt:
        print(
            f"error: no worktree on branch tp/{args.slug}. Create one first: "
            f"git worktree add ../<repo>-wt/{args.slug} tp/{args.slug}",
            file=sys.stderr,
        )
        return 2

    config_dir, warning = drc.resolve_config_dir(env)
    if warning:
        print(warning, file=sys.stderr)
    cmd = drc.window_command(
        args.slug, wt, mode=args.mode, skip_design=args.skip_design,
        config_dir=config_dir, model=args.model, local=args.local,
    )
    if args.dry_run:
        print(cmd)
        return 0
    try:  # also helps the manual fallback skip the dialog
        drc.pretrust(wt, config_dir)
    except (OSError, ValueError) as exc:
        print(f"error: could not pre-trust worktree: {exc}", file=sys.stderr)
        return _manual(cmd, "Pre-trusting the worktree failed.")
    tmux = shutil.which("tmux", path=env.get("PATH"))
    if not env.get("TMUX") or not tmux:
        return _manual(cmd, "tmux is not available (not inside a tmux session).")

    proc = subprocess.run(
        [tmux, "new-window", "-d", "-n", args.slug, "-P", "-F",
         "#{session_name}:#{window_index}", cmd],
        capture_output=True, text=True, encoding="utf-8",
    )
    if proc.returncode != 0:
        print(proc.stderr.strip(), file=sys.stderr)
        return _manual(cmd, "tmux new-window failed.")
    target = proc.stdout.strip()
    print(f"design run launched in tmux window {target}")
    print(f"to show it in another session: tmux link-window -s {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
