"""design_run_command.py — shared builder for a top-level design-run window.

Single source of truth for the shell command that starts an autonomous
`/tp-run-full-design` run as a fresh top-level `claude` session (never a
subagent). Every launching path builds its command from these helpers so the
marker env var, the profile passthrough, and the model pin cannot drift.

Pure string builders plus one side effect: `pretrust()`, which marks a
worktree as trusted in the profile's `.claude.json` so the new session does
not stop at the trust dialog.

CLI:
    python3 design_run_command.py pretrust <worktree> [--config-dir DIR]
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import shlex
import sys
import tempfile
from typing import Mapping, Optional, Sequence, Tuple

MARKER = "TP_DESIGN_RUN"
DEFAULT_MODEL = "opus"
_SLUG_RE = re.compile(r"^[a-z0-9-]+$")


def resolve_config_dir(env: Mapping[str, str]) -> Tuple[Optional[str], Optional[str]]:
    """Return (config_dir, warning). Warning is set when CLAUDE_CONFIG_DIR is unset."""
    cfg = env.get("CLAUDE_CONFIG_DIR") or None
    if cfg:
        return cfg, None
    return None, (
        "warning: CLAUDE_CONFIG_DIR is unset; the new session will use the "
        "default profile (~/.claude.json)"
    )


def env_prefix(config_dir: Optional[str]) -> str:
    """Env assignments (with trailing space) placed right before `claude`."""
    prefix = f"{MARKER}=1 "
    if config_dir:
        prefix += f"CLAUDE_CONFIG_DIR={shlex.quote(config_dir)} "
    return prefix


def _require_slug(slug: str) -> str:
    if not isinstance(slug, str) or not _SLUG_RE.match(slug):
        raise ValueError(f"invalid design slug {slug!r}; must match [a-z0-9-]+")
    return slug


def _require_model(model: str) -> str:
    if not model or "fable" in model.lower():
        raise ValueError(f"model {model!r} is not allowed for a design run")
    return model


def slash_command(slug: str, mode: Optional[str] = None, skip_design: bool = False,
                  local: bool = False) -> str:
    """The `/tp-run-full-design` invocation typed into the new session."""
    parts = ["/tp-run-full-design", _require_slug(slug)]
    if mode:
        parts += ["--mode", mode]
    if skip_design:
        parts.append("--skip-design")
    if local:
        parts.append("--local")
    return " ".join(parts)


def window_command(
    slug: str,
    worktree: str,
    *,
    mode: Optional[str] = None,
    skip_design: bool = False,
    config_dir: Optional[str] = None,
    model: str = DEFAULT_MODEL,
    local: bool = False,
) -> str:
    """Full shell command for a tmux window (or manual paste)."""
    model = _require_model(model)
    slash = slash_command(slug, mode=mode, skip_design=skip_design, local=local)
    return (
        f"cd {shlex.quote(worktree)} && {env_prefix(config_dir)}"
        f"claude --model {shlex.quote(model)} {shlex.quote(slash)}; exec bash"
    )


def claude_json_path(config_dir: Optional[str], home: Optional[str] = None) -> str:
    """Profile `.claude.json`: `$CLAUDE_CONFIG_DIR/.claude.json` or `~/.claude.json`."""
    if config_dir:
        return os.path.join(config_dir, ".claude.json")
    return os.path.join(home or os.path.expanduser("~"), ".claude.json")


def pretrust(worktree: str, config_dir: Optional[str]) -> str:
    """Merge `hasTrustDialogAccepted: true` for worktree into the profile file.

    Every other key and project entry is preserved. The write is atomic
    (temp file in the same directory, then os.replace) and serialized by an
    exclusive flock on a `<path>.tp-pretrust.lock` sidecar held across
    load -> merge -> replace, so concurrent calls never lose entries.
    Returns the path.
    """
    path = claude_json_path(config_dir)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path + ".tp-pretrust.lock", "a", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _pretrust_locked(path, os.path.abspath(worktree))


def _pretrust_locked(path: str, wt: str) -> str:
    data: dict = {}
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    projects = data.setdefault("projects", {})
    entry = projects.setdefault(wt, {})
    entry["hasTrustDialogAccepted"] = True
    folder = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(prefix=".claude.json.", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return path


def pretrust_shell_line(worktree: str, config_dir: Optional[str]) -> str:
    """Shell line that runs this module's `pretrust` subcommand."""
    mod = os.path.abspath(__file__)
    line = f"python3 {shlex.quote(mod)} pretrust {shlex.quote(worktree)}"
    if config_dir:
        line += f" --config-dir {shlex.quote(config_dir)}"
    return line


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pretrust", help="mark a worktree trusted in .claude.json")
    p.add_argument("worktree")
    p.add_argument("--config-dir", default=None)
    args = parser.parse_args(argv)
    if args.cmd == "pretrust":
        print(pretrust(args.worktree, args.config_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
