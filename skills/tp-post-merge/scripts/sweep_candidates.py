"""sweep_candidates.py — candidate-branch sweep reporter.

Enumerates candidate/* branches (local or remote), classifies each as
orphaned (design archived) or live (design not archived), and reports the
result.

Always exits 0 (reporter — the SKILL decides deletion, not this script).

Usage:
    python3 skills/tp-post-merge/scripts/sweep_candidates.py \
        [--repo <repo_root>] [--remote] [--json]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

# Module-level compiled regexes — validated at the boundary so slugs and
# branch names are never interpolated from untrusted input downstream.
# Slug charset: lowercase alphanumeric and hyphens only (mirrors _DESIGN_RE
# in verify_merged.py; rejects '.', '/', spaces, uppercase, underscores).
_SLUG_RE = re.compile(r"^[a-z0-9-]+$")

# Branch name: the fixed shape emitted by the Tier-3 worker in
# tp-run-full-design (the MVP single-candidate orchestrator always uses
# the `single` candidate ID).  Anchored so partial matches (e.g.
# `candidate/../single`) are rejected.
_BRANCH_RE = re.compile(r"^candidate/([a-z0-9-]+)/single$")


def extract_slug(branch: str) -> str | None:
    """Return the slug from a candidate branch name, or None if invalid.

    Accepts only the shape `candidate/<slug>/single` where slug matches
    `[a-z0-9-]+`.  This is the boundary validation — any branch whose
    slug or shape is unexpected yields None and is dropped, never
    interpolated downstream.

    Examples:
        extract_slug("candidate/foo-bar/single")  → "foo-bar"
        extract_slug("candidate/../single")        → None  (traversal)
        extract_slug("candidate/Foo/single")       → None  (uppercase)
    """
    m = _BRANCH_RE.match(branch)
    if m is None:
        return None
    return m.group(1)


def is_archived(repo: str, slug: str) -> bool:
    """Return True if the design's archive exists on disk.

    Checks for `{repo}/three-pillars-docs/completed-tp-designs/{slug}/design.md`.
    The filesystem check is appropriate because the sweep runs from the base
    checkout where the archive is present after `/tp-design-complete`.

    Slug is re-guarded with _SLUG_RE before any path-join (defense-in-depth).
    """
    if not _SLUG_RE.match(slug):
        return False
    archive = (
        Path(repo)
        / "three-pillars-docs"
        / "completed-tp-designs"
        / slug
        / "design.md"
    )
    return archive.is_file()


def enumerate_candidate_branches(repo: str, *, remote: bool = False) -> list[str]:
    """Return a list of candidate branch names matching `candidate/<slug>/single`.

    remote=False: query local refs via `git branch --format=%(refname:short)`.
    remote=True:  query origin refs via `git ls-remote --heads origin 'candidate/*'`
                  (strips the `refs/heads/` prefix before filtering).

    Fail-open: any subprocess error returns [] without raising.
    """
    try:
        if remote:
            result = subprocess.run(
                [
                    "git",
                    "-C",
                    repo,
                    "ls-remote",
                    "--heads",
                    "origin",
                    "candidate/*",
                ],
                capture_output=True,
                timeout=15,
            )
            if result.returncode != 0:
                return []
            lines = result.stdout.decode("utf-8", errors="replace").splitlines()
            # Each line: "<sha>\trefs/heads/<branch>"
            names: list[str] = []
            for line in lines:
                parts = line.split("\t", 1)
                if len(parts) == 2:
                    ref = parts[1].strip()
                    prefix = "refs/heads/"
                    if ref.startswith(prefix):
                        names.append(ref[len(prefix):])
        else:
            result = subprocess.run(
                [
                    "git",
                    "-C",
                    repo,
                    "branch",
                    "--format=%(refname:short)",
                ],
                capture_output=True,
                timeout=15,
            )
            if result.returncode != 0:
                return []
            names = result.stdout.decode("utf-8", errors="replace").splitlines()

        return [name for name in names if _BRANCH_RE.match(name)]

    except Exception:
        return []


def classify_candidates(repo: str, *, remote: bool = False) -> dict[str, list[str]]:
    """Classify candidate branches as orphaned or live.

    Returns `{"orphaned": [...], "live": [...]}`.

    - orphaned: slug is_archived (safe to delete — design is done).
    - live:     slug not archived (design still in flight — never touch).
    - Branches with unparseable slugs are dropped (not classified).
    """
    branches = enumerate_candidate_branches(repo, remote=remote)
    orphaned: list[str] = []
    live: list[str] = []
    for branch in branches:
        slug = extract_slug(branch)
        if slug is None:
            # Unparseable — drop silently (should not happen since
            # enumerate already filters by _BRANCH_RE, but be defensive)
            continue
        if is_archived(repo, slug):
            orphaned.append(branch)
        else:
            live.append(branch)
    return {"orphaned": orphaned, "live": live}


def main(argv: list[str]) -> int:
    """CLI entry point. Always returns 0."""
    try:
        parser = argparse.ArgumentParser(
            description="Enumerate and classify candidate/* branches."
        )
        parser.add_argument(
            "--repo",
            default=".",
            help="Path to the git repo root (default: current directory)",
        )
        parser.add_argument(
            "--remote",
            action="store_true",
            help="Classify origin refs instead of local refs",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            dest="json_output",
            help="Output JSON classification to stdout",
        )
        args = parser.parse_args(argv)

        result = classify_candidates(args.repo, remote=args.remote)

        if args.json_output:
            print(json.dumps(result))
        else:
            orphaned = result["orphaned"]
            live = result["live"]
            print(f"orphaned: {len(orphaned)}")
            for b in orphaned:
                print(f"  {b}")
            print(f"live: {len(live)}")
            for b in live:
                print(f"  {b}")

        return 0

    except SystemExit as exc:
        if exc.code in (0, None):
            return 0
        _print_safe_fallback(argv)
        return 0

    except Exception:
        _print_safe_fallback(argv)
        return 0


def _print_safe_fallback(argv: list[str]) -> None:
    """Print a safe empty verdict. Never raises."""
    try:
        safe: dict[str, list[str]] = {"orphaned": [], "live": []}
        if "--json" in argv:
            print(json.dumps(safe))
        else:
            print("orphaned: 0")
            print("live: 0")
    except Exception:
        print('{"orphaned": [], "live": []}')


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
