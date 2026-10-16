#!/usr/bin/env python3
"""forge_gitea_agit.py — the no-token Gitea paths: AGit PR create, setup-line degrades.

design: forge-interface (Task 1.4)

A Gitea with no token still gets a real PR: `git push origin <head>:refs/for/<base>`
with `-o topic=… -o title=… -o description=…` push options needs only an SSH key, and
Gitea prints the PR it opened in the push's `remote:` output — that URL (and its
number) is what an `ok` result returns. The push is **idempotent per topic**: re-running
it for the same `head` re-pushes `refs/for/<base>` with the same topic, updating the
same PR, so no branch delete and no fresh topic is ever needed. Because whether a plain
later push moves the PR head is unverified on the live instance, every AGit `ok`
carries the visible note to re-run `forge.py pr-create` to update the PR.

Git refuses a newline in a push option, so the body is flattened to one line (and
capped); when that happens the `ok` note says so, and a cut says "truncated", rather
than silently dropping the shape of the description. AGit has no reviewer slot, so a
requested reviewer is a visible no-op in the note, as on the REST path. A failed push — non-zero, or zero with no `/pulls/<n>` URL,
or no `git` at all — degrades with a **Gitea compare URL built from `web_base`**, never
a github.com one: on a Gitea behind an ssh alias on a custom port, only `web_base` knows
the real instance and port. Comment / comment-edit / label ops have no no-token path at
all, so they degrade with `forge_gitea.setup_line` naming both ways to supply a token.
Seam: `runner` (argv -> CompletedProcess-like) and `repo`. Stdlib only.
"""
from __future__ import annotations

import re
import subprocess

from forge import ForgeInfo, Result
from forge_gitea import setup_line

# git's own limit is generous; 1000 chars keeps one push option readable on a terminal.
DESCRIPTION_CAP = 1000

# Gitea answers an AGit push with the PR it opened, on a `remote:` line.
_PR_URL_RE = re.compile(r"https?://\S+/pulls/(\d+)")

RERUN_NOTE = "later pushes: re-run `forge.py pr-create` to update the PR"
FLATTEN_NOTE = "description flattened (AGit push options are single-line)"
TRUNCATE_NOTE = f"description truncated to {DESCRIPTION_CAP} chars"
REVIEWER_NOTE = "reviewers not requested on Gitea"


def compare_url(info: ForgeInfo, base: str, head: str) -> str:
    """Gitea's own "open a comparison for this" URL — from `web_base`, not the ssh host."""
    return f"{info.web_base}/{info.owner}/{info.repo}/compare/{base}...{head}"


def no_token(op: str, info: ForgeInfo) -> Result:
    """The one visible answer for an op Gitea has no no-token path for."""
    return Result.degraded(f"{op}: {setup_line(info.web_base)}")


def _description(body: str) -> tuple:
    """`(push option value, was flattened, was truncated)` — one line, capped.

    Only the line breaks are collapsed (each, with its surrounding whitespace,
    becomes one space); text inside a line keeps its own spacing.
    """
    flat = re.sub(r"\s*\n\s*", " ", body or "").strip()
    return flat[:DESCRIPTION_CAP], "\n" in (body or ""), len(flat) > DESCRIPTION_CAP


def _notes(flattened: bool, truncated: bool, reviewers) -> str:
    """AGit `ok` notes, joined with `; ` — the re-run note is always there."""
    return "; ".join(([FLATTEN_NOTE] if flattened else [])
                     + ([TRUNCATE_NOTE] if truncated else [])
                     + ([REVIEWER_NOTE] if reviewers else []) + [RERUN_NOTE])


def _detail(proc) -> str:
    """Why the push did not open a PR: its first line, or its exit code."""
    for line in ((getattr(proc, "stderr", "") or "").splitlines()
                 + (getattr(proc, "stdout", "") or "").splitlines()):
        if line.strip():
            return line.strip()
    return f"exit {getattr(proc, 'returncode', '?')}"


def _degraded(info: ForgeInfo, base: str, head: str, detail: str) -> Result:
    return Result.degraded(
        f"AGit PR create failed ({detail}) — open it by hand: "
        f"{compare_url(info, base, head)}")


def pr_create_agit(info: ForgeInfo, *, base: str, head: str, title: str, body: str,
                   reviewers=None, runner=None, repo=None) -> Result:
    """Open (or update) a PR with one AGit push: `{url, number}` or a compare URL."""
    desc, flattened, truncated = _description(body)
    argv = ["git", "push", "origin", f"{head}:refs/for/{base}",
            "-o", f"topic={head}", "-o", f"title={title}",
            "-o", f"description={desc}"]
    # `cwd` belongs to the default runner only: an injected seam is argv -> proc,
    # like every other forge helper's, so a fake never has to accept kwargs.
    run = runner or (lambda argv: subprocess.run(argv, capture_output=True,
                                                 text=True, cwd=repo))
    try:
        proc = run(argv)
    except (FileNotFoundError, OSError):
        return _degraded(info, base, head, "git not found")
    found = _PR_URL_RE.search(f"{getattr(proc, 'stdout', '') or ''}"
                              f"\n{getattr(proc, 'stderr', '') or ''}")
    if proc.returncode != 0 or found is None:
        return _degraded(info, base, head, _detail(proc))
    return Result.ok({"url": found.group(0), "number": int(found.group(1))},
                     _notes(flattened, truncated, reviewers))
