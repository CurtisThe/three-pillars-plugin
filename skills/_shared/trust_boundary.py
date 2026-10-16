#!/usr/bin/env python3
"""trust_boundary.py — a closed, named trust-boundary pattern table over a unified diff.

design: review-convergence (detailed-design-security.md, Phase 3)

The table is read over the **added and removed** lines of a unified diff. It reports
surfaces; it never judges. A removed line that matches (a deleted ``shlex.quote``, a
dropped path-prefix check) is reported with ``removed: true`` ("guard removed"), so a
removal-only fix delta still turns the security lens on.

Extending the table is a reviewed code change, never config.

This module is the table plus :func:`surfaces`, the git-range reader
:func:`surfaces_for_range` and the CLI; the brief resolver lands in a later task of the
same design.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

# The six surfaces the security angle can be pointed at.
SURFACES = ("argv-subprocess", "file-write-path", "credentials", "git-gh",
            "untrusted-parse", "agent-tool-grant")

# One shared constant so the security angle and the impl-audit synth read the same text.
SECURITY_BAR = ("A security finding blocks only with a demonstrated exploit path: the "
                "attacker-controlled input, the trust boundary it crosses and the effect, with "
                "a reproducer. Hardening ideas without one are notes (blocking=false). Prefer "
                "allowlist or build-the-input fixes; a blocklist patch is not a fix.")

# The generic brief, shipped beside this module, for a repo without its own SECURITY.md.
CHECKLIST = Path(__file__).resolve().parent / "trust-boundary-checklist.md"

MAX_TEXT = 160  # the reported line content is cut to this many chars


class Pattern(NamedTuple):
    name: str                  # one of SURFACES
    path_glob: tuple[str, ...]  # fnmatch on the new path; () = any path
    line_re: re.Pattern | None  # each added/removed line; None = any line


def _any(*alts: str):
    """One alternation regex from the table's per-row alternatives."""
    return re.compile("|".join(alts))


# Path groups used by the table rows. fnmatch "*" crosses "/", so `*.py` also matches
# `skills/_shared/x.py`.
_PY = ("*.py",)
_SHELL = ("*.sh", "*.bash", "*.zsh", "hooks/*", "*/hooks/*", ".githooks/*")
_AGENT = ("agents/*.md", "**/agents/*.md", "settings*.json", "**/settings*.json",
          "SKILL.md", "**/SKILL.md")
# A hook DIRECTORY (or the pre-commit config) — a changed line there is a surface by
# itself. A `hooks/`-named script at the repo root stays on the shell row instead.
_HOOKS = ("**/hooks/**", ".pre-commit-config.yaml")
_ANY: tuple = ()

PATTERNS: tuple = (
    # argv-subprocess — python call sites
    Pattern("argv-subprocess", _PY, _any(
        r"subprocess\.(run|Popen|call|check_call|check_output)",
        r"os\.(system|exec\w*|spawn\w*)",
        r"shell\s*=\s*True",
        r"shlex\.",
    )),
    # argv-subprocess — shell scripts and hook scripts
    Pattern("argv-subprocess", _SHELL, _any(
        r"\beval\b",
        r"\b(ba)?sh\s+-c\b",
        r"\$\{?[A-Za-z_]\w*",
    )),
    # file-write-path — anything that can mutate the filesystem
    Pattern("file-write-path", _ANY, _any(
        r"""open\([^)]*["'][wax+]""",
        r"\.write_(text|bytes)\(",
        r"shutil\.(copy\w*|move|rmtree)",
        r"os\.(remove|unlink|rename|replace|makedirs)",
        r"\.(unlink|rename|rmdir)\(",
        r"\brm\s+-",
        r'>\s*"?\$',
    )),
    # credentials — a secret name or a secret-carrying header
    Pattern("credentials", _ANY, re.compile(
        r"(?i)token|secret|passw(or)?d|credential|api[_-]?key"
        r"|GH_TOKEN|GITHUB_TOKEN|Authorization")),
    # git-gh — commands that can rewrite repo or remote state
    Pattern("git-gh", _ANY, _any(
        r"\bgit\b[^\n]*\b(push|config|update-ref|reset|worktree|hook)",
        r"core\.hooksPath",
        r"\.git/hooks",
        r"\bgh\s+(api|pr|auth|repo)",
    )),
    # git-gh — a changed hook or hook-config line is a surface whatever it says
    Pattern("git-gh", _HOOKS, None),
    # untrusted-parse — feeding untrusted text to an interpreter
    Pattern("untrusted-parse", _PY, _any(
        r"json\.loads?\(",
        r"yaml\.",
        r"pickle\.loads?\(",
        r"\beval\(",
        r"\bexec\(",
        r"ast\.literal_eval",
        r"re\.compile\(",
    )),
    # agent-tool-grant — who is allowed to run what
    Pattern("agent-tool-grant", _AGENT, _any(
        r"^\s*tools:",
        r"allowed-tools",
        r'"allow"\s*:',
        r"permissions",
        r"dangerously",
    )),
)

_HUNK = re.compile(r"^@@ +-(\d+)(?:,(\d+))? +\+(\d+)(?:,(\d+))? @@")
_GARBAGE = ("diff ", "index ", "similarity ", "rename ", "copy ",
            "new file", "deleted file", "old mode", "new mode", "\\")


def _strip_prefix(raw: str):
    """`b/pkg/x.py` -> `pkg/x.py`; `/dev/null` -> None (so the a/ side is used)."""
    if raw == "/dev/null":
        return None
    for prefix in ("a/", "b/", "c/", "i/"):
        if raw.startswith(prefix):
            return raw[len(prefix):]
    return raw


def _changed_lines(diff_text: str):
    """Yield ``(path, removed, line, text)`` for every +/- line, in diff order.

    ``path`` is the b/ path (the a/ path when the b/ side is ``/dev/null``). ``line`` is
    the new-file line number for an added line and the old-file line number for a removed
    one, counted from the ``@@`` hunk header.
    """
    old_path = new_path = None
    old_line = new_line = 0
    for raw in diff_text.splitlines():
        if raw.startswith("--- "):
            old_path = _strip_prefix(raw[4:].strip())
            continue
        if raw.startswith("+++ "):
            new_path = _strip_prefix(raw[4:].strip())
            continue
        if raw.startswith("@@"):
            head = _HUNK.match(raw)
            old_line = int(head.group(1)) if head else 0
            new_line = int(head.group(3)) if head else 0
            continue
        if raw.startswith(_GARBAGE):
            continue
        path = new_path if new_path is not None else old_path
        if path is None:
            continue
        if raw.startswith("+"):
            yield path, False, new_line, raw[1:].strip()
            new_line += 1
        elif raw.startswith("-"):
            yield path, True, old_line, raw[1:].strip()
            old_line += 1
        else:  # a context line (or an empty line some tools emit for "no change")
            old_line += 1
            new_line += 1


def surfaces(diff_text: str) -> list:
    """The trust-boundary surfaces a diff touches.

    Returns ``[{"surface", "path", "line", "text"<=160, "removed": bool}]``,
    de-duplicated on ``(surface, path, line, removed)`` and kept in diff order. Any
    entry — added or removed — counts as a surface for the security lens.
    """
    found: list = []
    seen: set = set()
    for path, removed, line, text in _changed_lines(diff_text):
        for pat in PATTERNS:
            if pat.path_glob and not any(
                    fnmatch.fnmatch(path, glob) for glob in pat.path_glob):
                continue
            if pat.line_re is not None and not pat.line_re.search(text):
                continue
            key = (pat.name, path, line, removed)
            if key in seen:
                continue
            seen.add(key)
            found.append({"surface": pat.name, "path": path, "line": line,
                          "text": text[:MAX_TEXT], "removed": removed})
    return found


class TrustBoundaryError(Exception):
    """The git read failed. Callers fail closed: treat it as "surface present"."""


def _run_git(argv: list, cwd: str) -> str:
    """Run one git command and return stdout. Any failure is a TrustBoundaryError."""
    try:
        done = subprocess.run(["git", *argv], cwd=cwd, capture_output=True, text=True)
    except OSError as exc:
        raise TrustBoundaryError(f"git {argv[0]} could not run: {exc}") from exc
    if done.returncode != 0:
        raise TrustBoundaryError(
            f"git {argv[0]} failed ({done.returncode}): {done.stderr.strip()}")
    return done.stdout


def surfaces_for_range(repo, base: str, head: str, *, three_dot: bool = False,
                       run_git=None) -> list:
    """The trust-boundary surfaces a commit range touches.

    ``git diff --unified=0 --no-color base..head`` (two-dot over the fix delta), or
    ``base...head`` when ``three_dot`` — the form to use when ``base`` is the PR base.
    A git error raises :class:`TrustBoundaryError` rather than reporting nothing, so a
    caller can fail closed. ``run_git`` is the test seam: ``run_git(argv, cwd) -> str``
    with ``argv`` excluding the leading ``git``.
    """
    seam = run_git if run_git is not None else _run_git
    spec = f"{base}...{head}" if three_dot else f"{base}..{head}"
    argv = ["diff", "--unified=0", "--no-color", spec]
    try:
        out = seam(argv, str(repo))
    except TrustBoundaryError:
        raise
    except Exception as exc:
        raise TrustBoundaryError(f"git diff {spec} failed: {exc}") from exc
    return surfaces(out)


def brief_path(repo_root) -> Path:
    """Which brief the security angle reads for the repository under review.

    ``repo_root`` is that repository's toplevel (``git rev-parse --show-toplevel``) —
    never a path derived from this module's own location, so the plugin's checkout can
    not supply a brief for someone else's repo. Its ``SECURITY.md`` wins when it is a
    regular file; anything else (absent, or a directory) falls back to :data:`CHECKLIST`.
    """
    p = Path(repo_root) / "SECURITY.md"
    return p if p.is_file() else CHECKLIST


def main(argv=None) -> int:
    """CLI: print the distinct surface names (or the full entries with --json).

    Exit 0 when the range touches no surface, 3 when it touches any, 2 when the git
    read failed.
    """
    ap = argparse.ArgumentParser(
        description="Report the trust-boundary surfaces a git range touches.")
    ap.add_argument("--base", required=True, help="range base (PR base or parent sha)")
    ap.add_argument("--head", required=True, help="range head sha")
    ap.add_argument("--repo", default=".", help="repository to read (default: .)")
    ap.add_argument("--json", action="store_true",
                    help="print the full entries as JSON instead of names")
    ns = ap.parse_args(argv)
    try:
        found = surfaces_for_range(ns.repo, ns.base, ns.head)
    except TrustBoundaryError as exc:
        print(f"trust_boundary: {exc}", file=sys.stderr)
        return 2
    if ns.json:
        print(json.dumps(found, indent=2))
    else:
        for name in dict.fromkeys(e["surface"] for e in found):
            print(name)
    return 3 if found else 0


if __name__ == "__main__":
    sys.exit(main())
