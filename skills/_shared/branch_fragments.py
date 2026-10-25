"""List fragments on open design branches whose anchors are gone from the working-tree docs.

design: followups-1024 item 4. #385's diet archived a line that #386's fragment anchored on,
which was fixed by hand in #387. Read-only: never edits a branch, reads remote-tracking refs as
last fetched, no fetch.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import changes_fragment  # noqa: E402
import docs_fold  # noqa: E402
import pending_changes  # noqa: E402

REFS = "refs/remotes/origin/tp/"
CHANGES = "three-pillars-docs/changes/"


def _git(root, *args) -> tuple[int, str]:
    p = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    return p.returncode, p.stdout


def open_refs(root) -> list[str]:
    out = _git(root, "for-each-ref", "--format=%(refname)", REFS)[1]
    refs = [r for r in out.split() if r]
    return [r for r in refs if _git(root, "merge-base", "--is-ancestor", r, "HEAD")[0] != 0]


def ref_fragments(root, ref):
    for path in _git(root, "ls-tree", "--name-only", ref, CHANGES)[1].split():
        if not path.endswith(".md"):
            continue
        if _git(root, "rev-parse", f"{ref}:{path}")[1] == _git(root, "rev-parse", f"HEAD:{path}")[1]:
            continue
        yield path, _git(root, "show", f"{ref}:{path}")[1]


def stale(root) -> list[str]:
    lines = []
    for ref in open_refs(root):
        for path, text in ref_fragments(root, ref):
            frag = changes_fragment.parse(text, stem=Path(path).stem)
            if frag.problems or set(frag.sections) == {"Vision"}:
                continue
            docs = pending_changes.folded_before(root, frag)
            try:
                docs_fold.fold(docs, frag, pr=None, root=root)
            except docs_fold.FoldError as exc:
                lines.append(f"stale-anchor: {frag.slug} ({ref.removeprefix('refs/remotes/')}): {exc}")
    return lines


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="branch_fragments")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check").add_argument("--repo-root", default=".")
    args = ap.parse_args(argv)
    if _git(args.repo_root, "rev-parse", "--git-dir")[0] != 0:
        print(f"branch-fragments: not a git repository: {args.repo_root}", file=sys.stderr)
        return 2
    lines = stale(args.repo_root)
    for line in lines:
        print(line)
    return 1 if lines else 0


if __name__ == "__main__":
    sys.exit(main())
