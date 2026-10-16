#!/usr/bin/env python3
"""launcher_which.py — find the Homelab launcher and ask it what it would plan for a folder.

launch-role-precedence task 1.1. `launcher_home` resolves `claude` on PATH to its realpath
(`<home>/bin/claude`) and accepts it only when `<home>/lib/launcher/plan.py` exists. `which` runs
`<home>/bin/claude-which` in a folder with every launcher-made name scrubbed, so the answer is the
folder's own route, not the calling session's. Every failure returns None; nothing raises.
Stdlib only.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import launcher_env

__all__ = ["SCRUB_NAMES", "launcher_home", "scrub_env", "which", "supports_run"]

SCRUB_NAMES = (
    "CLAUDE_CONFIG_DIR", "CLAUDE_LAUNCHER_ROLE", "CLAUDE_LAUNCHER_FORCE_BACKEND",
    "CLAUDE_LAUNCHER_FORCE_PROFILE", "CLAUDE_LAUNCHER_OWNED", "ANTHROPIC_BASE_URL",
    "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL",
)
_KEYS = ("profile", "backend", "effective")
_RUN_RE = re.compile(r'^\s*RUN\s*=\s*["\']run["\']', re.MULTILINE)


def launcher_home(env: dict, which=shutil.which) -> Path | None:
    """The launcher tree `claude` on `env`'s PATH belongs to, or None for a plain `claude`."""
    try:
        path = env.get("PATH", "")
        found = which("claude", path=path)
        if not found:  # which() demands the exec bit; the tree check below is the real test
            found = next((str(Path(d) / "claude") for d in path.split(os.pathsep)
                          if d and (Path(d) / "claude").is_file()), None)
        if not found:
            return None
        home = Path(os.path.realpath(found)).parent.parent
        return home if (home / "lib" / "launcher" / "plan.py").is_file() else None
    except Exception:
        return None


def scrub_env(env: dict) -> dict:
    """`env` minus the launcher's keys, the names it owns and `SCRUB_NAMES`."""
    return {k: v for k, v in launcher_env.strip_launcher_keys(env).items()
            if k not in SCRUB_NAMES}


def which(cwd, env: dict, runner=subprocess.run, home=None) -> dict | None:
    """`claude-which` for `cwd` as {profile, backend, effective}; None on any failure."""
    try:
        home = home or launcher_home(env)
        if home is None:
            return None
        done = runner([str(Path(home) / "bin" / "claude-which")], cwd=str(cwd),
                      env=scrub_env(env), capture_output=True, text=True, timeout=15)
        if done.returncode != 0:
            return None
        out = {}
        for line in str(done.stdout).splitlines():
            key, sep, val = line.partition(":")
            if sep and key.strip() in _KEYS:
                out[key.strip()] = val.strip()
        return out or None
    except Exception:
        return None


def supports_run(home) -> bool:
    """True when the launcher's role.py defines the `run` role."""
    try:
        text = (Path(home) / "lib" / "launcher" / "role.py").read_text(encoding="utf-8")
    except Exception:
        return False
    return bool(_RUN_RE.search(text))
