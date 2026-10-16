#!/usr/bin/env python3
"""forge_ssh.py — resolve an ssh-config host alias offline with `ssh -G`.

design: forge-interface (impl-audit retry; known issue L113)

An origin like `git@github-work:Acme/widget.git` names an ssh-config alias, not a
host: only `ssh -G <alias>` (which prints the effective config and opens no
connection) knows it is really `github.com`. `is_github_alias` answers that one
question and nothing else — it never accepts an arbitrary alias just because the
remote has an owner/repo path. Any failure (no `ssh`, a timeout, a non-zero exit,
output with no `hostname` line) is "no": the caller keeps today's behaviour.

Seam: `runner` (argv -> CompletedProcess-like), the same shape `forge.resolve` uses;
without one, `ssh -G` runs with a short timeout. Stdlib only.
"""
from __future__ import annotations

import subprocess

SSH_TIMEOUT = 5
# github.com's own hostnames: the alias must resolve to exactly one of these.
GITHUB_HOSTS = ("github.com", "ssh.github.com")


def _default_runner(argv):
    return subprocess.run(argv, capture_output=True, text=True, timeout=SSH_TIMEOUT)


def alias_hostname(host: str, runner=None) -> str:
    """The `hostname` `ssh -G <host>` resolves to, lower-cased, or `""` on any failure."""
    if not host or host.startswith("-"):  # never let a host read as an ssh option
        return ""
    try:
        proc = (runner or _default_runner)(["ssh", "-G", host])
    except (OSError, subprocess.SubprocessError):
        return ""
    if getattr(proc, "returncode", 1) != 0:
        return ""
    for line in (getattr(proc, "stdout", "") or "").splitlines():
        key, _, value = line.strip().partition(" ")
        if key.lower() == "hostname":
            return value.strip().lower()
    return ""


def is_github_alias(host: str, runner=None) -> bool:
    """True when ssh-config alias `host` resolves to github.com."""
    return alias_hostname(host, runner) in GITHUB_HOSTS
