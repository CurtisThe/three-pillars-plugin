"""origin_blame — a finding's `origin` computed from git blame, not from reviewer text.

design: review-convergence (Task 2.1, detailed-design-pr-loop §B)

Review bar: the loop keeps patching an area that needs a rewrite because it cannot
tell whether a finding points at the PR's original code or at a previous fix. A
finding that cites `file:line` is blamed at the reviewed head: a line introduced by
a loop fix commit (any fix commit after round 1's head) is a `regression`, anything
else is `original`. `fix_commits` walks the range `--first-parent --no-merges`, so a
mid-loop base sync and the base commits it brings in are NOT loop fixes — synced
lines stay `original`.

A finding with no file/line, a blame error, or round 1 (`first_head == head`) falls
back to the reviewer's tag through `finding_fields.normalize`, recorded as
`origin_source: "reviewer"`; a computed one is `origin_source: "blame"`. Sentinels
pass through untouched. Inputs are never mutated. Stdlib only; `run_git` is the
injectable seam over `git -C <cwd> <args>`.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
_SHARED = _HERE.parent.parent / "_shared"
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

from finding_class import is_sentinel  # noqa: E402
from finding_fields import normalize as normalize_fields  # noqa: E402

MANIFEST = "angles.json"  # the round manifest (round_scratch.MANIFEST)

ORIGIN_SOURCE_BLAME = "blame"
ORIGIN_SOURCE_REVIEWER = "reviewer"

_ROUND_DIR = re.compile(r"^r(\d+)(\.1)?$")
_BLAME_HEADER = re.compile(r"^([0-9a-f]{7,40}) \d+ \d+")


def _default_run_git(cwd, args):
    """→ (returncode, stdout) for `git -C <cwd> <args>`; (1, "") when git never ran."""
    try:
        proc = subprocess.run(["git", "-C", str(cwd), *args],
                              capture_output=True, text=True)
    except OSError:
        return 1, ""
    return proc.returncode, proc.stdout


def _git(run_git, cwd, *args):
    return (run_git or _default_run_git)(cwd, list(args))


def round_heads(rounds_dir) -> list[str]:
    """The manifest `head` of every `r<N>[.1]` round dir, in round order."""
    root = Path(rounds_dir)
    try:
        entries = list(root.iterdir())
    except OSError:
        return []

    keyed = []
    for entry in entries:
        match = _ROUND_DIR.match(entry.name)
        if not match or not entry.is_dir():
            continue
        rerun = 1 if match.group(2) else 0
        keyed.append(((int(match.group(1)), rerun), entry))

    heads = []
    for _, entry in sorted(keyed, key=lambda pair: pair[0]):
        try:
            manifest = json.loads((entry / MANIFEST).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        head = manifest.get("head") if isinstance(manifest, dict) else None
        if isinstance(head, str) and head:
            heads.append(head)
    return heads


def fix_commits(cwd, first_head, head, *, run_git=None) -> set[str]:
    """Loop fix commits: the first-parent, no-merge range after round 1's head.

    Base-sync merges and the base commits they bring in are excluded, so lines
    that arrived through a sync keep reading `original`.
    """
    if not first_head or not head or first_head == head:
        return set()
    rc, out = _git(run_git, cwd, "rev-list", "--first-parent", "--no-merges",
                   f"{first_head}..{head}")
    if rc != 0:
        return set()
    return {line.strip() for line in out.splitlines() if line.strip()}


def _line_span(finding) -> tuple[int, int] | None:
    """(start, end) 1-based inclusive, or None when the finding cites no line."""
    span = finding.get("line_range")
    if not isinstance(span, (list, tuple)) or not span:
        return None
    start = span[0]
    if isinstance(start, bool) or not isinstance(start, int) or start <= 0:
        return None
    end = span[1] if len(span) > 1 else start
    if isinstance(end, bool) or not isinstance(end, int) or end < start:
        end = start
    return start, end


def _blamed(run_git, cwd, head, file, span) -> set[str] | None:
    """Commit shas blamed for `file`'s lines at `head`, or None when blame fails."""
    start, end = span
    rc, out = _git(run_git, cwd, "blame", "--porcelain", "-L", f"{start},{end}",
                   head, "--", file)
    if rc != 0:
        return None
    commits = set()
    for line in out.splitlines():
        match = _BLAME_HEADER.match(line)
        if match:
            commits.add(match.group(1))
    return commits or None


def _reviewer_tagged(finding) -> dict:
    """The reviewer's own tag through `normalize`, flagged as reviewer-sourced."""
    result = normalize_fields(finding)
    result["origin_source"] = ORIGIN_SOURCE_REVIEWER
    return result


def classify(findings, *, cwd, head, first_head, run_git=None) -> list:
    """Return copies of `findings` with a computed `origin` + `origin_source`.

    Blame wins whenever it can run; the reviewer's tag is the fallback only when
    there is no file/line, blame errors, or the round is round 1.
    """
    blameable = bool(head) and bool(first_head) and first_head != head
    fixes = None
    result = []
    for finding in findings:
        if is_sentinel(finding):
            result.append(dict(finding))
            continue
        file = finding.get("file")
        span = _line_span(finding)
        if not blameable or not isinstance(file, str) or not file or span is None:
            result.append(_reviewer_tagged(finding))
            continue
        if fixes is None:
            fixes = fix_commits(cwd, first_head, head, run_git=run_git)
        blamed = _blamed(run_git, cwd, head, file, span)
        if blamed is None:
            result.append(_reviewer_tagged(finding))
            continue
        tagged = normalize_fields(finding)
        tagged["origin"] = ("regression" if blamed & fixes else "original")
        tagged["origin_source"] = ORIGIN_SOURCE_BLAME
        result.append(tagged)
    return result
