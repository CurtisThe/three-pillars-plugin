"""fragility_diff.py — the lines a git diff adds, read from its hunk headers.

design: fragile-test-prevention (detailed-design-lint §Scoping and exit codes)

`added_lines(root, base, head=None, *, cached=False)` runs `git diff -U0` and
returns `{path: {line numbers}}` for the new side of the diff. Only the closed
`@@ -a,b +c,d @@` header grammar is read, never the line bodies: a `+c,d` hunk
adds lines c..c+d-1, a bare `+c` adds one line, `+c,0` adds none. Three modes:
`base...head` (commit), `--cached base` (index), or `base` against the
worktree. A binary file has no hunks and a renamed-away path has no `+++` side,
so neither gets lines. A git failure raises `DiffUnavailable`.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
_ESCAPES = {"a": 7, "b": 8, "f": 12, "n": 10, "r": 13, "t": 9, "v": 11}


class DiffUnavailable(RuntimeError):
    """git could not produce the diff (bad ref, not a repo, git missing): exit 2."""


def _unquote(text: str) -> str:
    """Decode a git C-quoted path (the text between the double quotes)."""
    out, i = bytearray(), 0
    while i < len(text):
        if text[i] != "\\":
            out += text[i].encode("utf-8", "surrogateescape")
            i += 1
        elif text[i + 1 : i + 2].isdigit():
            out.append(int(text[i + 1 : i + 4], 8))
            i += 4
        else:
            out.append(_ESCAPES.get(text[i + 1], ord(text[i + 1])))
            i += 2
    return out.decode("utf-8", "replace")


def _new_path(rest: str) -> str | None:
    """The path on a `+++ ` header line, or None for a deleted file."""
    if rest.startswith('"'):
        rest = _unquote(rest.rstrip("\t")[1:-1])
    elif rest.endswith("\t"):
        rest = rest[:-1]
    if rest == "/dev/null" or not rest.startswith("b/"):
        return None
    return rest[2:]


def parse_added(diff_text: str) -> dict[str, set[int]]:
    """Added line numbers per new path from `git diff -U0 --dst-prefix=b/` text."""
    found: dict[str, set[int]] = {}
    path: str | None = None
    in_hunks = False
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            path, in_hunks = None, False
        elif in_hunks is False and line.startswith("+++ "):
            path = _new_path(line[4:])
        elif (match := _HUNK.match(line)) and path is not None:
            in_hunks = True
            start = int(match.group(1))
            count = 1 if match.group(2) is None else int(match.group(2))
            if count:
                found.setdefault(path, set()).update(range(start, start + count))
        elif line.startswith("@@ "):
            in_hunks = True
    return found


def added_lines(
    root: str | Path, base: str, head: str | None = None, *, cached: bool = False
) -> dict[str, set[int]]:
    """Added line numbers per new path; raises `DiffUnavailable` on a git failure."""
    if cached and head is not None:
        raise DiffUnavailable("cached and head are mutually exclusive")
    if any(ref.startswith("-") for ref in (base, head or "")):
        raise DiffUnavailable(f"refusing a ref that looks like an option: {base!r} {head!r}")
    spec = ["--cached", base] if cached else [f"{base}...{head}" if head else base]
    cmd = ["git", "-c", "core.quotepath=off", "diff", "-U0", "--no-color", "--no-ext-diff",
           "--find-renames", "--src-prefix=a/", "--dst-prefix=b/", *spec, "--"]
    try:
        done = subprocess.run(cmd, cwd=root, capture_output=True, check=False)
    except OSError as exc:
        raise DiffUnavailable(f"could not run git in {root}: {exc}") from exc
    if done.returncode != 0:
        why = done.stderr.decode("utf-8", "replace").strip() or f"exit {done.returncode}"
        raise DiffUnavailable(f"git diff failed: {why}")
    return parse_added(done.stdout.decode("utf-8", "surrogateescape"))
