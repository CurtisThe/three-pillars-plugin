#!/usr/bin/env python3
"""Resolve a fold conflict that is only the design's append-only `decisions.md`.

Run mid-merge (tier 5.6 fold). When exactly `three-pillars-docs/tp-designs/{slug}/decisions.md`
is unmerged and both sides only appended to the merge base, write base + tp tail + candidate tail
+ one ruling entry, stage the file and print `{"status": "resolved", ...}`. Every other shape prints
`not-applicable` and leaves the tree as found. No commit is made. Stdlib only.

Exit codes: 0 resolved, 1 not-applicable, 2 bad slug.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

_MERGE_SCRIPTS = Path(__file__).resolve().parents[2] / "tp-merge-from-main" / "scripts"
if str(_MERGE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_MERGE_SCRIPTS))

from decisions_union import union_decisions  # noqa: E402

_SLUG = re.compile(r"[a-z0-9-]+")

_RULING = (
    "\n### [tp-run-full-design/tier-5.6] fold-decisions-union\n"
    "**Question**: decisions.md conflicted in the fold merge; how is it resolved?\n"
    "**Decided**: keep every line of both sides, tp side first, then the candidate side.\n"
    "**Reasoning**: only decisions.md conflicted and both sides only appended to the merge base.\n"
    "**Confidence**: High\n"
)


def _na(reason: str, path: str = "") -> dict:
    return {"status": "not-applicable", "path": path, "reason": reason}


def _git(repo: str, *args: str) -> bytes:
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, check=True).stdout


def _counts(text: str) -> Counter:
    return Counter(line for line in text.split("\n") if line.strip())


def resolve_fold(repo: str, slug: str) -> dict:
    """Union-resolve the design's decisions.md fold conflict, or report not-applicable."""
    try:
        return _resolve(repo, slug)
    except Exception as exc:  # noqa: BLE001 - contract: never raises
        return _na(f"error: {exc}")


def _resolve(repo: str, slug: str) -> dict:
    if not _SLUG.fullmatch(slug or ""):
        return _na("bad-slug")
    rel = f"three-pillars-docs/tp-designs/{slug}/decisions.md"
    git_dir = Path(_git(repo, "rev-parse", "--absolute-git-dir").decode().strip())
    if not (git_dir / "MERGE_HEAD").exists():
        return _na("no-merge-in-progress")
    raw = _git(repo, "diff", "--name-only", "--diff-filter=U", "-z")
    unmerged = [p for p in raw.decode("utf-8", "replace").split("\0") if p]
    if unmerged != [rel]:
        return _na("unmerged-set-mismatch", rel)
    try:
        base, ours, theirs = (_git(repo, "show", f":{n}:{rel}").decode("utf-8") for n in (1, 2, 3))
    except (subprocess.CalledProcessError, UnicodeDecodeError):
        return _na("missing-stage-or-non-utf8", rel)
    merged = union_decisions(base, ours, theirs)
    if merged is None:
        return _na("not-append-only", rel)
    got = _counts(merged)
    if not merged.startswith(base) or any(got[k] < v for side in (ours, theirs) for k, v in _counts(side).items()):
        return _na("dropped-line", rel)
    (Path(repo) / rel).write_bytes((merged + _RULING).encode("utf-8"))
    _git(repo, "add", "--", rel)
    return {"status": "resolved", "path": rel, "reason": ""}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--slug", required=True)
    ap.add_argument("--repo", default=".")
    args = ap.parse_args(argv)
    if not _SLUG.fullmatch(args.slug):
        print(json.dumps(_na("bad-slug")))
        return 2
    res = resolve_fold(args.repo, args.slug)
    print(json.dumps(res))
    return 0 if res["status"] == "resolved" else 1


if __name__ == "__main__":
    sys.exit(main())
