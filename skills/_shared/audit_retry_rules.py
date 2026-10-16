"""Audit retry rules: the lows predicate and the post-patch recheck predicate.

design: run-throughput (detailed-design-part-c.md, "Lows rule predicate", Task 5.3)
and review-convergence (detailed-design-phase-check.md §F1, Task 12.1).

``lows_only(findings)`` is true when every finding whose ``category`` is not
``"map-check"`` has ``severity == "minor"``, whatever its ``confidence``.
A finding without ``severity`` counts as not minor (fail-safe). Map-check
findings are ignored by this predicate (they keep their own escalate-at-once
path), so a list containing only map-check findings is True, and an empty
list is vacuously True.

After the one allowed patch, ``verdict_after_patch(findings)`` decides whether
the cycle spends its single re-check or stops with the remaining findings as
PR notes. Only an open HIGH (``severity == HIGH``, map-check findings excluded)
justifies a re-check; everything else is a note.
"""
from __future__ import annotations

import argparse
import json
import sys

HIGH = "critical"  # the synth's top severity (build_synth_prompt SEVERITIES)


def lows_only(findings) -> bool:
    """True when all non-map-check findings are severity 'minor'."""
    for f in findings:
        if f.get("category") == "map-check":
            continue
        if f.get("severity") != "minor":
            return False
    return True


def open_high(findings) -> bool:
    """True when any non-map-check finding has severity ``HIGH``.

    Map-check findings escalate on their own path, so a map-check finding
    never triggers a re-check here.
    """
    for f in findings:
        if f.get("category") == "map-check":
            continue
        if f.get("severity") == HIGH:
            return True
    return False


def note_only(f) -> bool:
    """True when a finding is carried as a PR note instead of a fix.

    A ``minor`` finding is always a note; a ``medium`` is a note only when it
    carries no non-empty ``run_failure`` (nothing actually broke). Anything
    else — including a missing severity — is not a note (fail-safe).
    """
    severity = f.get("severity")
    if severity == "minor":
        return True
    if severity == "medium":
        return not f.get("run_failure")
    return False


def recheck(findings) -> bool:
    """True iff an open HIGH survives the patch, so the re-check is spent."""
    return open_high(findings)


def verdict_after_patch(findings) -> str:
    """The cycle's verdict after the one allowed patch."""
    return "re-check" if open_high(findings) else "pass-with-notes"


def _load_findings(path: str):
    """Read F: a JSON list of findings, or an object with a 'findings' key."""
    with open(path, encoding="utf-8") as fh:
        payload = json.load(fh)
    if isinstance(payload, dict):
        payload = payload.get("findings")
    if not isinstance(payload, list):
        raise ValueError("findings file must hold a list or an object with a 'findings' key")
    return payload


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="audit_retry_rules.py")
    sub = parser.add_subparsers(dest="command", required=True)
    lows = sub.add_parser("lows-only", help="exit 0 when lows_only(findings) is true, 1 when false")
    lows.add_argument("--findings", required=True, help="JSON file of findings")
    rec = sub.add_parser("recheck", help="exit 0 when a re-check is owed, 1 for pass-with-notes")
    rec.add_argument("--findings", required=True, help="JSON file of findings")
    args = parser.parse_args(argv)
    try:
        findings = _load_findings(args.findings)
    except (OSError, ValueError) as exc:
        print(f"{args.command}: error: {exc}", file=sys.stderr)
        return 2
    if args.command == "lows-only":
        verdict = lows_only(findings)
        print(f"lows-only: {'yes' if verdict else 'no'}")
        return 0 if verdict else 1
    verdict = verdict_after_patch(findings)
    print(f"recheck: {verdict}")
    return 0 if verdict == "re-check" else 1


if __name__ == "__main__":
    sys.exit(main())
