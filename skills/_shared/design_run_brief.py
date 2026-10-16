"""design_run_brief.py — write and commit the design run's seat brief.

The seat used to re-state the same launch preferences on every design run, from a brief in
`/tmp`. The brief now lives in the design dir on `tp/<slug>` (`seat-brief.md`), committed, so
the standing rulings are durable and reviewable; the launcher types one line telling the run
to read it. Source precedence: an explicit `--brief` file > an existing design-dir file (the
seat may have appended to it) > the repo's `.three-pillars/seat-brief.md` > the shipped
`seat-brief-template.md`. `{slug}` and `{busy_line}` are substituted; `{busy_line}` renders from
the active busy policy (`strata_spawn.busy_policy`), so a `wait` repo never gets the Sonnet-fallback
line. A source without the placeholder (a repo or `--brief` file) is written unchanged. Committing
is fail-open: a failed commit or push prints one line and the launch continues
(design-run-launch.md).
"""
from __future__ import annotations

import os
import subprocess
from typing import Callable, Optional, Sequence

import strata_spawn

FIRST_LINE = "Seat (under operator delegation): read seat-brief.md and follow it"
BRIEF_NAME = "seat-brief.md"
TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seat-brief-template.md")

BUSY_LINES = {
    "wait": "A busy local slot means wait for the slot; never fall back to Sonnet.",
    "fallback": "A busy local slot falls back to Sonnet immediately; do not wait for it.",
}


def busy_line(policy: Optional[str] = None) -> str:
    """The routing line for `policy`, resolved from config/env when `None`."""
    if policy is None:
        policy = strata_spawn.busy_policy(strata_spawn._raw_config(None), None, os.environ)
    return BUSY_LINES.get(policy, BUSY_LINES["fallback"])

GitRunner = Callable[[Sequence[str], str], "tuple[int, str]"]


def _git(args: Sequence[str], cwd: str) -> "tuple[int, str]":
    try:
        proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                              encoding="utf-8")
    except OSError as exc:
        return 1, str(exc)
    return proc.returncode, (proc.stdout if proc.returncode == 0 else proc.stderr).strip()


def brief_path(wt: str, slug: str) -> str:
    return os.path.join(wt, "three-pillars-docs", "tp-designs", slug, BRIEF_NAME)


def pick_source(wt: str, slug: str, brief: Optional[str], repo_root: str) -> "tuple[str, str]":
    """`(source name, file path)` of the brief that applies."""
    if brief:
        return "--brief", brief
    existing = brief_path(wt, slug)
    if os.path.isfile(existing):
        return "design-dir", existing
    override = os.path.join(repo_root, ".three-pillars", BRIEF_NAME)
    if os.path.isfile(override):
        return "repo", override
    return "template", TEMPLATE


def write_brief(wt: str, slug: str, brief: Optional[str] = None, *, repo_root: str,
                warn: Optional[Callable[[str], None]] = None,
                busy_policy: Optional[str] = None) -> "tuple[str, bool, str]":
    """Write the brief into the design dir; returns `(path, changed, source)`.

    An existing design-dir file is kept byte-identical (`changed` False). When `--brief`
    replaces an existing file with different content, `warn` gets one `warning:` line (the
    seat may have appended to the old file). Raises OSError
    when the chosen source cannot be read or the design dir cannot be written."""
    source, src = pick_source(wt, slug, brief, repo_root)
    dest = brief_path(wt, slug)
    if source == "design-dir":
        return dest, False, source
    with open(src, encoding="utf-8") as fh:
        text = fh.read().replace("{slug}", slug).replace("{busy_line}", busy_line(busy_policy))
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    old = None
    if os.path.isfile(dest):
        with open(dest, encoding="utf-8") as fh:
            old = fh.read()
    if old is not None and old != text and warn:
        warn(f"warning: replacing existing {BRIEF_NAME} with differing content from {src}")
    if old != text:
        with open(dest, "w", encoding="utf-8") as fh:
            fh.write(text)
    return dest, old != text, source


def commit_brief(wt: str, slug: str, path: str, push: Optional[GitRunner] = None,
                 run: GitRunner = _git) -> str:
    """Commit `path` alone (`docs(<slug>): seat brief`, no trailer) and push fail-open.

    Returns a line to print: "" when the file is already committed unchanged, a
    `not committed: …` line when git refused, else the commit (and any push failure).
    `push` defaults to `run`; both are injectable so tests never reach a remote."""
    rel = os.path.relpath(path, wt)
    rc, out = run(["status", "--porcelain", "--", rel], wt)
    if rc == 0 and not out.strip():
        return ""
    rc, out = run(["add", "--", rel], wt)
    if rc == 0:
        rc, out = run(["commit", "-q", "-m", f"docs({slug}): seat brief", "--", rel], wt)
    if rc != 0:
        return f"not committed: {out.splitlines()[-1] if out else 'git commit failed'}"
    _, sha = run(["rev-parse", "--short", "HEAD"], wt)
    line = f"seat brief committed ({sha})"
    prc, pout = (push or run)(["push", "-q", "origin", f"tp/{slug}"], wt)
    if prc != 0:
        line += f"; push failed (kept local): {pout.splitlines()[-1] if pout else 'unknown'}"
    return line
