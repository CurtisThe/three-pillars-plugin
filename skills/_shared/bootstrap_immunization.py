"""bootstrap_immunization.py — seat immunization installer.

Installs the `heal-core-bare.sh` hook into a repo's .git/hooks/ via
sentinel-guarded append and sets extensions.worktreeConfig=true to prevent
the harness core.bare bleed from affecting the shared .git/config.

Key design invariants:
  - NEVER auto-runs.  Only called by a consenting surface (first-run offer
    or explicit seat-repair acceptance via the worktree management skill's
    `seat --apply` command).
  - Idempotent: re-apply changes nothing if the sentinel is already present.
  - Non-clobbering: appends to existing hook files; never overwrites.
  - Heal hook is a no-op on healthy repos (only flips on the bleed state).
  - Config record mirrors `branch_protection` shape:
      {offered_at, applied_at (ISO|null), declined (bool)}
  - Hooks are resolved via git rev-parse --git-common-dir so that
    linked-worktree invocations install into the SEAT's real hooks dir.

Public API:
  status(repo) -> dict   -- {worktree_config: bool, heal_hooks: bool}
  apply(repo)            -- installs the hook(s) + sets extensions.worktreeConfig
  cheap_check(repo)      -- 'skip-decided' | 'needs-prompt'
  mark_applied(repo)     -- write applied_at timestamp to config
  mark_declined(repo)    -- write declined=true to config
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SENTINEL_BEGIN = "# three-pillars: heal-core-bare BEGIN"
SENTINEL_END = "# three-pillars: heal-core-bare END"

# Git hook events where the heal script fires.
HOOK_EVENTS = ("post-checkout", "post-merge")

# Path to the heal script relative to this file.
_HERE = Path(__file__).parent
_HEAL_SCRIPT = _HERE / "hooks" / "heal-core-bare.sh"

_CONFIG_KEY = "worktree_immunization"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _now_iso_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _git_common_dir(repo: Path) -> Optional[Path]:
    """Return the git common dir (seat's .git) via git rev-parse --git-common-dir.

    For a linked worktree, this resolves to the SEAT's real .git directory,
    not the per-worktree .git/worktrees/<name>/ path.  This is the directory
    where hooks/ lives and where git actually looks for hook scripts.
    """
    result = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    path = result.stdout.strip()
    if not path:
        return None
    # May be relative — resolve against repo
    p = Path(path)
    if not p.is_absolute():
        p = (repo / p).resolve()
    return p


def _hooks_dir(repo: Path) -> Optional[Path]:
    """Return the hooks directory via git rev-parse --git-path hooks.

    Uses --git-path hooks which honours both core.hooksPath overrides AND the
    common-dir (for linked worktrees), so callers install into the directory
    that git will actually consult — not a dead per-worktree path or an
    unmanaged fallback when core.hooksPath points to a manager-owned dir.

    NOTE: if core.hooksPath is set (e.g. by husky), --git-path hooks resolves
    to that managed directory.  We install into it unconditionally; operators
    using hook managers that do NOT tolerate appended content should be aware
    that the sentinel-guarded block will be appended to whatever file git-path
    resolves to.  The sentinel check ensures re-apply is idempotent.
    """
    result = subprocess.run(
        ["git", "rev-parse", "--git-path", "hooks"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    path = result.stdout.strip()
    if not path:
        return None
    p = Path(path)
    if not p.is_absolute():
        p = (repo / p).resolve()
    return p


def _hook_has_sentinel(hook_file: Path) -> bool:
    """Return True if the hook file already contains our sentinel.

    Reads bytes with errors='replace' to tolerate binary/non-UTF-8 hooks.
    """
    if not hook_file.exists():
        return False
    try:
        content = hook_file.read_bytes().decode("utf-8", errors="replace")
    except OSError:
        return False
    return SENTINEL_BEGIN in content


def _append_hook(hook_file: Path, heal_content: str) -> None:
    """Append the sentinel-guarded heal block to a hook file.

    Creates the file with a shebang if it does not exist yet.
    Never clobbers existing hook content — only appends.
    Idempotent: does nothing if the sentinel is already present.
    """
    if _hook_has_sentinel(hook_file):
        return  # already installed — idempotent

    if not hook_file.exists():
        hook_file.write_text("#!/usr/bin/env bash\n")
        hook_file.chmod(0o755)

    with hook_file.open("a") as f:
        f.write(f"\n{SENTINEL_BEGIN}\n")
        f.write(heal_content)
        f.write(f"\n{SENTINEL_END}\n")

    # Ensure the hook is executable
    hook_file.chmod(hook_file.stat().st_mode | 0o111)


def _extensions_worktree_config_set(repo: Path) -> bool:
    """Return True if extensions.worktreeConfig is set to true in .git/config."""
    result = subprocess.run(
        ["git", "config", "--local", "extensions.worktreeConfig"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and result.stdout.strip().lower() == "true"


def _is_worktree_git_file(repo: Path) -> bool:
    """Return True if the invoking worktree's .git is a file (linked worktree)."""
    git_path = repo / ".git"
    return git_path.is_file()


def _shared_config_has_bare_true(repo: Path) -> bool:
    """Return True if the shared .git/config has core.bare=true."""
    result = subprocess.run(
        ["git", "config", "--local", "core.bare"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and result.stdout.strip().lower() == "true"


def _heal_core_bare(repo: Path) -> None:
    """Heal the core.bare=true bleed: set core.bare=false in the shared config."""
    subprocess.run(
        ["git", "config", "--local", "core.bare", "false"],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def _heal_hooks_installed(repo: Path) -> bool:
    """Return True if ALL HOOK_EVENTS have the sentinel present."""
    hooks = _hooks_dir(repo)
    if hooks is None:
        return False
    for event in HOOK_EVENTS:
        hook_file = hooks / event
        if not _hook_has_sentinel(hook_file):
            return False
    return True


def _read_config(repo: Path) -> dict:
    """Read the .three-pillars/config.json file.

    Raises RuntimeError on corrupt/unreadable config rather than silently
    replacing it with defaults (which would clobber existing migration and
    branch_protection records, causing re-prompts for settled decisions).
    Returns {'schema_version': 1} only when the file does not exist yet.
    """
    config_path = repo / ".three-pillars" / "config.json"
    if not config_path.exists():
        return {"schema_version": 1}
    try:
        return json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(
            f"Corrupt config at {config_path}: {exc}. "
            "Fix or remove the file manually — never auto-rewriting to prevent "
            "clobbering existing migration and branch_protection records."
        ) from exc
    except OSError as exc:
        raise RuntimeError(
            f"Cannot read config at {config_path}: {exc}."
        ) from exc


def _atomic_write_config(repo: Path, data: dict) -> None:
    config_path = repo / ".three-pillars" / "config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        dir=config_path.parent,
        prefix=".config.",
        suffix=".tmp",
        delete=False,
    )
    try:
        json.dump(data, tmp, indent=2)
        tmp.write("\n")
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp.close()
        os.replace(tmp.name, config_path)
    except Exception:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def status(repo: Path) -> dict:
    """Return immunization status for the repo.

    Returns: {worktree_config: bool, heal_hooks: bool}

    Exits 0 always (documented contract).  If the config file is corrupt,
    returns {"error": "<message>", "worktree_config": False, "heal_hooks": False}
    so callers can detect the error key without relying on a non-zero exit.
    """
    try:
        return {
            "worktree_config": _extensions_worktree_config_set(repo),
            "heal_hooks": _heal_hooks_installed(repo),
        }
    except RuntimeError as exc:
        return {
            "error": str(exc),
            "worktree_config": False,
            "heal_hooks": False,
        }


def apply(repo: Path) -> None:
    """Install the heal hook(s) and set extensions.worktreeConfig=true.

    Idempotent: re-apply is safe and changes nothing if already installed.
    This function MUST only be called by a consenting surface.

    Pre-check: if the shared config has core.bare=true AND the repo has a
    .git entry (file or directory), heal core.bare=false FIRST.  A genuine
    bare clone has NO .git entry at all, so `(repo / '.git').exists()` is
    false there — this guard is therefore safe.  Enabling
    extensions.worktreeConfig while core.bare=true would break all worktrees
    on the next git operation regardless of whether the invoker is on a
    linked worktree or on the seat itself.

    Hooks are installed via git rev-parse --git-path hooks which honours
    core.hooksPath overrides and the common-dir for linked worktrees.
    extensions.worktreeConfig is set via git config --local from any worktree
    (which already writes to the shared .git/config — verified).
    """
    # 0. Pre-check: heal core.bare=true bleed before enabling worktreeConfig.
    # Condition: core.bare=true AND a .git entry exists (file or dir).
    # A genuine bare clone has no .git entry, so this is safe for bare repos.
    if _shared_config_has_bare_true(repo) and (repo / ".git").exists():
        _heal_core_bare(repo)
        print(
            "bootstrap_immunization: healed core.bare=true bleed before "
            "enabling extensions.worktreeConfig",
            file=__import__("sys").stderr,
        )

    # 1. Set extensions.worktreeConfig=true (isolates per-worktree config)
    subprocess.run(
        ["git", "config", "--local", "extensions.worktreeConfig", "true"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    # 2. Install heal hook into each event hook file
    hooks = _hooks_dir(repo)
    if hooks is None:
        raise RuntimeError(f"No git hooks directory found in {repo}")
    hooks.mkdir(parents=True, exist_ok=True)

    # Read the heal script body from the tracked copy
    heal_body = _HEAL_SCRIPT.read_text(encoding="utf-8")

    for event in HOOK_EVENTS:
        hook_file = hooks / event
        _append_hook(hook_file, heal_body)


def cheap_check(repo: Path) -> str:
    """Check whether the immunization offer should be skipped or shown.

    Returns:
      'skip-decided' — already applied or explicitly declined (never re-ask)
      'needs-prompt'  — not yet offered/decided
    """
    data = _read_config(repo)
    wi = data.get(_CONFIG_KEY, {})
    if wi.get("applied_at") or wi.get("declined"):
        return "skip-decided"
    return "needs-prompt"


def mark_applied(repo: Path) -> None:
    """Record that immunization was applied.  Writes applied_at timestamp."""
    data = _read_config(repo)
    wi = data.setdefault(_CONFIG_KEY, {})
    wi.setdefault("offered_at", _now_iso_utc())
    wi["applied_at"] = _now_iso_utc()
    wi["declined"] = False
    _atomic_write_config(repo, data)


def mark_declined(repo: Path) -> None:
    """Record that the user declined immunization.  Permanently suppresses reprompt."""
    data = _read_config(repo)
    wi = data.setdefault(_CONFIG_KEY, {})
    wi.setdefault("offered_at", _now_iso_utc())
    wi["applied_at"] = None
    wi["declined"] = True
    _atomic_write_config(repo, data)


def mark_offered(repo: Path) -> None:
    """Record that the offer was shown (before user response)."""
    data = _read_config(repo)
    wi = data.setdefault(_CONFIG_KEY, {})
    if not wi.get("offered_at"):
        wi["offered_at"] = _now_iso_utc()
    _atomic_write_config(repo, data)


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI for bootstrap_immunization.

    Usage:
      python3 bootstrap_immunization.py status [--repo <path>]
      python3 bootstrap_immunization.py apply  [--repo <path>]
      python3 bootstrap_immunization.py --repo <path> status
      python3 bootstrap_immunization.py --repo <path> apply

    ``status`` prints a JSON object with the immunization state (as returned
    by ``status()``) plus the ``cheap_check`` verdict.  Exits 0 always.

    ``apply`` installs extensions.worktreeConfig=true and the heal hooks,
    then calls ``mark_applied()``.  It does NOT prompt — callers are
    responsible for obtaining consent before invoking this subcommand.
    Exits 0 on success, 1 on error.
    """
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="Bootstrap immunization helper (seat protect against core.bare bleed).",
    )
    parser.add_argument(
        "--repo",
        default=None,
        help="Path to the repo root (default: current directory).",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    status_p = sub.add_parser("status", help="Print immunization status as JSON.")
    status_p.add_argument(
        "--repo",
        default=None,
        dest="sub_repo",
        help="Path to the repo root (overrides top-level --repo).",
    )
    apply_p = sub.add_parser(
        "apply",
        help="Install immunization (no prompt — caller must obtain consent first).",
    )
    apply_p.add_argument(
        "--repo",
        default=None,
        dest="sub_repo",
        help="Path to the repo root (overrides top-level --repo).",
    )
    args = parser.parse_args()

    # Subcommand --repo overrides top-level --repo; fall back to "."
    repo_str = getattr(args, "sub_repo", None) or args.repo or "."
    repo = Path(repo_str).resolve()

    if args.command == "status":
        import json as _json
        result = status(repo)
        # cheap_check also reads config; catch its RuntimeError too
        try:
            result["cheap_check"] = cheap_check(repo)
        except RuntimeError as exc:
            result["cheap_check"] = "error"
            result.setdefault("error", str(exc))
        print(_json.dumps(result))
        sys.exit(0)

    if args.command == "apply":
        try:
            apply(repo)
            mark_applied(repo)
            sys.exit(0)
        except Exception as exc:  # pragma: no cover
            print(f"error: {exc}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
