"""What counts as a line range in the conflict scan — anchors and span order.

Split from `test_loop_driver_conflict_keys.py` (which owns the deferral KEY) so
each file stays inside the size cap and each owns one question. Scope here: the
range side of `_detect_conflicts` — which ranges can conflict at all, and how a
range's endpoints are read.

Seed: the anchorless `[0, 0]` sentinel is truthy and overlaps itself, so two
UNRELATED file-level findings on one path deferred each other, `kept` emptied,
and `_apply_conflicts` flipped the round to `[all-conflicting-deferred-to-human]`
with real, non-conflicting work still in it.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import loop_driver  # noqa: E402
import review_merge  # noqa: E402

_NOW = datetime(2026, 5, 31, 12, 0, 0, tzinfo=timezone.utc)


def _state() -> dict:
    """The minimum iterate-state `_apply_conflicts` reads/appends to."""
    return {
        "phase": "fixing",
        "iteration": 2,
        "started_at": (_NOW - timedelta(hours=2)).isoformat(),
        "transitions": [],
    }


def _file_level(cid: str, file: str) -> dict:
    """A Copilot comment with NO line anchor — normalizes to `[0, 0]`.

    This is the real shape of a GitHub file-level or outdated review comment and
    of every `thread_resolver.list_review_threads` row: a path, a body, and no
    line field at all.
    """
    return review_merge.normalize_copilot(
        {"comment_id": cid, "thread_id": f"RT_{cid}", "path": file,
         "body": f"{cid} is about {file} as a whole", "verdict": "structural"}
    )


def _anchored(cid: str, file: str, rng: list[int]) -> dict:
    return review_merge.normalize_copilot(
        {"comment_id": cid, "thread_id": f"RT_{cid}", "path": file,
         "line_range": rng, "body": f"{cid} on {file}", "verdict": "structural"}
    )


# ---------- the sentinel is not a location ----------


def test_two_anchorless_findings_on_one_file_do_not_conflict():
    """`[0, 0]` twice over is two place-less findings, not one shared hunk."""
    classified = [_file_level("c1", "a.py"), _file_level("c2", "a.py")]
    assert [f["line_range"] for f in classified] == [[0, 0], [0, 0]], (
        "premise broken — an unanchored comment must normalize to the sentinel"
    )

    deferred, kept = loop_driver._detect_conflicts(classified)

    assert deferred == [], f"anchorless findings must not defer each other; got {deferred!r}"
    assert kept == classified, f"both must stay in the round; got {kept!r}"


def test_an_anchorless_finding_never_conflicts_with_an_anchored_one():
    """The sentinel is not line 0, so it does not share a hunk that touches 0.

    The anchored range starts AT 0 deliberately. There is no slack padding on
    this path — that is `review_merge_dedupe._line_proximity`'s business; the
    conflict scan compares raw inclusive spans, so `[0, 0]` vs `[0, 4]` DOES
    overlap arithmetically and only the anchor gate keeps them apart. A range
    starting at 1 would pass with the gate removed and prove nothing.
    """
    classified = [_file_level("c1", "a.py"), _anchored("c2", "a.py", [0, 4])]

    deferred, kept = loop_driver._detect_conflicts(classified)

    assert deferred == [], f"the sentinel must not reach a real range; got {deferred!r}"
    assert kept == classified


def test_an_all_anchorless_round_is_not_all_conflicting():
    """The bug at the level above: the terminal that swallowed the round.

    Every finding here is real work on three files. Reading the sentinel as a
    range deferred all of them, emptied `kept`, and handed the PR to a human.
    """
    classified = [
        _file_level("c1", "a.py"),
        _file_level("c2", "a.py"),
        _file_level("c3", "b.py"),
    ]

    next_state, kept, terminal = loop_driver._apply_conflicts(_state(), classified, now=_NOW)

    assert not terminal, "nothing conflicted — the round must not terminate"
    assert kept == classified
    assert next_state["transitions"] == [], "a no-conflict round appends no deferral note"


def test_a_real_overlap_on_an_anchored_pair_still_defers():
    """Guard the other side: skipping sentinels must not skip real conflicts."""
    classified = [_anchored("c1", "a.py", [10, 20]), _anchored("c2", "a.py", [15, 25])]

    deferred, kept = loop_driver._detect_conflicts(classified)

    assert sorted(deferred) == ["0:c1", "1:c2"], f"a real overlap must defer; got {deferred!r}"
    assert kept == []


# ---------- one coercer: `_span` decides type, order and anchor ----------


def test_span_rejects_everything_that_names_no_place():
    """The unanchored table — each row is a shape untrusted output really sends.

    `_span` is the ONLY gate, so anything it lets through reaches
    `_ranges_overlap` raw. Mirrors `review_merge_dedupe._norm_range`: wrong
    type, short arity, non-numeric or `bool` elements, and any span with no
    positive coordinate.
    """
    for r in (None, [], [7], "12", ["a", "b"], [True, 2], [0, 0], [-5, -1]):
        assert loop_driver._span(r) is None, f"{r!r} names no place — must be unanchored"


def test_span_returns_the_ordered_int_tuple_for_a_real_range():
    """The anchored table — the value handed to the comparison, not just a bool."""
    assert loop_driver._span([0, 12]) == (0, 12), (
        "a span reaching line 12 is anchored even though it starts at 0 — "
        "ordering with min instead of max would read it as the sentinel"
    )
    assert loop_driver._span([12, 0]) == (0, 12), "end-first is the same span"
    assert loop_driver._span((3, 9)) == (3, 9), "a tuple is a range too"
    assert loop_driver._span([1.5, 2.5]) == (1, 2), "floats coerce like _norm_range"


def test_ranges_overlap_compares_the_spans_the_coercer_returned():
    """`[20, 10]` is lines 10..20 however it was written — ordered once, in `_span`."""
    span = loop_driver._span
    assert loop_driver._ranges_overlap(span([20, 10]), span([12, 15])), (
        "a reversed span must still overlap a range inside it"
    )
    assert loop_driver._ranges_overlap(span([12, 15]), span([20, 10])), "symmetric"
    assert not loop_driver._ranges_overlap(span([20, 10]), span([30, 40])), (
        "ordering must not make disjoint spans overlap"
    )


def _raw(cid: str, file: str, rng) -> dict:
    """A finding that did NOT go through `review_merge` — range exactly as given.

    `normalize_copilot` runs `_coerce_range`, so a normalized finding can never
    carry a string span; `_detect_conflicts` is also called on hand-built and
    replayed findings, which can.
    """
    return {"comment_id": cid, "verdict": "structural", "file": file, "line_range": rng}


def test_a_string_endpoint_range_does_not_raise_in_the_scan():
    """Untrusted `["10", "20"]` goes through the coercer, never into `min()` raw."""
    classified = [_raw("c1", "a.py", ["10", "20"]), _raw("c2", "a.py", [15, 25])]

    deferred, _kept = loop_driver._detect_conflicts(classified)

    assert sorted(deferred) == ["0:c1", "1:c2"], (
        f"a string-endpoint span is still lines 10..20; got {deferred!r}"
    )


def test_an_unanchored_shape_never_reaches_the_comparison():
    """A `["a", "b"]` range is place-less, not a hunk shared with its neighbour."""
    classified = [_raw("c1", "a.py", ["a", "b"]), _raw("c2", "a.py", ["a", "b"])]

    deferred, kept = loop_driver._detect_conflicts(classified)

    assert deferred == [], f"non-numeric ranges must not defer each other; got {deferred!r}"
    assert kept == classified


def test_a_reversed_range_still_defers_its_conflicting_twin():
    """Through the scan, not just the predicate: the deferral actually fires."""
    classified = [_anchored("c1", "a.py", [20, 10]), _anchored("c2", "a.py", [12, 15])]

    deferred, _kept = loop_driver._detect_conflicts(classified)

    assert sorted(deferred) == ["0:c1", "1:c2"], (
        f"endpoint order must not hide a conflict; got {deferred!r}"
    )
