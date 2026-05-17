#!/usr/bin/env python3
"""
Parent-design detection for /tp-design-complete.

Inspects sibling designs under three-pillars-docs/tp-designs/ to determine
whether the current branch was cut from another in-flight design's branch.
Emits a JSON verdict (none / single / multiple) that SKILL.md step 6g uses
to choose the PR's --base target.

Usage: python3 detect_parent.py --repo PATH --design NAME --default-branch NAME
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path


DESIGNS_SUBDIR = Path("three-pillars-docs") / "tp-designs"


def resolve_default_ref(repo_root: Path, default_branch: str) -> str:
    """Resolve the default-branch ref, heads-first then origin fallback.

    Raises LookupError if neither `refs/heads/{default_branch}` nor
    `refs/remotes/origin/{default_branch}` exists — caller exits 2 so the
    SKILL falls through to its existing default-branch behavior.
    """
    ref = resolve_ref(repo_root, default_branch)
    if ref is None:
        raise LookupError(f"default branch {default_branch!r} not resolvable")
    return ref


def pick_leaf(repo_root: Path, candidates: list[dict]) -> list[dict]:
    """Drop any candidate that is an ancestor of another candidate (chained-design ranking).

    A "leaf" parent is the most direct ancestor: not an ancestor of any sibling candidate.
    """
    if len(candidates) <= 1:
        return candidates
    out: list[dict] = []
    for i, ci in enumerate(candidates):
        dropped = False
        for j, cj in enumerate(candidates):
            if i == j:
                continue
            if is_ancestor(repo_root, ci["_ref"], cj["_ref"]):
                dropped = True
                break
        if not dropped:
            out.append(ci)
    return out


def filter_active(repo_root: Path, candidates: list[dict], head: str, default_ref: str) -> list[dict]:
    """Keep candidates whose branch is an ancestor of HEAD and *not* already merged into default."""
    out: list[dict] = []
    for c in candidates:
        ref = resolve_ref(repo_root, c["branch"])
        if ref is None:
            continue
        if not is_ancestor(repo_root, ref, head):
            continue
        if is_ancestor(repo_root, ref, default_ref):
            continue  # already merged into default — not a live parent
        out.append({**c, "_ref": ref})
    return out


def is_ancestor(repo_root: Path, ref: str, head: str) -> bool:
    """Return True iff `ref` is an ancestor of `head`. Wraps `git merge-base --is-ancestor`."""
    proc = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ref, head],
        cwd=str(repo_root),
        capture_output=True,
    )
    return proc.returncode == 0


def resolve_ref(repo_root: Path, branch: str) -> str | None:
    """Return the qualified ref-name for `branch`, preferring local heads over origin.

    Tries refs/heads/{branch} first; falls through to refs/remotes/origin/{branch}.
    Returns None if neither resolves.
    """
    for candidate in (f"refs/heads/{branch}", f"refs/remotes/origin/{branch}"):
        proc = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", candidate],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0:
            return candidate
    return None


def enumerate_siblings(repo_root: Path, current_design: str) -> list[dict]:
    """List sibling designs that carry a lock.json. The current design is excluded."""
    repo_root = Path(repo_root)
    designs_dir = repo_root / DESIGNS_SUBDIR
    if not designs_dir.is_dir():
        return []

    siblings: list[dict] = []
    for design_dir in sorted(designs_dir.iterdir()):
        if not design_dir.is_dir():
            continue
        if design_dir.name == current_design:
            continue
        lock_path = design_dir / "lock.json"
        if not lock_path.is_file():
            continue
        try:
            lock = json.loads(lock_path.read_text())
        except json.JSONDecodeError:
            continue
        siblings.append({
            "design": lock.get("design", design_dir.name),
            "branch": lock.get("branch", ""),
            "last_touched": lock.get("last_touched", ""),
        })
    return siblings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--repo", required=True, help="repo root (typically $(git rev-parse --show-toplevel))")
    parser.add_argument("--design", required=True, help="current design name (excluded from sibling enumeration)")
    parser.add_argument("--default-branch", required=True, help="repo default branch (e.g. master/main)")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo)
    siblings = enumerate_siblings(repo_root, args.design)

    try:
        default_ref = resolve_default_ref(repo_root, args.default_branch)
    except LookupError:
        return 2

    active = filter_active(repo_root, siblings, "HEAD", default_ref)
    leaves = pick_leaf(repo_root, active)
    leaves.sort(key=lambda c: c.get("last_touched", ""), reverse=True)
    public = [{k: v for k, v in c.items() if not k.startswith("_")} for c in leaves]

    if len(public) == 0:
        verdict = "none"
    elif len(public) == 1:
        verdict = "single"
    else:
        verdict = "multiple"

    payload = {
        "verdict": verdict,
        "default_branch": args.default_branch,
        "candidates": public,
    }
    json.dump(payload, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
