"""Validate staged living-doc change fragments at commit time.

design: followups-1023 item 12. /tp-design-learn wrote `Completion PR pending`
into Recent completions three times and only a hand fix caught it; this check
runs the fragment grammar over a path list so the commit fails instead.
Grammar only (no repo_root): live-doc drift never blocks a commit.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

import changes_fragment

FRAGMENT = re.compile(r"^three-pillars-docs/changes/[^/]+\.md$")


def _staged_text(repo_root, p):
    """The index blob of `p`: None when `p` is not staged, the text otherwise.
    Raises on a git failure so the caller blocks (fail-closed)."""
    cwd = str(repo_root)
    listed = subprocess.run(["git", "ls-files", "--stage", "-z", "--", p],
                            cwd=cwd, capture_output=True, text=True)
    if listed.returncode != 0:
        raise RuntimeError(f"git ls-files failed: {listed.stderr.strip()}")
    if not listed.stdout:
        return None
    blob = subprocess.run(["git", "cat-file", "-p", f":{p}"],
                          cwd=cwd, capture_output=True)
    if blob.returncode != 0:
        raise RuntimeError(f"git cat-file failed: {blob.stderr.decode().strip()}")
    return blob.stdout.decode("utf-8")


def problems_for(repo_root, paths, staged: bool = False) -> list[str]:
    """`staged=True` validates the index blob (the commit hook), else the disk file."""
    lines = []
    for p in paths:
        if not FRAGMENT.match(p):
            continue
        if staged:
            text = _staged_text(repo_root, p)
        else:
            f = Path(repo_root) / p
            text = f.read_text(encoding="utf-8") if f.is_file() else None
        if text is None:
            continue
        frag = changes_fragment.parse(text, stem=Path(p).stem)
        for problem in changes_fragment.validate(frag):
            lines.append(f"fragment-check: {p}: {changes_fragment.format_problem(problem)}")
    return lines


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--staged", action="store_true",
                    help="validate the staged (index) blob, not the working-tree file")
    ap.add_argument("paths", nargs="*")
    args = ap.parse_args(argv)
    lines = problems_for(args.repo_root, args.paths, staged=args.staged)
    for line in lines:
        print(line, file=sys.stderr)
    if lines:
        print("fragment-check: fix the fragment per skills/_shared/living-doc-fragments.md"
              " and re-stage it", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
