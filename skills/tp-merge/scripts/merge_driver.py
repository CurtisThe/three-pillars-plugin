#!/usr/bin/env python3
"""Merge driver for `/tp-merge` — merge a base ref into the current worktree branch and
auto-resolve the AUTO-SAFE living-doc conflict classes behind the zero-drop verifier, deferring
everything else to a human.

Flow (design.md §Behavior):
  1. `git merge --no-commit --no-ff <base_ref>` inside `repo` (a worktree on the design branch).
  2. For each conflicted file:
       - living doc  -> reconstruct (base, ours, theirs) from index stages, build a diff3 block,
                        classify -> resolve -> verify.
       - everything else (code/prose files) -> DEFER unconditionally.
  3. Staging policy (load-bearing safety): a file is staged ONLY when
       file_status == RESOLVED  AND  verifier reports zero drops  AND  no conflict marker remains.
     Otherwise the conflict markers are left in the worktree for a human, and the file is reported
     as deferred with a reason. The driver NEVER commits and NEVER pushes — those are the skill's
     human-gated steps after tests pass.

The driver returns a structured report; it does not decide whether to commit. `--abort` cleans up.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from resolve import resolve_file, RESOLVED  # noqa: E402
from verify import verify  # noqa: E402

DEFAULT_LIVING_DOCS = (
    "three-pillars-docs/known_issues.md",
    "three-pillars-docs/product_roadmap.md",
    "three-pillars-docs/architecture.md",
    "three-pillars-docs/vision.md",
)
CONFLICT_MARKERS = ("<<<<<<<", "=======", ">>>>>>>")


@dataclass
class FileOutcome:
    path: str
    kind: str            # "living-doc" | "other"
    action: str          # "auto-resolved" | "partially-resolved" | "deferred"
    reason: str = ""
    classes: list = field(default_factory=list)
    resolved_classes: list = field(default_factory=list)   # mechanical hunks resolved in place
    deferred_classes: list = field(default_factory=list)   # semantic hunks left for the human
    dropped: list = field(default_factory=list)
    renumbered: dict = field(default_factory=dict)


@dataclass
class MergeReport:
    base_ref: str
    merged_clean: bool                       # True if `git merge` had no conflicts at all
    conflicted: list = field(default_factory=list)
    auto_resolved: list = field(default_factory=list)        # fully resolved + staged
    partially_resolved: list = field(default_factory=list)   # mechanical done, semantic markers remain
    deferred: list = field(default_factory=list)             # untouched, human owns it
    outcomes: list = field(default_factory=list)             # [FileOutcome as dict]
    needs_human: bool = False                # True if anything is not fully auto-resolved

    def to_json(self) -> str:
        d = asdict(self)
        return json.dumps(d, indent=2)


def _git(repo: str, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, check=check)


def conflicted_files(repo: str) -> list[str]:
    out = _git(repo, "diff", "--name-only", "--diff-filter=U", check=False).stdout
    return [p for p in out.splitlines() if p.strip()]


def _stage_blob(repo: str, stage: int, path: str) -> str | None:
    """Return the blob content for a merge stage, or None if that stage is absent.

    Distinguishing absent (stage missing → add/add or add/delete) from present-but-empty
    (a legitimately empty file) matters: the former must defer, the latter is a normal merge.
    """
    r = _git(repo, "show", f":{stage}:{path}", check=False)
    return r.stdout if r.returncode == 0 else None


def diff3_text(ours: str, base: str, theirs: str) -> str:
    """Build a `git merge-file --diff3` conflict block from the three versions."""
    with tempfile.TemporaryDirectory() as d:
        po, pb, pt = Path(d) / "ours", Path(d) / "base", Path(d) / "theirs"
        po.write_text(ours); pb.write_text(base); pt.write_text(theirs)
        r = subprocess.run(
            ["git", "merge-file", "-p", "--diff3", str(po), str(pb), str(pt)],
            capture_output=True, text=True,
        )
        return r.stdout


def resolve_living_doc(repo: str, path: str) -> FileOutcome:
    base = _stage_blob(repo, 1, path)
    ours = _stage_blob(repo, 2, path)
    theirs = _stage_blob(repo, 3, path)
    if ours is None or theirs is None:   # add/delete or rename — a content side is absent
        return FileOutcome(path, "living-doc", "deferred",
                           reason="add/delete conflict (a side is absent) — needs human")
    if base is None:                     # add/add — both sides created the file, no common ancestor
        return FileOutcome(path, "living-doc", "deferred",
                           reason="add/add conflict (no common base) — needs human")
    conflict = diff3_text(ours, base, theirs)
    status, lines, results = resolve_file(conflict)
    merged = "\n".join(lines)
    if not merged.endswith("\n"):
        merged += "\n"
    classes = [r.label for r in results]
    # Bucket by actual hunk outcome — a gated/low-confidence mechanical hunk DEFERS, so label
    # membership in MECHANICAL is not the right signal; the resolver's status is.
    resolved_classes = sorted({r.label for r in results if r.status == RESOLVED})
    deferred_classes = sorted({r.label for r in results if r.status != RESOLVED})
    renumbered = {k: v for r in results for k, v in r.renumbered.items()}

    # Zero-drop is the hard gate — checked on whatever we are about to write to the worktree.
    ok, dropped = verify(ours, theirs, merged)
    if not ok:
        # Refuse to touch the file; leave git's original markers for the human.
        return FileOutcome(path, "living-doc", "deferred",
                           reason="verifier flagged content drop — left untouched for human",
                           classes=classes, dropped=[f"{k}:{s}" for k, s in dropped])

    if status == RESOLVED and not any(m in merged for m in CONFLICT_MARKERS):
        # Every hunk mechanical and clean -> fully auto-resolve and stage.
        Path(repo_path(repo, path)).write_text(merged)
        _git(repo, "add", "--", path)
        return FileOutcome(path, "living-doc", "auto-resolved", classes=classes,
                           resolved_classes=resolved_classes, renumbered=renumbered)

    # Mixed file: pre-resolve the mechanical hunks in place, leave semantic hunks as markers.
    # Written to the worktree (shrinks the human's job) but NOT staged — markers remain.
    Path(repo_path(repo, path)).write_text(merged)
    return FileOutcome(path, "living-doc", "partially-resolved",
                       reason=f"mechanical hunks pre-resolved; human must finish: {deferred_classes}",
                       classes=classes, resolved_classes=resolved_classes,
                       deferred_classes=deferred_classes, renumbered=renumbered)


def repo_path(repo: str, path: str) -> str:
    return str(Path(repo) / path)


def merge_back(repo: str, base_ref: str, living_docs=DEFAULT_LIVING_DOCS,
               start_merge: bool = True) -> MergeReport:
    if start_merge:
        mr = _git(repo, "merge", "--no-commit", "--no-ff", base_ref, check=False)
        if mr.returncode == 0 and "CONFLICT" not in (mr.stdout + mr.stderr):
            return MergeReport(base_ref=base_ref, merged_clean=True)

    files = conflicted_files(repo)
    report = MergeReport(base_ref=base_ref, merged_clean=False, conflicted=files)
    living = set(living_docs)
    for path in files:
        if path in living:
            outcome = resolve_living_doc(repo, path)
        else:
            outcome = FileOutcome(path, "other", "deferred",
                                  reason="non-living-doc conflict — always human")
        report.outcomes.append(asdict(outcome))
        bucket = {"auto-resolved": report.auto_resolved,
                  "partially-resolved": report.partially_resolved,
                  "deferred": report.deferred}[outcome.action]
        bucket.append(path)
    report.needs_human = bool(report.partially_resolved or report.deferred)
    return report


def _main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Merge a base ref and auto-resolve living-doc conflicts.")
    ap.add_argument("repo")
    ap.add_argument("base_ref")
    ap.add_argument("--no-start-merge", action="store_true",
                    help="assume a conflicted merge is already in progress; just resolve")
    ap.add_argument("--abort", action="store_true", help="git merge --abort and exit")
    args = ap.parse_args(argv)
    if args.abort:
        _git(args.repo, "merge", "--abort", check=False)
        print("merge aborted")
        return 0
    report = merge_back(args.repo, args.base_ref, start_merge=not args.no_start_merge)
    print(report.to_json())
    # exit 0 = fully resolved/clean; 2 = needs human (deferrals remain)
    return 2 if report.needs_human else 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
