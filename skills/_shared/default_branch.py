#!/usr/bin/env python3
"""default_branch.py — resolve a repository's default branch.

design: consumer-repo-parity (Task 4.1, spec part B §M4)

`resolve_default_branch(repo_root=".", *, explicit=None, run_git=None)` walks a
fixed order and returns the first name that resolves:

  1. `explicit` — the caller's name, returned verbatim (not validated);
  2. `origin/HEAD` — the symbolic remote HEAD, with the `origin/` prefix
     stripped (`git symbolic-ref --short refs/remotes/origin/HEAD`);
  3. `init.defaultBranch` — `git config init.defaultBranch`, used only if the
     local branch `refs/heads/<name>` exists (an unset or dangling value is
     skipped, so it never points at a branch this clone does not have);
  4. local `main`;
  5. local `master`.

Nothing resolves → `DefaultBranchError`. `run_git` is an injectable callable
`(args: list[str], cwd) -> (returncode, stdout)` used for every git query; the
default is a `subprocess.run` wrapper.

`default_ref(repo_root=".", *, prefer="local")` (Task 4.2) returns the first
verifying ref of the resolved name — `<resolved>`, `origin/<resolved>` (order
reversed for `prefer="origin"`), verified with `git rev-parse --verify --quiet
<ref>^{commit}` — or None when nothing verifies or the resolver raises. It
never raises.

Stdlib-only: a shipped helper, no third-party or dev-only imports.

CLI: `default_branch.py [--repo P]` prints the resolved name and exits 0, or
exits 1 with guidance on stderr (nothing on stdout).
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


class DefaultBranchError(RuntimeError):
    """Raised when no default branch can be resolved for a repository."""


def _default_run_git(args: list[str], cwd) -> tuple[int, str]:
    """The production `run_git` wrapper: run `git <args>` under `cwd`."""
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True,
        stdin=subprocess.DEVNULL)
    return (proc.returncode, proc.stdout)


def _origin_head(run_git, repo_root) -> str | None:
    """The branch `refs/remotes/origin/HEAD` points at, or None if unset.

    Runs `git symbolic-ref --short refs/remotes/origin/HEAD` and strips the
    `origin/` prefix the short form carries."""
    rc, out = run_git(["symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
                      repo_root)
    if rc != 0:
        return None
    name = out.strip()
    if not name:
        return None
    prefix = "origin/"
    return name[len(prefix):] if name.startswith(prefix) else name


def _local(run_git, repo_root, name: str) -> bool:
    """True if local branch `refs/heads/<name>` exists and verifies."""
    rc, _ = run_git(["show-ref", "--verify", "--quiet",
                     f"refs/heads/{name}"], repo_root)
    return rc == 0


def _init_default(run_git, repo_root) -> str | None:
    """`git config init.defaultBranch`, or None if unset.

    The caller gates this on `_local(name)` — the value is honoured only when
    the local branch exists, so a stale `init.defaultBranch` never resolves to
    a branch this clone does not have."""
    rc, out = run_git(["config", "init.defaultBranch"], repo_root)
    name = out.strip()
    return name if (rc == 0 and name) else None


def resolve_default_branch(repo_root=".", *, explicit: str | None = None,
                           run_git=None) -> str:
    """Return the repository's default-branch name; raise `DefaultBranchError`.

    `repo_root` is the path the git queries run under (default `.`). `explicit`
    short-circuits the whole cascade (returned verbatim). `run_git` is an
    injectable `(args, cwd) -> (returncode, stdout)`; the default runs git via
    `subprocess`."""
    git = run_git or _default_run_git
    if explicit:
        return explicit

    origin = _origin_head(git, repo_root)
    if origin:
        return origin

    configured = _init_default(git, repo_root)
    if configured and _local(git, repo_root, configured):
        return configured

    for name in ("main", "master"):
        if _local(git, repo_root, name):
            return name

    raise DefaultBranchError(
        f"could not determine the default branch of {repo_root!r}: no "
        "origin/HEAD, no init.defaultBranch (or its branch is absent), and "
        "neither a local main nor a local master branch exists")


def _ref_verifies(run_git, repo_root, ref: str) -> bool:
    """True if `ref` resolves to a commit
    (`git rev-parse --verify --quiet <ref>^{commit}`)."""
    rc, _ = run_git(["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
                    repo_root)
    return rc == 0


def default_branch_names(repo=".") -> tuple[str, ...]:
    """The names to treat as "the default branch" for `repo` — fail-safe.

    Returns the fixed `("main", "master")` tuple plus `repo`'s resolved
    default-branch name (deduplicated, fixed names first). Never raises: a
    `DefaultBranchError` from `resolve_default_branch` — or any other
    exception, e.g. an OSError from a nonexistent `repo` — falls back to the
    fixed `("main", "master")` tuple alone."""
    names = ["main", "master"]
    try:
        resolved = resolve_default_branch(repo)
    except Exception:
        return tuple(names)
    if resolved not in names:
        names.append(resolved)
    return tuple(names)


def default_ref(repo_root=".", *, prefer="local") -> str | None:
    """The first verifying ref of the resolved default branch, else None.

    Candidates: `<resolved>` and `origin/<resolved>`; the order is local
    first for `prefer="local"` (the default) and reversed for
    `prefer="origin"`. A ref verifies via `git rev-parse --verify --quiet
    <ref>^{commit}`. Never raises: a `DefaultBranchError` from
    `resolve_default_branch` also yields None."""
    git = _default_run_git
    try:
        name = resolve_default_branch(repo_root)
    except DefaultBranchError:
        return None
    order = (name, f"origin/{name}") if prefer == "local" \
        else (f"origin/{name}", name)
    for ref in order:
        if _ref_verifies(git, repo_root, ref):
            return ref
    return None


def main(argv=None) -> int:
    """CLI: `default_branch.py [--repo P]`.

    Prints the resolved name and returns 0; on `DefaultBranchError` prints
    guidance to stderr and returns 1 (nothing on stdout)."""
    parser = argparse.ArgumentParser(
        prog="default_branch.py",
        description="Resolve the repository's default branch.")
    parser.add_argument("--repo", default=".",
                        help="repository root to resolve (default: current dir)")
    args = parser.parse_args(argv)
    try:
        print(resolve_default_branch(Path(args.repo)))
    except DefaultBranchError as exc:
        print(f"default_branch: {exc}", file=sys.stderr)
        print(
            "hint: set origin/HEAD (`git remote set-head origin <branch>`), "
            "set `init.defaultBranch`, or create a local `main` or `master` "
            "branch", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
