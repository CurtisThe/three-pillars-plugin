#!/usr/bin/env python3
"""living_doc_guard.py -- refuse a design branch that edits a shared living doc.

The shipped floor of living-doc-fragments: a `tp/<slug>` branch writes
`three-pillars-docs/changes/<slug>.md`, never the shared living docs. The diff is taken from
the merge-base with the base ref, so a base-sync merge of already-landed base text is not counted.

CLI: `living_doc_guard.py check --base REF [--branch B] [--repo-root R] [--json]`
exit 0 clean/exempt/skipped, 1 refused, 2 git error.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from auto_safe_resolution import AUTO_SAFE_PATHS
from low_doc_parts import is_part_rel

LEGACY_REL = ".three-pillars/living-doc-legacy.txt"
EXEMPT_SLUGS = frozenset({"docs-compile"})
PROTOCOL_DOC = "skills/_shared/living-doc-fragments.md"


class GuardGitError(RuntimeError):
    """A git command failed (unknown base ref, not a repo, ...)."""


@dataclass
class GuardResult:
    verdict: str  # clean | refused | exempt | skipped
    paths: list[str] = field(default_factory=list)
    fix: str = ""


def is_shared_living_doc(rel: str) -> bool:
    rel = rel.replace("\\", "/")
    if rel == "three-pillars-docs/vision.md":
        return False
    return rel in AUTO_SAFE_PATHS or is_part_rel(rel)


def _git(root: Path, *args: str) -> str:
    try:
        r = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8")
    except OSError as exc:
        raise GuardGitError(str(exc)) from exc
    if r.returncode != 0:
        raise GuardGitError(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout.strip()


def _legacy_slugs(root: Path) -> set[str]:
    p = root / LEGACY_REL
    if not p.is_file():
        return set()
    lines = (ln.strip() for ln in p.read_text(encoding="utf-8").splitlines())
    return {ln for ln in lines if ln and not ln.startswith("#")}


def check(repo_root: Path | str, *, base_ref: str, branch: str | None = None) -> GuardResult:
    root = Path(repo_root)
    name = branch or _git(root, "rev-parse", "--abbrev-ref", "HEAD")
    if not name.startswith("tp/"):
        return GuardResult("skipped")
    slug = name[len("tp/"):]
    if slug in EXEMPT_SLUGS or slug in _legacy_slugs(root):
        return GuardResult("exempt")
    base = _git(root, "merge-base", base_ref, "HEAD")
    changed = _git(root, "diff", "--name-only", base, "HEAD").splitlines()
    paths = sorted(p for p in changed if is_shared_living_doc(p))
    if not paths:
        return GuardResult("clean")
    fix = (f"write your doc changes to three-pillars-docs/changes/{slug}.md instead of editing "
           f"{', '.join(paths)}; see {PROTOCOL_DOC}")
    return GuardResult("refused", paths, fix)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="living_doc_guard.py", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--base", required=True)
    c.add_argument("--branch")
    c.add_argument("--repo-root", default=".")
    c.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    try:
        res = check(args.repo_root, base_ref=args.base, branch=args.branch)
    except GuardGitError as exc:
        print(f"living_doc_guard: git error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps({"verdict": res.verdict, "paths": res.paths, "fix": res.fix}))
    elif res.verdict == "refused":
        print(f"living_doc_guard: refused: {', '.join(res.paths)}\nfix: {res.fix}")
    else:
        print(f"living_doc_guard: {res.verdict}")
    return 1 if res.verdict == "refused" else 0


if __name__ == "__main__":
    sys.exit(main())
