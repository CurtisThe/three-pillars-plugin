"""placeholder_gate.py — refuse to land a PR whose head still holds unnumbered issue IDs.

design: basesync-autoresolve-coverage. An ``<S>-new-<slug>`` heading in the known-issue
files is a placeholder that ``number_issues.py`` turns into a real number. ``/tp-merge``
(the CLI, never library ``land()``) and the HTML briefing's merge seam call
``head_unnumbered_ids`` before the gate (via ``land.unnumbered_refusal``) and refuse on any hit.

- ``unnumbered_ids(texts)``: pure; the sorted placeholder IDs headed in the ``ISSUE_FILES``
  texts (a mapping of repo-relative path -> text; absent files contribute nothing).
- ``unnumbered_ids_at(repo_root, ref)``: reads each issue file committed at ``ref`` with
  ``git show`` (a missing file is skipped; an unresolvable ``ref`` raises).
- ``head_unnumbered_ids(pr_url, repo_root)``: reads the PR *head commit* (``headRefOid``),
  never the ambient checkout, fetching it from ``origin`` only when it is not local yet.

Fail-closed: any piece that cannot be established raises ``PlaceholderGateError``.
Stdlib only.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

_SHARED = str(Path(__file__).resolve().parent)
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

from number_issues import DEFINED, ISSUE_FILES  # noqa: E402
from task_scope import _git_env  # noqa: E402

_SHA = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")


class PlaceholderGateError(RuntimeError):
    """The PR head's issue files could not be read; the caller must refuse."""


def unnumbered_ids(texts) -> list:
    """Sorted ``L-new-slug`` IDs headed (``### L-new-slug``) in the ``ISSUE_FILES`` texts."""
    found = set()
    for path in ISSUE_FILES:
        for m in DEFINED.finditer((texts or {}).get(path) or ""):
            found.add(f"{m.group(1)}-new-{m.group(2)}")
    return sorted(found)


def _git(run, repo_root, args):
    return run(["git", "-C", str(repo_root), *args], capture_output=True, text=True,
               env=_git_env())


def _detail(proc) -> str:
    lines = (proc.stderr or proc.stdout or "").strip().splitlines()
    return lines[-1] if lines else f"exit {proc.returncode}"


def _have_commit(run, repo_root, sha) -> bool:
    return _git(run, repo_root, ["cat-file", "-e", f"{sha}^{{commit}}"]).returncode == 0


def unnumbered_ids_at(repo_root, ref, run=subprocess.run) -> list:
    """Unnumbered IDs in the issue files committed at ``ref`` (never the worktree)."""
    probe = _git(run, repo_root, ["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"])
    if probe.returncode != 0:
        raise PlaceholderGateError(f"unresolvable ref {ref!r}")
    texts = {}
    for path in ISSUE_FILES:
        proc = _git(run, repo_root, ["show", f"{ref}:{path}"])
        if proc.returncode == 0:
            texts[path] = proc.stdout
    return unnumbered_ids(texts)


def head_unnumbered_ids(pr_url, repo_root, *, pr_state_fn=None, run=subprocess.run) -> list:
    """Unnumbered IDs at the PR's head commit (``headRefOid``), not local HEAD."""
    if pr_state_fn is None:
        import deterministic_gate  # resolved at call time: ships beside this module
        pr_state_fn = deterministic_gate._live_pr_state_fn
    payload = pr_state_fn(pr_url)
    sha = payload.get("headRefOid") if isinstance(payload, dict) else None
    if not isinstance(sha, str) or not _SHA.fullmatch(sha):
        raise PlaceholderGateError("PR state has no usable headRefOid")
    if not _have_commit(run, repo_root, sha):
        fetched = _git(run, repo_root, ["fetch", "origin", sha])
        if fetched.returncode != 0:
            raise PlaceholderGateError(f"git fetch origin {sha[:12]} failed: {_detail(fetched)}")
        if not _have_commit(run, repo_root, sha):
            raise PlaceholderGateError(f"PR head {sha[:12]} still missing after fetch")
    return unnumbered_ids_at(repo_root, sha, run=run)
