"""Carry the impl-audit verdict's dispositions into the PR loop (Tier 7).

design: review-convergence, detailed-design-pr-loop.md §D4.

``write`` reads one audit-return envelope (``skills/tp-run-full-design/schemas/
audit-return.v1.json``, or a bare list of findings) and records one entry per
finding that names a file: what the audit found, where, how hard it judged it,
and how it was dispositioned. The list lands at ``<design-dir>/audit-dispositions.json``
(``CARRY``) so a later review round can tell a finding it already dispositioned
from a new one.

``mark`` is the read side: for **round 1** it walks the round's normalized findings
and returns copies with the carry's judgement attached where a finding is the same
one the audit already dispositioned — equal ``file`` (no parent-dir fallback), line
ranges that overlap when both sides cite lines, ``claim_tokens`` Jaccard ≥ 0.5, and
``git diff --quiet <audit_head> <head> -- <file>`` clean, i.e. the audited code has
not moved. A matched copy gets ``dispositioned: true``, ``blocking: false``,
``verdict: "minor"`` and a ``disposition_note`` naming the audit's disposition, so
the round cannot re-block a finding the audit already settled. A finding whose
reproducer actually reproduced it is never dispositioned — the evidence in hand
outranks the carry — and a diff git cannot run (unknown sha, not a repo) counts as
changed, so an unverifiable claim keeps blocking.

An unfiled finding cannot be matched to a diff, so it is not carried.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

_SHARED = str(Path(__file__).resolve().parent)
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

from task_scope import _git_env  # noqa: E402  shipped scrub; git_env is dev-only

CARRY = "audit-dispositions.json"

# The similarity floor between two claims for them to count as the same finding.
CLAIM_JACCARD = 0.5

DISPOSITIONS = ("fixed", "noted")

# Words that carry no signal about *which* defect a claim describes, so a Jaccard
# comparison of claim tokens must not count them. The threshold (not completeness)
# is the safety net: one missed stop-word costs a little similarity, not a match.
STOP_WORDS = frozenset("""
a about above after again against all also any because before being below both but
can could did does doing down during each for from further had has have having her
here his how i if in into it its me more most my no nor not now of off on once only
other our out over own same she some such than that the their then there these they
this those through to too under until very was we were what when where which while
who whom why will with would you your
""".split())

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def claim_tokens(text) -> frozenset:
    """The comparable signature of a claim: lowercase words ≥ 3 chars, minus stop-words."""
    if not isinstance(text, str):
        return frozenset()
    return frozenset(t for t in _TOKEN_RE.findall(text.lower())
                     if len(t) >= 3 and t not in STOP_WORDS)


def _normalise_claim(finding) -> str:
    """Lowercase, whitespace-collapsed claim text from the finding's own wording."""
    for key in ("description", "claim", "title"):
        value = finding.get(key)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split()).lower()
    return ""


def _area(file: str) -> str:
    """The file's parent directory as written, "" for a bare name."""
    parent = PurePosixPath(file).parent.as_posix()
    return "" if parent == "." else parent


def _entry(finding, head) -> dict:
    """One carry entry: what was found, where, how severe, how dispositioned."""
    disposition = finding.get("disposition")
    entry = {
        "file": finding["file"],
        "area": _area(finding["file"]),
        "claim": _normalise_claim(finding),
        "disposition": disposition if disposition in DISPOSITIONS else "noted",
        "severity": finding.get("severity"),
        "audit_head": head,
    }
    if finding.get("line") is not None:
        entry["line"] = finding["line"]
    return entry


def _findings(audit_return_path) -> list:
    """The findings of an audit-return envelope, or of a bare findings list."""
    payload = json.loads(Path(audit_return_path).read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload = payload.get("findings")
    if not isinstance(payload, list):
        raise ValueError("audit-return file must hold a findings[] object or a findings list")
    return [f for f in payload if isinstance(f, dict) and f.get("file")]


def write(design_dir, audit_return_path, *, head) -> Path:
    """Write ``<design_dir>/CARRY`` from an audit-return file; return its path."""
    entries = [_entry(f, head) for f in _findings(audit_return_path)]
    out = Path(design_dir) / CARRY
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")
    return out


def _span(value):
    """(start, end) 1-based inclusive from an int or a list of line numbers, else None."""
    if isinstance(value, (list, tuple)):
        nums = [v for v in value if isinstance(v, int) and not isinstance(v, bool)]
        return (min(nums), max(nums)) if nums else None
    if isinstance(value, int) and not isinstance(value, bool):
        return (value, value)
    return None


def _overlaps(a, b) -> bool:
    return a[0] <= b[1] and b[0] <= a[1]


def _jaccard(a: frozenset, b: frozenset) -> float:
    """Token overlap of two claims; 0.0 when neither says anything comparable."""
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def _default_run_git(cwd, args):
    """→ (returncode, stdout) for `git -C <cwd> <args>`; (1, "") when git never ran."""
    try:
        proc = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True,
                              text=True, env=_git_env())
    except OSError:
        return 1, ""
    return proc.returncode, proc.stdout


def _unchanged(file, audit_head, head, cwd, run_git) -> bool:
    """True iff ``git diff --quiet <audit_head> <head> -- <file>`` is clean.

    Anything but returncode 0 counts as changed — a real diff (1) *and* a diff git
    could not run (unknown sha, not a repo): an unverifiable claim keeps blocking.
    """
    git = run_git or _default_run_git
    returncode, _out = git(cwd, ["diff", "--quiet", str(audit_head), str(head),
                                 "--", str(file)])
    return returncode == 0


def _carry_entries(carry_path) -> list:
    """The carry's entries; [] when the file is missing, unreadable or malformed."""
    try:
        payload = json.loads(Path(carry_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(payload, list):
        return []
    return [e for e in payload if isinstance(e, dict) and e.get("file")]


def _disposition(finding, entry) -> None:
    """Attach the audit's judgement to one marked copy."""
    finding["dispositioned"] = True
    finding["blocking"] = False
    finding["verdict"] = "minor"
    finding["disposition_note"] = (f"audit {entry.get('disposition') or 'noted'} at "
                                   f"{str(entry.get('audit_head') or '')[:12]}")


def mark(findings, carry_path, *, cwd, head, round_no, run_git=None) -> list:
    """Copies of `findings`, with the carry's disposition on the round-1 matches.

    Round 1 is where the audit's verdict is still current, so any other round returns
    the findings untouched and reads no git. Within round 1 a finding matches an entry
    when the file is equal (§D4 dropped the parent-dir fallback), the claim tokens are
    at least ``CLAIM_JACCARD`` alike, the cited line ranges overlap (only when both
    sides cite lines) and the file is unchanged between the entry's ``audit_head`` and
    ``head``. A finding its reproducer actually reproduced is never dispositioned, so
    it is not even diffed. Inputs are never mutated.
    """
    marked = [dict(f) for f in findings]
    entries = _carry_entries(carry_path) if round_no == 1 else []
    if not entries:
        return marked

    cache: dict[tuple, bool] = {}

    def file_unchanged(file, audit_head) -> bool:
        key = (file, audit_head)
        if key not in cache:
            cache[key] = _unchanged(file, audit_head, head, cwd, run_git)
        return cache[key]

    for finding in marked:
        if finding.get("reproduction") == "reproduced":
            continue
        claim = claim_tokens(finding.get("summary") or finding.get("description"))
        span = _span(finding.get("line_range"))
        for entry in entries:
            if entry["file"] != finding.get("file"):
                continue
            if _jaccard(claim, claim_tokens(entry.get("claim"))) < CLAIM_JACCARD:
                continue
            if not file_unchanged(entry["file"], entry.get("audit_head")):
                continue
            entry_span = _span(entry.get("line"))
            if span is not None and entry_span is not None and not _overlaps(span, entry_span):
                continue
            _disposition(finding, entry)
            break
    return marked


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="audit_dispositions.py")
    sub = parser.add_subparsers(dest="command", required=True)
    write_p = sub.add_parser("write", help="write the design dir's audit-dispositions carry")
    write_p.add_argument("--design-dir", required=True, help="design dir holding the carry")
    write_p.add_argument("--audit-return", required=True,
                         help="audit-return JSON (findings[] envelope or list)")
    write_p.add_argument("--head", required=True, help="audit head sha the findings were filed at")
    args = parser.parse_args(argv)
    if args.command != "write":
        parser.error(f"unknown command {args.command!r}")
    try:
        out = write(args.design_dir, args.audit_return, head=args.head)
    except (OSError, ValueError) as exc:
        print(f"audit-dispositions write: error: {exc}", file=sys.stderr)
        return 2
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
