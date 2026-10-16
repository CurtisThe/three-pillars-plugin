#!/usr/bin/env python3
"""commit_guard.py — install and manage the commit guard (consumer-repo-parity H2).

`apply(repo, *, file_size, deny_no_verify)` installs the versioned sentinel
block into `pre-commit` and `commit-msg` (honouring the pre-commit framework
rule and the common-dir scope), refuses the unsafe cases with two manual
snippets and a per-clone marker, and on success persists the offer's answers
plus `applied_at`, the S1 deny rules when opted in, and the tp-root pointer.
`status(repo) -> dict` tells an effective install from a stale, missing or
disabled one; `refusal_cause(repo)` is the per-clone predicate; `refresh`
rewrites a stale block in place; `decline` writes only the per-clone
marker. `record_tp_root` writes `<git-common-dir>/three-pillars/tp-root`.

Split by responsibility (the 500-line cap): the shared foundation
(constants, `Refused`, the marker paths, the block/snippet builders, and the
S1 deny merge) lives in `commit_guard_settings`; the per-hook analysis and
install live in `commit_guard_hooks`. This module is the public entry point
and the CLI; `commit_guard.BODY_VERSION` / `BODY_SHA256` / `Refused` remain
here for importers. Stdlib only.
"""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

# The shared foundation (constants, `Refused`, the git helpers, the marker
# paths, the block/snippet builders and the S1 deny merge) and the per-hook
# analysis are imported here so `commit_guard.X` keeps its public name for
# importers.
from commit_guard_settings import (  # noqa: E402,F401
    BODY_SHA256, BODY_VERSION, HOOK_NAMES, Refused,
    _common_dir, _git, declined_marker, manual_marker, merge_deny, snippets_for)
from commit_guard_hooks import (  # noqa: E402
    _hooks_dir_ok, hook_refusal_cause, hook_status, install_hook)
from repo_config_load import load_repo_config, update_config  # noqa: E402


def _now_iso_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _plugin_root() -> str:
    # skills/_shared/<this file> -> the repo root the pointer must name.
    return str(Path(__file__).resolve().parents[2])


def apply(repo, *, file_size: bool = False, deny_no_verify: bool = False) -> None:
    """Install the guard into both hooks and persist the offer's answers.

    All-or-nothing: a refusal raises `Refused` (carrying the two manual
    snippets) before any hook, config or settings write, and records the
    cause in the per-clone `commit-guard-manual` marker. On success:
    `commit_guard.file_size` and `commit_guard.deny_no_verify` (false or
    true, as asked), `commit_guard.applied_at`, the S1 deny rules when opted
    in, and the tp-root pointer under the git common dir.
    """
    repo = Path(repo)
    _print_overdue_obligations(repo)
    hooks_dir, ok = _hooks_dir_ok(repo)
    if hooks_dir is None:
        raise Refused("cannot resolve this repo's git hooks directory",
                      snippets_for("cannot resolve the git hooks directory"))
    try:
        # Both hooks are checked before either is written: a refusal leaves
        # every hook as it was.
        cause = _scope_cause() if not ok else hook_refusal_cause(hooks_dir)
        if cause:
            raise Refused(cause, snippets_for(cause))
        # The pointer the sentinel body reads goes in BEFORE either hook: a
        # later failure (e.g. a config write refused by an unrelated invalid
        # key) must never leave installed hooks that print "commit NOT
        # checked" on every commit while status reports them effective.
        record_tp_root(repo, _plugin_root())
        for name in HOOK_NAMES:
            install_hook(hooks_dir, name)
    except Refused as exc:
        # Every refusal (a hooks dir outside the common dir, or a per-hook
        # refusal) is recorded per clone so the cheap path can settle it for
        # this clone; the committed config is not touched.
        common = _common_dir(repo)
        if common is not None:
            marker = manual_marker(repo)
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(exc.cause, encoding="utf-8")
        raise
    if deny_no_verify:
        merge_deny(repo)
    update_config(repo, "commit_guard.file_size", bool(file_size))
    update_config(repo, "commit_guard.deny_no_verify", bool(deny_no_verify))
    update_config(repo, "commit_guard.applied_at", _now_iso_utc())


def _scope_cause() -> str:
    return ("the hooks dir is outside the git common dir (a tracked in-tree "
            "hooks dir, or a repo/global core.hooksPath shared by every repo "
            "on the machine) — a guard block there would print 'plugin not "
            "found' on every commit elsewhere")


def status(repo) -> dict:
    """The install state (part E §status): `hooks_dir`/`hooks_dir_ok`, the
    two `hooks`, `tp_root`, the per-clone `local_decline`/`manual` markers,
    `stale`, and `effective`. The top-level `effective` is `hooks_dir_ok`
    and both hooks effective — so a global `core.hooksPath` set after the
    install makes it report not effective."""
    repo = Path(repo)
    hooks_dir, ok = _hooks_dir_ok(repo)
    if hooks_dir is not None:
        hooks = {name: hook_status(hooks_dir, name) for name in HOOK_NAMES}
    else:
        hooks = {name: {"target": None, "manager": None, "sentinel": False,
                        "version": None, "stale": False, "effective": False}
                 for name in HOOK_NAMES}
    tp_root = None
    common = _common_dir(repo)
    if common is not None:
        pointer = common / "three-pillars" / "tp-root"
        try:
            tp_root = pointer.read_text(encoding="utf-8")
        except (OSError, FileNotFoundError):
            pass
    return {
        "hooks_dir": str(hooks_dir) if hooks_dir else None,
        "hooks_dir_ok": ok,
        "hooks": hooks,
        "tp_root": tp_root,
        "local_decline": bool(common is not None and declined_marker(repo).exists()),
        "manual": _refusal_cause_from_marker(repo),
        "stale": any(h["stale"] for h in hooks.values()),
        "effective": ok and all(h["effective"] for h in hooks.values()),
    }


def _refusal_cause_from_marker(repo) -> str | None:
    marker = manual_marker(repo)
    if not marker.exists():
        return None
    try:
        return marker.read_text(encoding="utf-8")
    except (OSError, FileNotFoundError):
        return None


def refusal_cause(repo) -> str | None:
    """The per-clone refusal predicate (part E §Refusals): the cause when the
    install would still be refused now, else None. Written to
    `<git-common-dir>/three-pillars/commit-guard-manual`; read back by the
    cheap path, which deletes the marker and re-offers when this is None."""
    hooks_dir, ok = _hooks_dir_ok(repo)
    if not ok:
        return _scope_cause()
    if hooks_dir is not None:
        return hook_refusal_cause(hooks_dir)
    return None


def refresh(repo) -> None:
    """Rewrite only the current block in place (part E §Refresh / first-run):
    a `v<N-1>` block still runs, so first-run refreshes it to the current
    `BODY_VERSION`, keeping every foreign line. Refuses (no write) when the
    install would still be refused. Does not touch the committed config."""
    repo = Path(repo)
    hooks_dir, ok = _hooks_dir_ok(repo)
    cause = _scope_cause() if hooks_dir is None or not ok \
        else hook_refusal_cause(hooks_dir)
    if cause:
        raise Refused(cause, snippets_for(cause))
    for name in HOOK_NAMES:
        install_hook(hooks_dir, name)


def decline(repo) -> None:
    """Write only the per-clone `commit-guard-declined` marker (part E §CLI):
    a "no" to the offer settles this clone without touching the committed
    config, so one teammate's answer does not change the repo's."""
    common = _common_dir(repo)
    if common is None:
        raise Refused("cannot resolve the git common directory")
    marker = declined_marker(repo)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(_now_iso_utc(), encoding="utf-8")


def record_tp_root(repo, tp_root: str) -> bool:
    """Write `<git-common-dir>/three-pillars/tp-root`; True only on change.

    The sentinel body reads this pointer on every commit, so a plugin
    upgrade that moves the cache path is healed by re-recording it here —
    a rewrite of a file the guard already owns, never the committed config.
    """
    common = _common_dir(repo)
    if common is None:
        raise Refused("cannot resolve the git common directory")
    pointer = common / "three-pillars" / "tp-root"
    existing = None
    try:
        existing = pointer.read_text(encoding="utf-8")
    except (OSError, FileNotFoundError):
        pass
    if existing == tp_root:
        return False
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text(tp_root, encoding="utf-8")
    return True


def _print_overdue_obligations(repo) -> None:
    """Existing obligations are listed before the install (part E §First-run):
    `apply` runs the ledger coverage arm once and prints each overdue SHA
    with its remedy before touching any hook — the obligation is real
    regardless (arm (a)'s own contract), so this never blocks the install
    itself, and a failure to compute it is advisory-only."""
    try:
        from hot_patch_check import LEDGER_RELPATH, _run_arm_a  # noqa: PLC0415
        ledger_path = Path(repo) / LEDGER_RELPATH
        violations = _run_arm_a(str(repo), ledger_path, None)
    except Exception:  # noqa: BLE001 - advisory only, never blocks apply
        return
    for line in violations:
        print(line)
        if "ledger-overdue" in line:
            sha = line.split()[1]
            print(
                f"commit-guard: append {sha}'s entry to "
                "three-pillars-docs/tp-designs/orchestration/hot-patches.md "
                "before your next commit — the ledger backstop refuses it otherwise."
            )


def _has_any_ref(repo) -> bool:
    """True unless this is the root commit right after `git init` (no refs
    at all yet): step 0 of `run`'s dispatch skips steps 1-3 there — the
    write guard and isolation guard both resolve a current branch, which an
    unborn HEAD with no refs cannot supply consistently."""
    return _git(repo, "for-each-ref", "--count=1") is not None


def _current_branch(repo) -> list:
    """`["--branch", <name>]` from `git symbolic-ref --short -q HEAD` (works
    on an unborn or orphan branch too, unlike `rev-parse --abbrev-ref HEAD`),
    or `[]` on a detached HEAD — the guards then resolve the branch
    themselves and see the same detachment."""
    branch = _git(repo, "symbolic-ref", "--short", "-q", "HEAD")
    return ["--branch", branch] if branch else []


def _staged_paths(repo) -> list:
    """The staged-path list read through `git diff --cached`, honouring
    whatever `GIT_DIR`/`GIT_INDEX_FILE` this process inherited — never
    stripped or re-initialised, since `commit -a` or a pathspec commit hands
    the hook a temporary index that this must see.

    `-z` NUL-separates the names, so a non-ASCII or quoted-looking name
    arrives verbatim (never `core.quotePath`-escaped into a path that does
    not exist). A non-zero git exit raises: `run` calls this inside
    `_guarded`, so the failure blocks as an internal error — never an empty
    staged set that every staged-path guard would wave through."""
    proc = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR"],
        cwd=str(repo), capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"git diff --cached exited {proc.returncode}: {proc.stderr.strip()}")
    return [p for p in proc.stdout.split("\0") if p]


def _file_size_enabled(repo) -> bool:
    try:
        config = load_repo_config(repo).config
    except Exception:  # noqa: BLE001 - a config read must never block a commit
        return False
    return bool(config.get("commit_guard", {}).get("file_size", False))


def _guarded(name: str, func) -> int:
    """Run one guard's CLI `main` in-process inside its own try block (part E
    §run): an unexpected exception blocks with `commit-guard: internal error
    in <guard>: <exc>` rather than propagating out of the hook."""
    try:
        return func()
    except Exception as exc:  # noqa: BLE001
        print(f"commit-guard: internal error in {name}: {exc}", file=sys.stderr)
        return 1


def run(repo, hook: str, msg_file: str | None = None) -> int:
    """The `pre-commit` / `commit-msg` dispatcher (part E §`run(repo, hook,
    msg_file)`). `repo` is the hook's `git rev-parse --show-toplevel`; stdin
    is not read. Every guard runs in-process inside `_guarded`, so an
    unexpected exception blocks rather than crashing the hook."""
    repo = str(repo)

    if hook == "commit-msg":
        from hot_patch_check import main as hot_patch_check_main  # noqa: PLC0415
        return _guarded("hot_patch_check", lambda: hot_patch_check_main(
            ["--repo-root", repo, "--commit-msg", msg_file]))

    if hook != "pre-commit":
        print(f"commit-guard: unknown hook {hook!r}", file=sys.stderr)
        return 2

    blocked = False
    if _has_any_ref(repo):
        branch_arg = _current_branch(repo)
        from worktree_write_guard import main as write_guard_main  # noqa: PLC0415
        from worktree_isolation_guard import main as isolation_guard_main  # noqa: PLC0415
        from hot_patch_check import main as hot_patch_check_main  # noqa: PLC0415

        steps = (
            ("worktree_write_guard",
             lambda: write_guard_main(["--repo", repo, *branch_arg])),
            ("worktree_isolation_guard",
             lambda: isolation_guard_main(
                 ["--repo", repo, "--assert-own-worktree", *branch_arg])),
            ("hot_patch_check",
             lambda: hot_patch_check_main(
                 ["--repo-root", repo, "--ledger-only", "--branch-trailered"])),
        )
        for name, func in steps:
            if _guarded(name, func) != 0:
                blocked = True

    if _file_size_enabled(repo):
        from file_size_guard import main as file_size_guard_main  # noqa: PLC0415
        if _guarded("file_size_guard", lambda: file_size_guard_main(
                ["--repo-root", repo, *_staged_paths(repo)])) != 0:
            blocked = True

    return 1 if blocked else 0


def _resolve_repo(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit)
    out = _git(".", "rev-parse", "--show-toplevel")
    if not out:
        raise ValueError("not inside a git repository (pass --repo <path>)")
    return Path(out)


def _print_refused(exc) -> None:
    print(f"commit-guard: install refused: {exc.cause}", file=sys.stderr)
    for snip in exc.snippets:
        print("add by hand to the hook:\n" + snip, file=sys.stderr)


def main(argv=None) -> int:
    """CLI (part E §CLI). `apply [--file-size] [--deny-no-verify]` exits 0
    installed or already current, 3 refused (the cause and the two manual
    snippets on stderr); `status [--brief]` exits 0 when effective, 3 when
    not; `refresh` rewrites a stale block in place; `decline` writes only the
    per-clone marker; `record-tp-root <path>` prints `changed`/`unchanged`.
    `--repo` defaults to `git rev-parse --show-toplevel`."""
    import argparse

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--repo", default=None,
                        help="repo root (default: git rev-parse --show-toplevel)")
    parser = argparse.ArgumentParser(
        prog="commit_guard.py",
        description="Install and manage the three-pillars commit guard.")
    sub = parser.add_subparsers(dest="command", required=True)
    apply_p = sub.add_parser("apply", parents=[common],
                             help="install the guard into both hooks")
    apply_p.add_argument("--file-size", action="store_true",
                         help="opt the guard into the file-size cap checks")
    apply_p.add_argument("--deny-no-verify", action="store_true",
                         help="opt into the `git commit --no-verify` deny rules")
    status_p = sub.add_parser("status", parents=[common],
                             help="report the install state (exit 0 effective, 3 not)")
    status_p.add_argument("--brief", action="store_true",
                          help="print only the effective/stale/decline line")
    sub.add_parser("refresh", parents=[common],
                   help="rewrite a stale block to the current version")
    sub.add_parser("decline", parents=[common],
                   help="record this clone's decline (per-clone marker only)")
    root_p = sub.add_parser("record-tp-root", parents=[common],
                            help="write the tp-root pointer (prints changed/unchanged)")
    root_p.add_argument("path", help="plugin root to record")
    run_p = sub.add_parser("run", parents=[common],
                           help="dispatch a hook (called from the sentinel body)")
    run_p.add_argument("hook", choices=list(HOOK_NAMES))
    run_p.add_argument("msg_file", nargs="?", default=None,
                       help="commit-msg's message file")
    args = parser.parse_args(argv)
    repo = _resolve_repo(args.repo)

    if args.command == "run":
        try:
            return run(repo, args.hook, args.msg_file)
        except Exception as exc:  # noqa: BLE001 - never crash the hook
            print(f"commit-guard: internal error in run: {exc}", file=sys.stderr)
            return 1

    try:
        if args.command == "record-tp-root":
            changed = record_tp_root(repo, args.path)
            print("changed" if changed else "unchanged")
            return 0
        if args.command == "status":
            st = status(repo)
            if args.brief:
                print(f"effective={st['effective']} stale={st['stale']} "
                      f"local_decline={st['local_decline']}")
            else:
                import json  # noqa: PLC0415
                print(json.dumps(st))
            return 0 if st["effective"] else 3
        if args.command == "refresh":
            refresh(repo)
            return 0
        if args.command == "decline":
            decline(repo)
            return 0
        apply(repo, file_size=args.file_size, deny_no_verify=args.deny_no_verify)
    except Refused as exc:
        _print_refused(exc)
        return 3
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
