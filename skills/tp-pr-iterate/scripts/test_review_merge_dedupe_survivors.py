"""Survivor precedence + verdict promotion for `review_merge.dedupe`.

Split out of `test_review_merge_dedupe.py` (which owns the collapse predicate)
so both stay under the file-size-guard's test cap. The collapse tests answer
"do these two findings become one?"; these answer "which record survives, and
what verdict does it carry?" — and they cover BOTH routes into a collision, the
exact-match short-circuit and the fuzzy near-miss path, because `dedupe` applies
one survivor rule to both and only the exact branch used to be pinned.

The finding builders live in the sibling module so there is one definition each.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import review_merge  # noqa: E402
from test_review_merge_dedupe import _cop, _cr  # noqa: E402

# A proximate-but-NOT-identical pair of ranges: the fuzzy path, not the
# short-circuit. Asserted explicitly in each near-miss test below.
_NEAR_A = [12, 12]
_NEAR_B = [13, 14]


# ---------- severity outranks summary length ----------


def test_exact_collision_keeps_the_more_specific_summary():
    """Neither side is Copilot and severities tie → the longer summary survives."""
    terse = _cr("cr-terse", "run_round.py", [8, 8], "bad guard")
    specific = _cr(
        "cr-specific", "run_round.py", [8, 8],
        "the empty-list guard runs after the index, so an empty payload raises",
    )
    for order in ([terse, specific], [specific, terse]):
        out = review_merge.dedupe(order)
        assert len(out) == 1
        assert out[0]["finding_id"] == "cr-specific", (
            f"the longer/more specific summary must survive; got {out[0]!r}"
        )


def test_structural_twin_survives_a_wordier_minor_twin():
    """At identical coordinates the more SEVERE verdict wins, either order.

    The round verdict is derived from the surviving findings: if a wordy `minor`
    twin beat a terse `structural` one, the round would report `minor-only`
    while a structural finding had actually been raised.
    """
    structural = _cr("cr-struct", "gate.py", [12, 12], "gate is bypassable", "structural")
    minor = _cr(
        "cr-minor", "gate.py", [12, 12],
        "the comment above this branch still names the old helper and should be reworded",
        "minor",
    )
    for order in ([structural, minor], [minor, structural]):
        out = review_merge.dedupe(order)
        assert len(out) == 1, f"identical coordinates must collapse; got {out!r}"
        assert out[0]["finding_id"] == "cr-struct", (
            f"the structural verdict must survive the longer minor summary; got {out[0]!r}"
        )
        assert out[0]["verdict"] == "structural"
        assert out[0]["merged_from"] == ["cr-minor"], (
            f"dropped twin's provenance must be kept; got {out[0]!r}"
        )


def test_summary_length_still_decides_at_equal_severity():
    """Severity is a tie-BREAKER above length, not a replacement for it."""
    terse = _cr("cr-terse", "gate.py", [12, 12], "bad guard", "minor")
    wordy = _cr(
        "cr-wordy", "gate.py", [12, 12],
        "the empty-list guard runs after the index, so an empty payload raises",
        "minor",
    )
    out = review_merge.dedupe([terse, wordy])
    assert len(out) == 1
    assert out[0]["finding_id"] == "cr-wordy", f"length must still decide a tie; got {out[0]!r}"


# ---------- Copilot keeps the record; the verdict is still promoted ----------
#
# `_survives` tests source precedence BEFORE severity, so Copilot wins a
# collision even when it is the LESS severe side — it owns the `thread_id`
# reply-and-resolve needs. The severity must not go down with the dropped twin:
# the round verdict is read off the survivors, so a lost `structural` reported
# the round as minor-only and the fix round it should have opened was skipped.


def test_copilot_collision_is_promoted_to_the_code_review_structural_verdict():
    """Copilot survives for its thread_id, but wearing the severer verdict."""
    for cop_verdict in ("minor", "unclear"):
        cop = _cop(55, "gate.py", [12, 12], "nit: reword this", verdict=cop_verdict)
        cr = _cr(
            "cr-55", "gate.py", [12, 12],
            "the gate is bypassable when the flag is unset", "structural",
        )
        for order in ([cop, cr], [cr, cop]):
            out = review_merge.dedupe(order)
            assert len(out) == 1, f"identical coordinates must collapse; got {out!r}"
            assert out[0]["source"] == "copilot", (
                f"Copilot must keep the record (thread_id); got {out[0]!r}"
            )
            assert out[0]["thread_id"] == "RT_55", f"thread_id lost: {out[0]!r}"
            assert out[0]["verdict"] == "structural", (
                f"the dropped twin's structural verdict must be promoted; got {out[0]!r}"
            )
            assert out[0]["merged_from"] == ["cr-55"]


def test_promotion_never_downgrades_the_survivor():
    """A Copilot `structural` is not dragged down to a code-review `minor`."""
    cop = _cop(56, "gate.py", [12, 12], "the gate is bypassable", verdict="structural")
    cr = _cr("cr-56", "gate.py", [12, 12], "the wording of this comment is stale", "minor")
    for order in ([cop, cr], [cr, cop]):
        out = review_merge.dedupe(order)
        assert len(out) == 1
        assert out[0]["verdict"] == "structural", f"verdict was downgraded; got {out[0]!r}"


# ---------- the same rules apply on the FUZZY path ----------
#
# `dedupe` runs one survivor rule for both routes, but only the exact branch was
# pinned: a mutation that reverted fuzzy collisions to copilot-or-first-seen
# passed the suite. These near-miss variants close that hole.


def test_near_miss_structural_twin_survives_a_wordier_minor_twin():
    """Severity beats length on a proximate, non-identical range too."""
    structural = _cr(
        "cr-struct", "gate.py", _NEAR_A,
        "the gate is bypassable when the flag is unset", "structural",
    )
    minor = _cr(
        "cr-minor", "gate.py", _NEAR_B,
        "the gate is bypassable when the flag is left unset", "minor",
    )
    assert not review_merge._is_exact_duplicate(structural, minor), (
        "premise broken — this pair must reach the FUZZY path, not the short-circuit"
    )
    for order in ([structural, minor], [minor, structural]):
        out = review_merge.dedupe(order)
        assert len(out) == 1, f"proximate + similar must collapse; got {out!r}"
        assert out[0]["finding_id"] == "cr-struct", (
            f"severity must decide a fuzzy collision too; got {out[0]!r}"
        )
        assert out[0]["verdict"] == "structural"


def test_near_miss_copilot_collision_promotes_the_severer_verdict():
    """Copilot keeps the record and gains the verdict on the fuzzy path too."""
    cop = _cop(88, "converge.py", [30, 31], "the loop bound excludes the final round", "minor")
    cr = _cr(
        "cr-88", "converge.py", [32, 33],
        "the loop bound excludes the final round, so the last review never runs",
        "structural",
    )
    assert not review_merge._is_exact_duplicate(cop, cr), (
        "premise broken — this pair must reach the FUZZY path, not the short-circuit"
    )
    for order in ([cop, cr], [cr, cop]):
        out = review_merge.dedupe(order)
        assert len(out) == 1, f"proximate + similar must collapse; got {out!r}"
        assert out[0]["source"] == "copilot" and out[0]["thread_id"] == "RT_88", (
            f"Copilot must keep the record on a fuzzy collision; got {out[0]!r}"
        )
        assert out[0]["verdict"] == "structural", (
            f"the structural verdict must be promoted on the fuzzy path; got {out[0]!r}"
        )


# ---------- the dead tie: first-seen, so the output stays order-stable ----------


def test_a_dead_tie_keeps_the_first_seen_finding():
    """Equal length, equal severity, neither Copilot → the FIRST finding survives.

    `_survives` ends in `len(a) >= len(b)`, and that `>=` (not `>`) is the only
    thing keeping `dedupe` order-stable. Nothing pinned it: flipping it to `>`
    silently reordered the fix round's finding list on every exact tie.
    """
    first = _cr("cr-first", "gate.py", [12, 12], "the guard is missing here", "minor")
    second = _cr("cr-second", "gate.py", [12, 12], "this branch lacks a guard", "minor")
    assert len(first["summary"]) == len(second["summary"]), (
        "premise broken — the summaries must be the same length"
    )
    out = review_merge.dedupe([first, second])
    assert len(out) == 1, f"identical coordinates must collapse; got {out!r}"
    assert out[0]["finding_id"] == "cr-first", f"ties go to first-seen; got {out[0]!r}"
    assert out[0]["merged_from"] == ["cr-second"], (
        f"the later twin's provenance must be kept; got {out[0]!r}"
    )


# ---------- the thread_id, not the source label, wins the slot ----------


def test_a_thread_less_copilot_record_does_not_take_the_slot_from_a_threaded_one():
    """Copilot precedence is a proxy for the `thread_id` — the thread itself wins.

    `source == "copilot"` wins collisions only because Copilot findings carry
    the `thread_id` reply-and-resolve needs. A Copilot-shaped record with a null
    thread (a file-level row, a hand-built finding) carries nothing, so testing
    the source first let it beat a record that DID hold a thread — dropping
    exactly what the rule exists to protect, and on the longer-summary tie-break
    at that.
    """
    thread_less = dict(
        _cop(70, "gate.py", [12, 12],
             "a considerably longer restatement of the very same defect"),
        thread_id=None,
    )
    threaded = _cop(71, "gate.py", [12, 12], "gate bypass")
    assert len(thread_less["summary"]) > len(threaded["summary"]), (
        "premise broken — the thread-less record must be the wordier one"
    )
    for order in ([thread_less, threaded], [threaded, thread_less]):
        out = review_merge.dedupe(order)
        assert len(out) == 1, f"identical coordinates must collapse; got {out!r}"
        assert out[0]["thread_id"] == "RT_71", (
            f"the record holding a real thread_id must survive; got {out[0]!r}"
        )


# ---------- the caller's own dicts are never written to ----------


def test_dedupe_never_mutates_its_input_findings():
    """`dedupe` reports; it does not edit the lists its callers still hold.

    SKILL.md step 6b rebinds `classified` to the deduped union while the
    normalized Copilot / code-review lists stay in scope, and the fix round's
    envelope and the PR comment are built from those. A promoted `verdict` or a
    `merged_from` written back into an input dict would silently restate a
    source's own findings as something it never said.
    """
    cop = _cop(72, "gate.py", [12, 12], "nit: reword this", verdict="minor")
    cr = _cr("cr-72", "gate.py", [12, 12], "the gate is bypassable", "structural")
    before = [dict(cop), dict(cr)]

    out = review_merge.dedupe([cop, cr])

    assert len(out) == 1 and out[0]["verdict"] == "structural", (
        f"premise broken — this collision must promote a verdict; got {out!r}"
    )
    assert out[0]["merged_from"] == ["cr-72"], f"premise broken; got {out[0]!r}"
    assert [cop, cr] == before, (
        f"dedupe mutated its inputs: {cop!r} / {cr!r} vs {before!r}"
    )


def test_dedupe_never_mutates_its_input_when_the_later_finding_wins():
    """The same guarantee on the branch where the LATER finding takes the slot.

    The test above only exercises first-seen-survives, where the survivor is
    already the `kept` COPY. Reversed, the incoming finding wins the slot — and
    it is the caller's own dict, so it must be copied before the verdict
    promotion and `merged_from` are written. Both orders, or the invariant only
    holds for half the inputs.
    """
    cr = _cr("cr-72", "gate.py", [12, 12], "the gate is bypassable", "structural")
    cop = _cop(72, "gate.py", [12, 12], "nit: reword this", verdict="minor")
    before = [dict(cr), dict(cop)]

    out = review_merge.dedupe([cr, cop])

    assert len(out) == 1 and out[0]["thread_id"] == "RT_72", (
        f"premise broken — the later Copilot record must take the slot; got {out!r}"
    )
    assert out[0]["verdict"] == "structural", (
        f"premise broken — this collision must promote a verdict; got {out[0]!r}"
    )
    assert out[0]["merged_from"] == ["cr-72"], f"premise broken; got {out[0]!r}"
    assert [cr, cop] == before, (
        f"dedupe mutated its inputs: {cr!r} / {cop!r} vs {before!r}"
    )
