"""certify_scratch — per-pole scratch clones and the caller-repo env scrub.

design: audit-pass-does-not-bind (Task 3.1; detailed-design.md §Interfaces [R2][R11], P6).

`pole_tree(repo, sha)` yields `(path, env)`: a detached checkout of `sha` in a
fresh temp dir, cloned `--shared --no-checkout` from `repo` with its `origin`
remote removed (a probe's `git push` / `fetch` has no route back to the
caller), removed on exit. `env` is the pole's process env: every
`git rev-parse --local-env-vars` name unset (so an inherited hook `GIT_DIR`
cannot point a pole's git at the caller), `PYTEST_*` unset (so no
`PYTEST_ADDOPTS` adds to the certifier's own fixed pytest command), `TMPDIR`
inside the pole dir, and a wide `COLUMNS`, so a tool that fits its output to
the terminal width never cuts or wraps a line a marker sits on (a non-pytest pole is read from its console
output; a pytest pole from its `--junitxml` report, which COLUMNS does not touch).

The scrub is this module's own: a shipped module must not import the
dev-only `git_env` (it is tiered dev in the release manifest).
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path

# `git rev-parse --local-env-vars` (git 2.43), unioned with the live answer.
LOCAL_ENV_VARS = (
    "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_CONFIG", "GIT_CONFIG_PARAMETERS",
    "GIT_CONFIG_COUNT", "GIT_OBJECT_DIRECTORY", "GIT_DIR", "GIT_WORK_TREE",
    "GIT_IMPLICIT_WORK_TREE", "GIT_GRAFT_FILE", "GIT_INDEX_FILE",
    "GIT_NO_REPLACE_OBJECTS", "GIT_REPLACE_REF_BASE", "GIT_PREFIX",
    "GIT_SHALLOW_FILE", "GIT_COMMON_DIR",
)
POLE_COLUMNS = "500"
GIT_TIMEOUT = 120


def local_env_vars() -> set[str]:
    """The repo-local git env names: the pinned set plus git's own list."""
    names = set(LOCAL_ENV_VARS)
    base = {k: v for k, v in os.environ.items() if k not in names}
    try:
        proc = subprocess.run(["git", "rev-parse", "--local-env-vars"], env=base,  # tp-allow-fail-open: git unavailable is handled by the except
                              capture_output=True, text=True, timeout=GIT_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return names  # git unavailable: the pinned set still applies
    return names | set(proc.stdout.split())


def scrubbed_env(base=None, **extra) -> dict:
    """A copy of `base` (default os.environ) minus the local git env and PYTEST_*."""
    source = os.environ if base is None else base
    drop = local_env_vars()
    env = {k: v for k, v in source.items() if k not in drop and not k.startswith("PYTEST_")}
    env.update(extra)
    return env


def git(args, *, cwd, env) -> str:
    """Run one git command (list argv, scrubbed env); raise on failure."""
    proc = subprocess.run(["git", *args], cwd=str(cwd), env=env, capture_output=True,
                          text=True, timeout=GIT_TIMEOUT, check=True)
    return proc.stdout


@contextmanager
def pole_tree(repo, sha):
    """Yield `(path, env)` for one pole; see the module docstring."""
    with tempfile.TemporaryDirectory(prefix="certify-pole-", ignore_cleanup_errors=True) as tmp:
        pole = Path(tmp)
        tree, scratch = pole / "tree", pole / "tmp"
        scratch.mkdir()
        env = scrubbed_env(TMPDIR=str(scratch), COLUMNS=POLE_COLUMNS, GIT_TERMINAL_PROMPT="0")
        git(["clone", "--quiet", "--shared", "--no-checkout", str(Path(repo).resolve()),
             str(tree)], cwd=pole, env=env)
        git(["remote", "remove", "origin"], cwd=tree, env=env)
        git(["checkout", "--quiet", "--detach", str(sha)], cwd=tree, env=env)
        yield tree, env


# --- caller-repo fingerprint (Task 3.2) ------------------------------------------------
#
# sha256 over exactly: HEAD (symbolic target + sha); the worktree tree id from a
# throw-away GIT_INDEX_FILE (read-tree HEAD → add -A → write-tree: tracked, dirty
# and untracked non-ignored content; the real index is never touched); the
# watched refs (default: the ref HEAD points at); the bytes of the hooks dir and
# of core.hooksPath's target; the security config keys. Every other ref and
# config key is out of scope, so a concurrent design moving its own branches or
# writing branch.*/remote.* config never looks like a mutation [R2].

SECURITY_KEYS = (r"^(core\.(hookspath|fsmonitor|sshcommand|pager)|include\.|includeif\."
                 r"|filter\.|alias\.|diff\..*\.textconv|credential\.)")


def _git_rc(args, *, cwd, env) -> tuple[int, str]:
    """Run git where a non-zero exit is an answer (e.g. `symbolic-ref -q`)."""
    proc = subprocess.run(["git", *args], cwd=str(cwd), env=env, capture_output=True,
                          text=True, timeout=GIT_TIMEOUT)
    return proc.returncode, proc.stdout


def _worktree_tree(repo: Path, env: dict) -> str:
    with tempfile.TemporaryDirectory(prefix="certify-fp-") as tmp:
        ienv = dict(env, GIT_INDEX_FILE=str(Path(tmp) / "index"))
        git(["read-tree", "HEAD"], cwd=repo, env=ienv)
        # fsmonitor off: a probe-written core.fsmonitor must not run here.
        git(["-c", "core.fsmonitor=false", "add", "-A"], cwd=repo, env=ienv)
        return git(["write-tree"], cwd=repo, env=ienv).strip()


def _dir_bytes(path: Path) -> bytes:
    """Name + bytes of each top-level file of a hooks dir (sorted)."""
    if not path.is_dir():
        return b"<absent>"
    out = []
    for entry in sorted(path.iterdir()):
        try:
            data = entry.read_bytes() if entry.is_file() else b"<not-a-file>"
        except OSError:
            data = b"<unreadable>"
        out.append(entry.name.encode() + b"\0" + data)
    return b"\0\0".join(out)


def _hook_dirs(repo: Path, env: dict) -> list[Path]:
    dirs = [repo / git(["rev-parse", "--git-path", "hooks"], cwd=repo, env=env).strip()]
    rc, value = _git_rc(["config", "--get", "core.hooksPath"], cwd=repo, env=env)
    if rc == 0 and value.strip():
        dirs.append(repo / Path(value.strip()).expanduser())
    return list(dict.fromkeys(d.resolve() for d in dirs))


def fingerprint(repo, watch_refs=None) -> str:
    """The scoped caller-repo fingerprint (block comment above)."""
    repo = Path(repo).resolve()
    env = scrubbed_env()
    digest = hashlib.sha256()

    def part(label: str, data) -> None:
        data = data.encode() if isinstance(data, str) else data
        digest.update(f"{label}:{len(data)}:".encode() + data)

    _rc, symbolic = _git_rc(["symbolic-ref", "-q", "HEAD"], cwd=repo, env=env)
    part("head", symbolic.strip() + " " + git(["rev-parse", "HEAD"], cwd=repo, env=env))
    part("tree", _worktree_tree(repo, env))
    refs = list(watch_refs) if watch_refs else [r for r in [symbolic.strip()] if r]
    if refs:
        fmt = "--format=%(refname) %(objectname)"
        part("refs", git(["for-each-ref", fmt, *refs], cwd=repo, env=env))
    for hooks in _hook_dirs(repo, env):
        part(f"hooks {hooks}", _dir_bytes(hooks))
    _rc, config = _git_rc(["config", "--get-regexp", SECURITY_KEYS], cwd=repo, env=env)
    part("config", config)
    return digest.hexdigest()
