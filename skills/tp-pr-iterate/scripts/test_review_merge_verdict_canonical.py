"""Verdict canonicalization: one spelling of `structural` from end to end.

The severity rules inside `dedupe` compare verdicts case-insensitively
(`_verdict_rank` lowercases) while every downstream consumer tests the STORED
string exactly — `loop_driver._detect_conflicts` and the `has_structural` behind
the round's `minor-only` verdict both do `== "structural"`. `/code-review`
findings reach `normalize_codereview` unvalidated, so a `"Structural"` used to
satisfy the first reading and fail the second: it ranked structural, took the
record on the length tiebreak, and the round then reported minor-only with a
structural finding in it.

These pin the fix at its three points: the normalization boundary (both
sources), the promotion write inside `dedupe`, and `_verdict_rank`'s own
normalization — which the boundary now makes redundant for normalized findings
and which must stay for the hand-built ones.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import review_merge  # noqa: E402
import review_merge_dedupe  # noqa: E402
from test_review_merge_dedupe import _cop, _cr  # noqa: E402


# ---------- the normalization boundary ----------


def test_codereview_verdict_casing_is_canonicalized():
    """`"Structural"` / `" STRUCTURAL "` from a `/code-review` angle → `"structural"`."""
    for raw in ("Structural", " STRUCTURAL ", "structural\n"):
        out = review_merge.normalize_codereview(
            {"finding_id": "cr-1", "file": "gate.py", "line_range": [12, 12],
             "summary": "the gate is bypassable", "verdict": raw}
        )
        assert out["verdict"] == "structural", (
            f"{raw!r} must normalize to the canonical 'structural'; got {out['verdict']!r}"
        )


def test_codereview_minor_casing_is_canonicalized():
    out = review_merge.normalize_codereview(
        {"finding_id": "cr-1", "file": "gate.py", "line_range": [12, 12],
         "summary": "reword this", "verdict": "Minor"}
    )
    assert out["verdict"] == "minor", f"got {out['verdict']!r}"


def test_copilot_verdict_casing_is_canonicalized():
    """The Copilot normalizer canonicalizes too — the same field, the same rules."""
    out = review_merge.normalize_copilot(
        {"comment_id": 7, "thread_id": "RT_7", "path": "gate.py", "line_range": [12, 12],
         "body": "the gate is bypassable", "verdict": " Structural "}
    )
    assert out["verdict"] == "structural", f"got {out['verdict']!r}"


def test_unknown_verdict_keeps_each_sources_existing_default():
    """Coercion is casing/whitespace only: an off-enum value keeps the old default.

    `/code-review` defaults to `structural` (fail-closed) and Copilot to
    `unclear` (its comments carry no verdict of their own). The coercer must not
    quietly re-point either one.
    """
    cr = review_merge.normalize_codereview(
        {"finding_id": "cr-1", "file": "gate.py", "line_range": [12, 12],
         "summary": "s", "verdict": "blocker"}
    )
    assert cr["verdict"] == "structural", f"got {cr['verdict']!r}"
    cop = review_merge.normalize_copilot(
        {"comment_id": 7, "thread_id": "RT_7", "path": "gate.py", "line_range": [12, 12],
         "body": "s", "verdict": 3}
    )
    assert cop["verdict"] == "unclear", f"got {cop['verdict']!r}"
    missing = review_merge.normalize_copilot(
        {"comment_id": 8, "thread_id": "RT_8", "path": "gate.py", "line_range": [12, 12],
         "body": "s"}
    )
    assert missing["verdict"] == "unclear", f"got {missing['verdict']!r}"


# ---------- through dedupe ----------


def test_case_varied_twin_survivor_carries_the_canonical_verdict():
    """A `"Structural"` twin vs a canonical one → the survivor reads `"structural"`.

    The two rank EQUAL (rank is case-insensitive), so the length tiebreak decides
    the record — and the wordier one here is the case-varied twin. Whichever wins,
    the stored verdict has to satisfy the downstream `== "structural"` test.
    """
    varied = _cr(
        "cr-varied", "gate.py", [12, 12],
        "the gate is bypassable when the roster is empty and nothing re-checks it",
        "Structural",
    )
    canonical = _cr("cr-canon", "gate.py", [12, 12], "gate is bypassable", "structural")
    for order in ([varied, canonical], [canonical, varied]):
        out = review_merge.dedupe(order)
        assert len(out) == 1, f"identical coordinates must collapse; got {out!r}"
        assert out[0]["verdict"] == "structural", (
            f"survivor must carry the canonical verdict; got {out[0]!r}"
        )


def test_promotion_onto_a_copilot_record_stores_the_canonical_verdict():
    """A Copilot `"Minor"` promoted by a code-review `"structural"` stores `"structural"`."""
    cop = _cop(72, "gate.py", [12, 12], "nit: reword this", verdict="Minor")
    cr = _cr("cr-72", "gate.py", [12, 12], "the gate is bypassable", "Structural")
    out = review_merge.dedupe([cop, cr])
    assert len(out) == 1 and out[0]["thread_id"] == "RT_72", (
        f"premise broken — the Copilot record must take the slot; got {out!r}"
    )
    assert out[0]["verdict"] == "structural", (
        f"the promoted verdict must be canonical; got {out[0]!r}"
    )


def test_promote_verdict_canonicalizes_an_unnormalized_dropped_twin():
    """`_promote_verdict` is the backstop for findings that skipped normalization.

    Hand-built findings (loop-driver sentinels, test fixtures, a caller feeding
    `dedupe` raw dicts) never pass the normalizer, so the write itself must
    canonicalize rather than copy the dropped twin's raw string.
    """
    survivor = {"verdict": "minor"}
    review_merge_dedupe._promote_verdict(survivor, {"verdict": " Structural "})
    assert survivor["verdict"] == "structural", (
        f"the promotion stored a non-canonical verdict; got {survivor!r}"
    )


def test_promote_verdict_still_never_downgrades():
    survivor = {"verdict": "structural"}
    review_merge_dedupe._promote_verdict(survivor, {"verdict": "Minor"})
    assert survivor["verdict"] == "structural", f"downgraded; got {survivor!r}"


# ---------- the rank function's own normalization ----------


def test_verdict_rank_ignores_case_and_whitespace():
    """Rank normalizes what it is handed — dropping `.lower()` must fail here.

    The boundary coercion makes this redundant for NORMALIZED findings, which is
    the point of pinning it separately: the two defenses are independent, and
    `dedupe` is called with raw dicts often enough that neither may be removed
    on the strength of the other.
    """
    for raw in ("Structural", " STRUCTURAL ", "structural"):
        assert review_merge_dedupe._verdict_rank({"verdict": raw}) == 2, (
            f"{raw!r} must rank as structural"
        )
    for raw in ("Minor", " minor\t"):
        assert review_merge_dedupe._verdict_rank({"verdict": raw}) == 1, (
            f"{raw!r} must rank as minor"
        )
    assert review_merge_dedupe._verdict_rank({"verdict": "unclear"}) == 0
    assert review_merge_dedupe._verdict_rank({}) == 0
