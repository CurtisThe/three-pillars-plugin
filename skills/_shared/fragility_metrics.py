"""fragility_metrics.py — rounds per PR and fragility-class share.

design: fragile-test-prevention (detailed-design-stages.md, `fragility_metrics.py`).

Reads the flushed `[tp-pr-iterate] round …` lines written by
`finding_class.class_line` from committed `decisions.md` files under
`three-pillars-docs/tp-designs/*/` and `three-pillars-docs/completed-tp-designs/*/`.
It never reads the proof root (`<repo>/.three-pillars/review-proof`), which
`/tp-post-merge` deletes with the worktree — only the two design globs above
are ever read.

A round line's `frag=open-ended:<n>,change-detector:<n>,blocklist:<n>` token
(added in this design) tallies the three structural fragility classes. A line
flushed before that change carries no `frag=` token at all; its `blocking=<n>`
count is attributed wholesale to `unclassified`, per the design text.

`--baseline FILE` compares the computed rounds-per-PR against a committed
baseline (e.g. `.three-pillars/fragility-baseline.json`) — a delta only, no
verdict; this module reports, it never gates. A delta exists only when BOTH
sides carry a measured `rounds` figure: a design whose decisions.md has no
round line reports `rounds: null` (unmeasured, never 0), and a baseline entry
without an integer `rounds` (the #162/#165 entries record blockers only) is
unmeasured too. Such an entry's status names the unmeasured side(s) instead.

Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

FRAG_CLASSES = ("open-ended", "change-detector", "blocklist")
ALL_CLASSES = FRAG_CLASSES + ("unclassified",)

_DESIGN_GLOBS = ("three-pillars-docs/tp-designs", "three-pillars-docs/completed-tp-designs")

_ROUND_RE = re.compile(r"^\[tp-pr-iterate\] round (\d+)\b")
_BLOCKING_RE = re.compile(r"\bblocking=(\d+)\b")
_FRAG_RE = re.compile(r"\bfrag=(\S+)\b")


def _parse_frag_token(token: str) -> dict:
    """`open-ended:<n>,change-detector:<n>,blocklist:<n>` -> `{class: n}`."""
    out = {c: 0 for c in FRAG_CLASSES}
    for part in token.split(","):
        cls, sep, n = part.partition(":")
        if sep and cls in out and n.isdigit():
            out[cls] = int(n)
    return out


def parse_round_lines(text: str) -> list[dict]:
    """Each flushed `[tp-pr-iterate] round …` line -> `{round, blocking, frag}`.

    `frag` is the parsed token dict, or `None` when the line has no `frag=`
    token (a pre-migration line).
    """
    rounds = []
    for raw in text.splitlines():
        line = raw.strip()
        match = _ROUND_RE.match(line)
        if not match:
            continue
        blocking_match = _BLOCKING_RE.search(line)
        frag_match = _FRAG_RE.search(line)
        rounds.append({
            "round": int(match.group(1)),
            "blocking": int(blocking_match.group(1)) if blocking_match else 0,
            "frag": _parse_frag_token(frag_match.group(1)) if frag_match else None,
        })
    return rounds


def find_decision_files(root) -> list[Path]:
    """Committed `decisions.md` under the two design roots only."""
    root = Path(root)
    found = []
    for base in _DESIGN_GLOBS:
        found.extend(sorted((root / base).glob("*/decisions.md")))
    return found


def pr_id_for(path: Path) -> str:
    """The design directory name stands in for the PR its loop ran against."""
    return path.parent.name


def collect(root) -> dict:
    """Per-PR `{rounds, frag: {class: n}}` built from every committed decisions.md.

    `rounds` is the count of flushed round lines, or `None` when the file has
    none: a decisions.md that predates the flushed line format is unmeasured,
    which is not the same as a measured 0.
    """
    report: dict = {}
    for path in find_decision_files(root):
        pr = pr_id_for(path)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        entry = report.setdefault(pr, {"rounds": None, "frag": {c: 0 for c in ALL_CLASSES}})
        for rnd in parse_round_lines(text):
            entry["rounds"] = (entry["rounds"] or 0) + 1
            if rnd["frag"] is None:
                entry["frag"]["unclassified"] += rnd["blocking"]
            else:
                for cls in FRAG_CLASSES:
                    entry["frag"][cls] += rnd["frag"][cls]
    return report


def frag_share(frag: dict) -> dict:
    """Each class's count as a fraction of the PR's total tallied findings."""
    total = sum(frag.values())
    if total == 0:
        return {c: 0.0 for c in ALL_CLASSES}
    return {c: frag[c] / total for c in ALL_CLASSES}


def build_report(root) -> dict:
    """`{"prs": {pr: {rounds, frag, frag_share}}}` for every committed decisions.md."""
    collected = collect(root)
    prs = {}
    for pr, entry in collected.items():
        prs[pr] = {
            "rounds": entry["rounds"],
            "frag": entry["frag"],
            "frag_share": frag_share(entry["frag"]),
        }
    return {"prs": prs}


def _measured_rounds(entry) -> "int | None":
    """An entry's `rounds` when it is a real integer count, else `None` (unmeasured)."""
    rounds = entry.get("rounds") if isinstance(entry, dict) else None
    return rounds if isinstance(rounds, int) and not isinstance(rounds, bool) else None


def compare(report: dict, baseline: dict) -> dict:
    """Per-PR `{status, ...}` for every PR the baseline names.

    The report keys by design directory (`pr_id_for`), while a baseline may key by
    PR number and name the design in `design` (`.three-pillars/fragility-baseline.json`
    does), so an entry matches its key first and its `design` second. `status` is
    `"missing"` when neither matches. A delta is computed only when both sides have a
    measured `rounds` figure: then `"ok"` with
    `rounds_delta = current_rounds - baseline_rounds`. Otherwise `"unmeasured"` with
    `unmeasured` naming the side(s) without one (`"baseline"`, `"current"`) and no
    delta — a missing figure is never read as 0.
    """
    out = {}
    prs = report.get("prs", {})
    for pr, base_entry in (baseline.get("prs") or {}).items():
        design = base_entry.get("design") if isinstance(base_entry, dict) else None
        current = prs.get(pr) or (prs.get(design) if design is not None else None)
        if current is None:
            out[pr] = {"status": "missing"}
            continue
        base_rounds = _measured_rounds(base_entry)
        current_rounds = _measured_rounds(current)
        unmeasured = [side for side, rounds in (("baseline", base_rounds),
                                                ("current", current_rounds))
                      if rounds is None]
        if unmeasured:
            out[pr] = {"status": "unmeasured", "unmeasured": unmeasured}
            continue
        out[pr] = {"status": "ok", "rounds_delta": current_rounds - base_rounds}
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="fragility_metrics")
    ap.add_argument("--root", default=".")
    ap.add_argument("--baseline")
    args = ap.parse_args(argv)

    report = build_report(args.root)
    if args.baseline:
        baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
        report["comparison"] = compare(report, baseline)

    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
