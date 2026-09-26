"""Deterministic verdict rule for Shape C verdict-only `--auto` audits.

Used by `/tp-implementation-audit --auto` to map a list of finding
confidences to a verdict + exit code. The Shape C *dispatch* path
(`/tp-design-audit --auto` auto-applies vs escalates) is out of scope —
it lives inline in that SKILL.md, not here.

Rule:
    []                                          -> ("PASS", 0)
    all values == "High"                        -> ("PASS WITH NOTES", 0)
    any value in {"Medium", "Low"}              -> ("NEEDS WORK", 1)

Inputs are strict: any value outside {"High", "Medium", "Low"} raises
ValueError. A policy function should fail loudly on garbage rather than
silently fall through to PASS WITH NOTES on a typo like "high" or "Med".

A non-zero exit code on NEEDS WORK lets the orchestrator escalate.
"""

from __future__ import annotations

VALID_CONFIDENCES = ("High", "Medium", "Low")


def compute_verdict(confidences: list[str]) -> tuple[str, int]:
    if not confidences:
        return ("PASS", 0)
    unknown = [c for c in confidences if c not in VALID_CONFIDENCES]
    if unknown:
        raise ValueError(
            f"unknown confidence value(s) {unknown!r}; expected one of {VALID_CONFIDENCES}"
        )
    if any(c in ("Medium", "Low") for c in confidences):
        return ("NEEDS WORK", 1)
    return ("PASS WITH NOTES", 0)


# Certification join (design audit-pass-does-not-bind). Rank order, lowest
# first; the code is the exit code the orchestrator branches on.
VERDICT_ORDER = ("PASS", "PASS WITH NOTES", "KNOWN BYPASS", "UNVERIFIED", "NEEDS WORK")
VERDICT_CODE = {"PASS": 0, "PASS WITH NOTES": 0, "KNOWN BYPASS": 0,
                "UNVERIFIED": 2, "NEEDS WORK": 1}
STATUS_VERDICT = {"binds": "PASS", "known-bypass": "KNOWN BYPASS",
                  "unverified": "UNVERIFIED", "not-binding": "NEEDS WORK",
                  "false-red": "NEEDS WORK"}


def combine_verdict(base: str, statuses: list[str]) -> tuple[str, int]:
    """Join `base` with each claim status over VERDICT_ORDER; return (verdict, code).

    `combine_verdict(v, [])` is `(v, code(v))`. The join is commutative and
    idempotent, so fold order never matters. Unknown inputs raise ValueError.
    """
    if base not in VERDICT_CODE:
        raise ValueError(f"unknown base verdict {base!r}; expected one of {VERDICT_ORDER}")
    unknown = [s for s in statuses if s not in STATUS_VERDICT]
    if unknown:
        raise ValueError(
            f"unknown claim status(es) {unknown!r}; expected one of {tuple(STATUS_VERDICT)}"
        )
    verdict = max([base] + [STATUS_VERDICT[s] for s in statuses], key=VERDICT_ORDER.index)
    return (verdict, VERDICT_CODE[verdict])
