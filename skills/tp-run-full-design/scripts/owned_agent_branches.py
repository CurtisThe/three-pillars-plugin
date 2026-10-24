"""Per-slug record of agent branches a design run owns (fail-open)."""

from __future__ import annotations

import argparse
import os
import re
import sys

_SLUG = re.compile(r"[a-z0-9-]+")
_WT = re.compile(r"agent-([A-Za-z0-9]+)")
_BRANCH = re.compile(r"worktree-agent-[A-Za-z0-9]+")


def branch_for_worktree(path: str) -> str | None:
    m = _WT.fullmatch(os.path.basename(str(path or "").rstrip("/")))
    return f"worktree-agent-{m.group(1)}" if m else None


def _file(root: str, slug: str) -> str:
    return os.path.join(root, ".tp-scratch", "owned-agent-branches", f"{slug}.txt")


def record(root: str, slug: str, worktree_path: str) -> bool:
    try:
        branch = branch_for_worktree(worktree_path)
        if not branch or not _SLUG.fullmatch(slug or ""):
            return False
        p = _file(root, slug)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        fd = os.open(p, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, (branch + "\n").encode("utf-8"))
        finally:
            os.close(fd)
        return True
    except Exception:
        return False


def owned(root: str, slug: str) -> set[str]:
    try:
        if not _SLUG.fullmatch(slug or ""):
            return set()
        with open(_file(root, slug), encoding="utf-8") as fh:
            lines = [ln.strip() for ln in fh]
        return {ln for ln in lines if _BRANCH.fullmatch(ln)}
    except Exception:
        return set()


def main(argv: list[str] | None = None) -> int:
    try:
        ap = argparse.ArgumentParser(description=__doc__)
        sub = ap.add_subparsers(dest="cmd", required=True)
        r = sub.add_parser("record")
        r.add_argument("--slug", required=True)
        r.add_argument("--worktree", required=True)
        r.add_argument("--root", default=".")
        a = ap.parse_args(argv)
        record(a.root, a.slug, a.worktree)
    except SystemExit:
        pass
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
