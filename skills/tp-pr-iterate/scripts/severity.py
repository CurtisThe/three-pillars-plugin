"""severity — the one severity authority for /tp-pr-iterate findings.

design: review-convergence (Phase 1, D1)

Before this module the blocking flag was written in four places
(`finding_class.coerce`, `reproduce.run_reproducers`, `_apply_adopted`,
`review_merge_dedupe`), so an Opus-downgraded claim could be re-blocked by a
passing reproducer (#231). This module is the single place that decides whether a
finding blocks, and the single place that writes the final `blocking`/`verdict`.

A finding blocks only when it is a real finding (not a degraded sentinel), its
`blocking` tag is True, Opus's check did not downgrade it, and its reproducer was
not refuted. An `inconclusive` reproducer run keeps Opus's call — absence of
evidence is not evidence of absence.

Stdlib only; computes, never shells out (C1).
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from finding_class import is_sentinel  # noqa: E402

REPRODUCTIONS = ("reproduced", "refuted", "inconclusive")


def opus_downgraded(f) -> bool:
    """True iff Opus's check recorded `escape.disposition == "downgraded"`.

    A missing or malformed `escape` (non-dict) is not a downgrade.
    """
    escape = f.get("escape")
    if not isinstance(escape, dict):
        return False
    return escape.get("disposition") == "downgraded"


def is_blocking(f) -> bool:
    """True iff `f` is a real finding that blocks: tagged blocking, kept by Opus,
    and not refuted by a reproducer run."""
    if is_sentinel(f):
        return False
    if f.get("blocking") is not True:
        return False
    if opus_downgraded(f):
        return False
    return f.get("reproduction") != "refuted"


def _flip_note(f) -> str:
    """Why a blocking finding was flipped to non-blocking ("" when neither applies)."""
    if opus_downgraded(f):
        return "opus-downgraded"
    if f.get("reproduction") == "refuted":
        return "refuted"
    return ""


def finalize(findings) -> list:
    """Return copies of `findings` with `blocking`/`verdict` set from `is_blocking`.

    Sentinels are copied but never re-severitied — a degraded review is not a
    finding. When a flip from blocking to non-blocking happens, the copy gains
    `severity_note` naming the reason (`"opus-downgraded"` or `"refuted"`); a
    finding that was already non-blocking gets no note. The input list and its
    dicts are never mutated.
    """
    out = []
    for f in findings:
        copy = dict(f)
        if is_sentinel(copy):
            out.append(copy)
            continue
        blocking = is_blocking(copy)
        if not blocking and f.get("blocking") is True:
            note = _flip_note(copy)
            if note:
                copy["severity_note"] = note
        copy["blocking"] = blocking
        copy["verdict"] = "structural" if blocking else "minor"
        out.append(copy)
    return out
