#!/usr/bin/env python3
"""hot_patch_hook.py — the hot-patch lane's git-hook modes (consumer-repo-parity H3).

Shipped: the commit guard (`commit_guard.run`) and the dev repo's own
pre-commit config call these through `hot_patch_check.py`'s CLI flags.

- ``commit_msg_mode(repo, msg_file)`` — ``--commit-msg FILE``, arm (b) on the
  *pending* commit. git runs ``commit-msg`` after the message exists and before
  the commit object is written. The trailers are read with git's own rules
  (``git interpret-trailers --parse``: last paragraph only, comment lines
  ignored, the repo's trailer config honoured). With no trailer whose key is
  ``hot-patch`` (any casing) the lane is inert. Otherwise the exclusions and
  the DIFF_CAP run over the index (``git diff --cached``, which works on an
  unborn HEAD and reads the temporary ``GIT_INDEX_FILE`` git hands the hook
  for ``commit -a`` / pathspec commits); the ledger stays exempt from the cap.
  Any violation exits 1 and git aborts the commit.
- ``branch_trailered_mode(repo)`` — ``--branch-trailered``, the arm (b)
  backstop the ``pre-commit`` hook and ``ci_gate_run`` run: ``--amend`` diffs
  against the old HEAD and rebase ``pick`` / cherry-pick skip ``commit-msg``,
  so every trailered commit in ``<default_ref(prefer="origin")>..HEAD`` is
  re-checked with the ``--check-sha`` logic. A later commit in the range whose
  revert line names exactly that SHA voids it. The remedy is chosen per SHA:
  ``git reset --soft <sha>^`` for an unpushed first-parent commit, otherwise
  ``git revert <sha>`` plus the ledger step. Unborn HEAD or no resolvable base
  skips with one warning. Disclosed: on the default branch with no ``origin``
  the range is empty.

Import direction (no cycle): this module imports ``hot_patch_check``'s helpers
at module level; ``hot_patch_check.main`` imports this module function-locally.
Stdlib only.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_SHARED_DIR = str(Path(__file__).resolve().parent)
if _SHARED_DIR not in sys.path:
    sys.path.insert(0, _SHARED_DIR)

from default_branch import default_ref  # noqa: E402
from skills._shared.hot_patch_check import (  # noqa: E402
    LEDGER_RELPATH,
    check_diff_cap,
    check_exclusions,
)

TRAILER_KEY = "hot-patch"
_KEY_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9-]*)")


def _trailer_keys(repo: str, msg_file: str) -> list[str]:
    """Lowercased trailer keys of ``msg_file`` per git's trailer rules.

    ``--no-divider``: a ``---`` body line is not a patch divider here, matching the
    ``%(trailers)`` read every other arm makes of the landed commit (M40).

    Raises RuntimeError when git cannot parse the file (fail-closed: the
    caller's CLI turns it into exit 2, which git treats as a refusal)."""
    result = subprocess.run(
        ["git", "-C", repo, "interpret-trailers", "--parse", "--no-divider", msg_file],
        capture_output=True, text=True, stdin=subprocess.DEVNULL,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git interpret-trailers failed (exit {result.returncode}): "
            f"{result.stderr.strip()}"
        )
    keys = []
    for line in result.stdout.splitlines():
        match = _KEY_RE.match(line)
        if match:
            keys.append(match.group(1).lower())
    return keys


def has_hot_patch_trailer(repo: str, msg_file: str) -> bool:
    """True when the message carries a ``hot-patch`` trailer (any key casing)."""
    return TRAILER_KEY in _trailer_keys(repo, msg_file)


def commit_msg_mode(repo: str, msg_file: str) -> int:
    """Arm (b) on the pending commit; 0 clean or inert, 1 on any violation."""
    msg_path = os.path.abspath(msg_file)
    if not has_hot_patch_trailer(repo, msg_path):
        return 0
    violations = check_exclusions(sha=None, repo=repo)
    violations.extend(check_diff_cap(sha=None, repo=repo))
    for line in violations:
        print(line)
    if violations:
        print(
            "hot-patch: this commit carries a `hot-patch:` trailer but is outside "
            "the lane (protected path or over the diff cap). Drop the trailer and "
            "take the normal design path, or split the fix under the cap."
        )
    return 1 if violations else 0


# ---------------------------------------------------------------------------
# --branch-trailered: the amend / rebase / cherry-pick backstop
# ---------------------------------------------------------------------------

def _run(repo: str, args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", repo, *args], capture_output=True,
                          text=True, stdin=subprocess.DEVNULL)


def _checked(repo: str, args: list[str]) -> str:
    result = _run(repo, args)
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:2])} failed (exit "
                           f"{result.returncode}): {result.stderr.strip()}")
    return result.stdout


def _resolve(repo: str, rev: str) -> str | None:
    result = _run(repo, ["rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}"])
    return result.stdout.strip() if result.returncode == 0 else None


def _trailered_in_range(repo: str, rev_range: str) -> list[str]:
    """Trailered SHAs in ``rev_range``: the ``-i --grep=^hot-patch`` prefilter,
    confirmed by git's ``%(trailers:key=hot-patch)`` parse (oldest first)."""
    out = _checked(repo, ["log", "--reverse", "-i", "--grep=^hot-patch",
                          "--format=%H", rev_range])
    candidates = [s.strip() for s in out.splitlines() if s.strip()]
    if not candidates:
        return []
    fmt = "%H %(trailers:key=hot-patch,valueonly,separator=%x2C,unfold=true)"
    out = _checked(repo, ["log", "--no-walk=unsorted", *candidates, f"--format={fmt}"])
    confirmed = []
    for line in out.splitlines():
        parts = line.strip().split(" ", 1)
        if len(parts) == 2 and parts[1].strip():
            confirmed.append(parts[0])
    return confirmed


_REVERT_RE = re.compile(r"^This reverts commit ([0-9a-f]{7,40})\b", re.MULTILINE)


def _reverted_in_range(repo: str, rev_range: str) -> set[str]:
    """Full SHAs named by git's revert line in any message of ``rev_range``.

    Its own ``git log`` over every commit (the prefiltered set never holds a
    revert). Each capture must resolve exactly; one that does not voids nothing."""
    out = _checked(repo, ["log", "--format=%B%x00", rev_range])
    voided = set()
    for capture in _REVERT_RE.findall(out):
        full = _resolve(repo, capture)
        if full:
            voided.add(full)
    return voided


def _is_unpushed_first_parent(repo: str, sha: str, rev_range: str) -> bool:
    """On HEAD's first-parent line and not pushed. With no ``@{upstream}``, the
    SHA counts as unpushed only when ``git branch -r --contains`` lists nothing;
    any hit or error errs toward the revert remedy."""
    first = _run(repo, ["rev-list", "--first-parent", rev_range])
    if first.returncode != 0 or sha not in first.stdout.split():
        return False
    if _resolve(repo, "@{upstream}"):
        pushed = _run(repo, ["merge-base", "--is-ancestor", sha, "@{upstream}"])
        return pushed.returncode == 1
    remote = _run(repo, ["branch", "-r", "--contains", sha])
    return remote.returncode == 0 and not remote.stdout.strip()


def _remedy(repo: str, sha: str, rev_range: str) -> list[str]:
    if _is_unpushed_first_parent(repo, sha, rev_range):
        return [
            f"hot-patch remedy for {sha}: unpushed, so run `git reset --soft {sha}^` "
            "and commit again without the `hot-patch:` trailer, or split it under "
            "the cap (reset runs no hook; the re-commit is checked afresh).",
        ]
    return [
        f"hot-patch remedy for {sha}: it is pushed or came in through a merge, so "
        f"run `git revert {sha}`, then re-apply the change without the "
        "`hot-patch:` trailer or split it under the cap.",
        f"If this branch will land with a merge commit, also append a ledger entry "
        f"for {sha} to {LEDGER_RELPATH} (arm (a) sees the reverted SHA once merged).",
    ]


def branch_trailered_violations(repo: str) -> list[str]:
    """VIOLATION and remedy lines for ``<default_ref(prefer="origin")>..HEAD``.

    Unborn HEAD or no resolvable base: one warning on stderr, no lines."""
    if _resolve(repo, "HEAD") is None:
        print("hot_patch_check: --branch-trailered skipped: unborn HEAD", file=sys.stderr)
        return []
    base = default_ref(repo, prefer="origin")
    if base is None:
        print("hot_patch_check: --branch-trailered skipped: no default-branch ref "
              "resolves", file=sys.stderr)
        return []
    rev_range = f"{base}..HEAD"
    shas = _trailered_in_range(repo, rev_range)
    if not shas:
        return []
    voided = _reverted_in_range(repo, rev_range)
    lines: list[str] = []
    for sha in shas:
        if sha in voided:
            continue
        found = check_exclusions(sha=sha, repo=repo) + check_diff_cap(sha=sha, repo=repo)
        if found:
            lines.extend(found)
            lines.extend(_remedy(repo, sha, rev_range))
    return lines


def branch_trailered_mode(repo: str) -> int:
    """The arm (b) backstop; 0 clean or skipped, 1 on any violation."""
    lines = branch_trailered_violations(repo)
    for line in lines:
        print(line)
    return 1 if lines else 0
