"""proof_root — the one resolver for the /tp-pr-iterate proof root.

design: review-proof-out-of-tree (Tasks 1.1-1.2)

The proof root holds `rounds/<pr>/r<N>/` (manifest, angle replies, tail envelope),
the per-head proof artifacts and `iterate-state.v1.json`. Its manifests carry
absolute machine paths, so it lives OUTSIDE the working tree by default:

- default: `<git rev-parse --absolute-git-dir>/three-pillars/review-proof`, per
  worktree (a linked worktree's git-dir is `<main>/.git/worktrees/<name>`);
- `TP_REVIEW_PROOF_DIR` (uncommitted env): an absolute root, used as-is, shared
  by every worktree that sets it; it wins over the config key (a relative value
  is refused with a stderr notice and resolution goes on as if it were unset);
- `review.proof_dir` in `.three-pillars/config.json`: RELATIVE only, against the
  worktree toplevel (the file is committed; an absolute value, or one resolving
  outside the worktree such as `../x`, is refused with a stderr notice and the
  default is used);
- outside git: the old `<start>/.three-pillars/review-proof`.

`resolve_proof_root` is pure (no filesystem mutation); `default_proof_root` also
runs the one-time `migrate_legacy` move of an in-tree legacy dir (idempotent,
fail-open, never deletes data). This is the ONLY module
that names the proof-root directory; every caller goes through it.

CLI: `python3 proof_root.py [--no-migrate]` prints the (migrated) root — the
prose's single way to get `<proof_root>`. Stdlib only.
"""

from __future__ import annotations

import argparse
import errno
import os
import shutil
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SHARED = _HERE.parents[1] / "_shared"
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

ENV_VAR = "TP_REVIEW_PROOF_DIR"
ROOT_PARTS = ("three-pillars", "review-proof")  # under the absolute git-dir
LEGACY_PARTS = (".three-pillars", "review-proof")  # under the worktree toplevel


def _default_run_git(args: list[str]) -> tuple[int, str, str]:
    try:
        r = subprocess.run(args, capture_output=True, text=True, check=False)
    except OSError as exc:  # git missing
        return 127, "", str(exc)
    return r.returncode, r.stdout, r.stderr


def _git_locate(start, run_git) -> "tuple[Path, Path] | None":
    """→ (absolute git-dir, worktree toplevel), or None outside a work tree."""
    cwd = Path(start) if start is not None else Path.cwd()
    rc, out, _err = (run_git or _default_run_git)(
        ["git", "-C", str(cwd), "rev-parse", "--absolute-git-dir", "--show-toplevel"])
    lines = [ln.strip() for ln in (out or "").splitlines() if ln.strip()]
    if rc != 0 or len(lines) < 2:
        return None
    return Path(lines[0]), Path(lines[1])


def _load_config(toplevel: Path) -> dict:
    """The repo config, fail-open: any failure → `{}` (the default applies)."""
    try:
        from repo_config_load import load_repo_config
        cfg = load_repo_config(toplevel).config
    except Exception:  # noqa: BLE001 — fail-open by contract
        return dict()
    return cfg if isinstance(cfg, dict) else dict()


def _config_override(config, toplevel: Path, err) -> "Path | None":
    review = config.get("review") if isinstance(config, dict) else None
    value = review.get("proof_dir") if isinstance(review, dict) else None
    if not isinstance(value, str) or not value.strip():
        return None
    if os.path.isabs(value):
        err.write(f"proof_root: review.proof_dir must be relative (the config is "
                  f"committed); ignoring {value!r}, using the default\n")
        return None
    root = Path(os.path.normpath(toplevel / value))
    if root != Path(toplevel) and Path(toplevel) not in root.parents:
        err.write(f"proof_root: review.proof_dir must stay inside the worktree; "
                  f"ignoring {value!r}, using the default\n")
        return None
    return root


def locate(start=None, config=None, *, run_git=None, env=None,
           err=None) -> "tuple[Path, Path | None]":
    """→ (proof root, worktree toplevel or None outside git). Pure."""
    err = err if err is not None else sys.stderr
    env = os.environ if env is None else env
    found = _git_locate(start, run_git)
    top = found[1] if found else None
    base = top if top is not None else (Path(start) if start is not None else Path.cwd())
    override = (env.get(ENV_VAR) or "").strip()
    if override and os.path.isabs(override):
        return Path(override), top
    if override:
        _notice(err, f"{ENV_VAR} must be an absolute path; ignoring {override!r}")
    if found is None:
        return base.absolute().joinpath(*LEGACY_PARTS), None
    gitdir, top = found
    cfg = _load_config(top) if config is None else config
    return (_config_override(cfg, top, err) or gitdir.joinpath(*ROOT_PARTS)), top


def resolve_proof_root(start=None, config=None, *, run_git=None, env=None, err=None) -> Path:
    """The proof root for the worktree containing `start` (default cwd). Pure.

    `config=None` loads the repo config fail-open (a missing or malformed file →
    the default). `run_git(args) -> (rc, stdout, stderr)` is the test seam.
    """
    return locate(start, config, run_git=run_git, env=env, err=err)[0]


def _notice(err, msg: str) -> None:
    err.write(f"proof_root: {msg}\n")


def _staged_copy(src: Path, new: Path) -> None:
    """Copy `src` into `<new>.migrating-<pid>`, then rename that into place.

    On any failure only the staging dir is removed and the error re-raised, so
    the new root is never half-created.
    """
    staging = new.with_name(f"{new.name}.migrating-{os.getpid()}")
    try:
        shutil.copytree(src, staging, symlinks=True)
        os.rename(staging, new)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def migrate_legacy(worktree_root, new_root, *, err=None) -> Path:
    """Move an in-tree legacy proof dir to `new_root` once. → the root to use.

    No-op when the legacy root is absent or IS the new root. New root present →
    both left, one notice. A real dir → `os.rename`, or (cross-device) a staged
    copy renamed into place, then the legacy dir removed. A symlink to a dir →
    its target's contents copied the same way, the link unlinked, the target kept
    (other worktrees may share it). A dangling link → left, with a notice. Any
    failure → only the staging dir removed, the new root never created, and the
    LEGACY root returned for this call (the next call retries). Never raises.
    """
    err = err if err is not None else sys.stderr
    legacy, new = Path(worktree_root).joinpath(*LEGACY_PARTS), Path(new_root)
    if not os.path.lexists(legacy) or os.path.realpath(legacy) == os.path.realpath(new):
        return new
    if os.path.lexists(new):
        _notice(err, f"{new} already exists; leaving the legacy {legacy} untouched")
        return new
    link = os.path.islink(legacy)
    src = Path(os.path.realpath(legacy)) if link else legacy
    if not src.is_dir():
        _notice(err, f"legacy {legacy} is a dangling symlink or not a directory; left in place")
        return new
    try:
        new.parent.mkdir(parents=True, exist_ok=True)
        if link:
            _staged_copy(src, new)
        else:
            try:
                os.rename(legacy, new)
                return new
            except OSError as exc:
                if exc.errno != errno.EXDEV:
                    raise
            _staged_copy(legacy, new)
    except OSError as exc:
        _notice(err, f"could not move {legacy} to {new} ({exc}); using the legacy root this call")
        return legacy
    try:  # the copy is in place: drop the link (not data) or the legacy real dir
        if link:
            os.unlink(legacy)
        else:
            shutil.rmtree(legacy)
    except OSError as exc:
        _notice(err, f"moved to {new}, but could not remove {legacy} ({exc})")
    return new


def default_proof_root(start=None, *, err=None) -> Path:
    """Resolve the proof root, then run the one-time legacy migration (idempotent)."""
    root, top = locate(start, err=err)
    return root if top is None else migrate_legacy(top, root, err=err)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Print the /tp-pr-iterate proof root.")
    ap.add_argument("--no-migrate", action="store_true",
                    help="resolve only; never move a legacy in-tree proof dir")
    a = ap.parse_args(argv)
    print(resolve_proof_root() if a.no_migrate else default_proof_root())
    return 0


if __name__ == "__main__":
    sys.exit(main())
