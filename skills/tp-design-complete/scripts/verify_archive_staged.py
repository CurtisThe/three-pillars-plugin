#!/usr/bin/env python3
"""Staged-blob archive guard for /tp-design-complete.

Read-only over git state: inspects the STAGED index blobs of an archived design
(never the working-tree files) and asserts the completion invariants that the
archival commit must carry. It performs no staging or commits itself, so it is
safe to re-run.

Assertions (all must pass for exit 0):
  - completed-tp-designs/{slug}/design.md  staged blob carries a
    `completed: YYYY-MM-DD` frontmatter stamp (the load-bearing keystone: a stamp
    that reached only the working tree, not the index, still FAILS).
  - completed-tp-designs/{slug}/lock.json  staged blob parses to phase
    `cleanup-pending`.
  - no dangling `tp-designs/{slug}` cite survives (front-runs inv #38), AND every
    file a pre-sweep would have rewritten is STAGED — a cite fixed on disk but not
    `git add`ed still FAILS (Behavior 7: staged-tree consistency, not disk-only).

Exit codes (the contract):
  0  all assertions pass
  1  at least one assertion failed (per-path repair line on stderr)
  2  a git/precondition error (an archived path is absent from the index, a bad
     --slug, an undecodable blob) — NOT fixable by re-staging

stdlib + git plumbing only; no network, no third-party deps.

Usage: python3 verify_archive_staged.py --repo PATH --slug NAME
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

# skills/_shared is where the shared frontmatter parser + cite detector live; add it
# to sys.path once so `parse_frontmatter` / `dead_design_cites` resolve (reuse-not-
# reinvent — the design's own constraint).
_SHARED_DIR = Path(__file__).resolve().parents[2] / "_shared"
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

COMPLETED_SUBDIR = "three-pillars-docs/completed-tp-designs"

# The `completed:` frontmatter value must be an ISO date; parse_frontmatter extracts
# the value, this validates its shape.
COMPLETED_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class PreconditionError(Exception):
    """A git/precondition error (path absent from index, bad slug, bad blob).

    Maps to exit 2 — the caller must NOT retry with a re-`git add` (the path is
    not there to re-add).
    """


def _design_path(slug: str) -> str:
    return f"{COMPLETED_SUBDIR}/{slug}/design.md"


def _lock_path(slug: str) -> str:
    return f"{COMPLETED_SUBDIR}/{slug}/lock.json"


def _show_staged(repo: str, path: str) -> str | None:
    """Return the STAGED (index, stage 0) blob of `path`, strict-UTF-8 decoded.

    Returns None when the path is not in the index (a fatal `git show` exit) —
    the caller maps that to a precondition error (exit 2), not an assertion
    failure. A blob present but not valid UTF-8 raises PreconditionError.
    """
    proc = subprocess.run(
        ["git", "-C", str(repo), "show", f":{path}"],
        capture_output=True,
    )
    if proc.returncode != 0:
        return None
    try:
        return proc.stdout.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PreconditionError(f"{path}: staged blob is not valid UTF-8 ({exc})")


def verify_staged_stamp(repo: str, slug: str) -> bool:
    """True iff the staged design.md blob carries a `completed:` frontmatter stamp.

    Raises PreconditionError if the archived design.md is absent from the index.
    Reuses the shared `weight_class.parse_frontmatter` for the fence parse (absent /
    unclosed / not-at-start frontmatter → `{}` → no `completed` key → fail), then
    validates the value is an ISO date.
    """
    from weight_class import parse_frontmatter

    path = _design_path(slug)
    blob = _show_staged(repo, path)
    if blob is None:
        raise PreconditionError(f"{path} is not in the git index (stage it first)")
    completed = parse_frontmatter(blob).get("completed")
    return bool(completed and COMPLETED_DATE_RE.match(completed.strip()))


def verify_staged_lock_phase(repo: str, slug: str) -> bool:
    """True iff the staged lock.json blob parses to phase == 'cleanup-pending'.

    Raises PreconditionError if the archived lock.json is absent from the index.
    """
    path = _lock_path(slug)
    blob = _show_staged(repo, path)
    if blob is None:
        raise PreconditionError(f"{path} is not in the git index (stage it first)")
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        return False
    return isinstance(data, dict) and data.get("phase") == "cleanup-pending"


def _staged_blob_lossy(repo: str, path: str) -> str | None:
    """Staged blob decoded lossily (`errors="ignore"`), or None if not in the index.

    Unlike `_show_staged`, this NEVER raises on a non-UTF-8 (binary) blob — it is
    used only for the part-(b) cite substring scan, where a binary asset simply
    cannot carry a text cite, so a lossy decode that drops undecodable bytes is
    safe. Reading blobs strictly here would turn a merely-modified tracked binary
    into a spurious precondition (exit 2) failure of the whole guard.
    """
    proc = subprocess.run(
        ["git", "-C", str(repo), "show", f":{path}"],
        capture_output=True,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout.decode("utf-8", errors="ignore")


def _unstaged_tracked_paths(repo: str) -> list[str]:
    """Repo-relative paths that differ between the working tree and the index.

    Wraps `git diff --name-only` (working-tree-vs-index). A tracked file rewritten
    on disk but not `git add`ed shows up here.
    """
    proc = subprocess.run(
        ["git", "-C", str(repo), "diff", "--name-only"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return []
    return [line for line in proc.stdout.splitlines() if line.strip()]


def verify_no_dangling(repo: str, slug: str) -> list[str]:
    """Return repair lines for dangling cites / unstaged rewrites (empty = pass).

    (a) Reuse citation_liveness.dead_design_cites (do NOT fork a cite scanner):
        no DeadCite for {slug} may remain over the working tree.
    (b) Staged-tree consistency (Behavior 7): a cite this design's pre-sweep
        rewrote on disk but did not `git add` — the working tree reads clean while
        the STAGED tree still carries the stale `tp-designs/{slug}` cite. Scoped to
        exactly those paths (an unstaged path whose staged blob still carries the
        slug cite), so unrelated working-tree WIP is not swept in.
    """
    # (a) reuse the shared dead-cite detector (skills/_shared already on sys.path).
    from citation_liveness import dead_design_cites

    failures: list[str] = []
    dead = [c for c in dead_design_cites(repo) if c.slug == slug]
    for c in dead:
        failures.append(
            f"{c.path}:{c.line}: live 'tp-designs/{slug}' cite survives the archive "
            f"(would trip inv #38) — repair: reconcile_docs.py --archive-cites "
            f"--slug {slug} --apply, then git add {c.path}"
        )

    # (b) staged-tree consistency — an unstaged tracked path whose STAGED blob still
    # carries a `tp-designs/{slug}/` cite is a rewrite that never reached the index.
    # Scoping to the stale-cite-in-index condition keeps unrelated WIP out (following
    # a blind `git add` on it would sweep WIP into the archival commit).
    stale_cite = f"tp-designs/{slug}/"
    for path in _unstaged_tracked_paths(repo):
        # Lossy decode: a modified tracked binary must not raise a precondition
        # error here (it cannot carry a text cite anyway).
        staged = _staged_blob_lossy(repo, path)
        if staged is not None and stale_cite in staged:
            failures.append(
                f"{path}: pre-sweep rewrote a 'tp-designs/{slug}' cite on disk but the "
                f"staged blob still carries it — repair: git add {path}"
            )
    return failures


def run_checks(repo: str, slug: str) -> list[str]:
    """Run every assertion; return a list of stderr repair lines (empty = pass).

    Raises PreconditionError on the first git/precondition failure (exit 2).
    """
    failures: list[str] = []
    if not verify_staged_stamp(repo, slug):
        failures.append(
            f"{_design_path(slug)}: staged blob missing a "
            f"'completed: YYYY-MM-DD' frontmatter stamp — "
            f"repair: git add {_design_path(slug)}"
        )
    if not verify_staged_lock_phase(repo, slug):
        failures.append(
            f"{_lock_path(slug)}: staged blob phase is not 'cleanup-pending' — "
            f"repair: git add {_lock_path(slug)}"
        )
    failures.extend(verify_no_dangling(repo, slug))
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument(
        "--repo", required=True,
        help="repo root (typically $(git rev-parse --show-toplevel))",
    )
    parser.add_argument("--slug", required=True, help="archived design slug")
    args = parser.parse_args(argv)

    try:
        failures = run_checks(args.repo, args.slug)
    except PreconditionError as exc:
        print(f"verify_archive_staged: precondition error: {exc}", file=sys.stderr)
        return 2

    if failures:
        for line in failures:
            print(f"verify_archive_staged: {line}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
