"""Conflict deferral keys on findings that have no `comment_id`.

Split from `test_loop_driver.py` (already over the file-size cap and
grandfathered) so this sits in a file that is inside it.

Seed: SKILL.md step 6b feeds the DEDUPED UNION of Copilot comments and
`/code-review` findings into step 7's `_apply_conflicts`. Every finding from
`review_merge.normalize_codereview` carries `comment_id: None`, so keying the
deferral on `comment_id` put a single `None` in the deferred set and the `kept`
filter — `c.get("comment_id") not in deferred` — then dropped EVERY code-review
finding in the round, including ones on other files that conflicted with
nothing. The whole local review silently vanished from the fix round.
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


def _cr(fid: str, file: str, rng, verdict: str = "structural") -> dict:
    return review_merge.normalize_codereview(
        {"finding_id": fid, "file": file, "line_range": rng,
         "summary": f"{fid} on {file}", "verdict": verdict}
    )


def _cop(cid: str, file: str, rng, verdict: str = "structural") -> dict:
    return review_merge.normalize_copilot(
        {"comment_id": cid, "thread_id": f"RT_{cid}", "path": file,
         "line_range": rng, "body": f"{cid} on {file}", "verdict": verdict}
    )


def test_overlapping_code_review_findings_do_not_defer_the_whole_round():
    """The seed: two overlapping code-review findings must defer only themselves.

    `cr3` is structural, on a DIFFERENT file, and overlaps nothing — it belongs
    in the fix round. Under the `comment_id` key it was dropped anyway, because
    it shared the `None` that the two conflicting findings had contributed.
    """
    classified = [
        _cop("c1", "src/other.py", [1, 2], "minor"),
        _cr("cr-1", "a.py", [10, 20]),
        _cr("cr-2", "a.py", [15, 18]),
        _cr("cr-3", "b.py", [3, 3]),
    ]
    assert {f["comment_id"] for f in classified[1:]} == {None}, (
        "premise broken — normalize_codereview must produce comment_id: None"
    )

    deferred, kept = loop_driver._detect_conflicts(classified)

    assert sorted(deferred) == ["1:cr-1", "2:cr-2"], (
        f"only the overlapping pair may be deferred; got {deferred!r}"
    )
    assert [f["finding_id"] for f in kept] == ["c1", "cr-3"], (
        f"non-conflicting findings must survive the round; got {kept!r}"
    )
    assert None not in deferred, "a null id must never reach the deferred set"


def test_conflicting_code_review_findings_are_not_all_conflicting():
    """`_apply_conflicts` stays non-terminal while a clean finding remains.

    The same bug at the level above: an empty `kept` is what flips the loop to
    the terminal `awaiting-human-review`, so over-filtering handed the PR to a
    human on a round that had real, unconflicted work in it.
    """
    classified = [
        _cr("cr-1", "a.py", [10, 20]),
        _cr("cr-2", "a.py", [15, 18]),
        _cr("cr-3", "b.py", [3, 3]),
    ]
    next_state, kept, terminal = loop_driver._apply_conflicts(_state(), classified, now=_NOW)

    assert not terminal, "one clean structural finding remains — not all-conflicting"
    assert [f["finding_id"] for f in kept] == ["cr-3"]
    note = next_state["transitions"][-1]["note"]
    assert sorted(note["deferred_conflicting_comments"]) == ["0:cr-1", "1:cr-2"]
    assert "tag" not in note


def test_overlapping_copilot_comments_defer_under_index_qualified_ids():
    """A Copilot key still carries its `comment_id` — qualified by position.

    The id stays IN the key because a human reads
    `deferred_conflicting_comments` out of the state note and has to know which
    comment was deferred; the index is what makes "never shared" total.
    """
    classified = [_cop("c1", "a.py", [10, 20]), _cop("c2", "a.py", [15, 25])]

    deferred, kept = loop_driver._detect_conflicts(classified)

    assert sorted(deferred) == ["0:c1", "1:c2"], (
        f"Copilot keys must be index-qualified comment_ids; got {deferred!r}"
    )
    assert kept == []


def test_a_duplicated_comment_id_does_not_take_the_innocent_copy_down():
    """The union can hold ONE comment twice — the copies are not one key.

    Step 6b merges `list_review_threads` rows with review comments, so the same
    `comment_id` can arrive twice: once anchored on the hunk, once as an
    anchorless thread row. The anchored copy conflicts and is deferred; on the
    bare `comment_id` key the anchorless copy shared its identity and the `kept`
    filter dropped it too — the same over-filtering the null-id bug caused, one
    identity down, on the id GitHub was supposed to make safe.
    """
    classified = [
        _cop("c1", "a.py", [10, 20]),
        _cop("c2", "a.py", [15, 18]),
        {"comment_id": "c1", "verdict": "structural", "file": "a.py", "line_range": [0, 0]},
    ]

    deferred, kept = loop_driver._detect_conflicts(classified)

    assert deferred == ["0:c1", "1:c2"], (
        f"only the two anchored copies may be deferred; got {deferred!r}"
    )
    assert kept == [classified[2]], (
        f"the anchorless copy conflicted with nothing and must survive; got {kept!r}"
    )


def test_blank_copilot_comment_ids_get_distinct_positional_keys():
    """`comment_id: ""` is no id at all — two of them are two findings.

    A Copilot-shaped row can reach step 7 with a blank id (a hand-built or
    replayed record). The key shape is asserted, not just distinctness: relaxing
    the guard to `comment_id is not None` keys these on `"0:"`/`"1:"` — the id
    arm's shape worn by findings that carry no id — instead of the `idx:`
    fallback that says so.
    """
    classified = [_cop("", "a.py", [10, 20]), _cop("", "a.py", [15, 18])]
    assert {f["comment_id"] for f in classified} == {""}, (
        "premise broken — the rows must carry a blank comment_id"
    )

    deferred, kept = loop_driver._detect_conflicts(classified)

    assert deferred == ["idx:0", "idx:1"], (
        f"a blank id must fall through to the positional key; got {deferred!r}"
    )
    assert kept == []


def test_a_mixed_overlap_defers_both_sides_under_distinct_keys():
    """A Copilot comment and a code-review finding on one hunk are two deferrals.

    Distinct keys matter twice over: the human reading
    `deferred_conflicting_comments` needs to see both, and a shared key would
    take unrelated findings down with them.
    """
    classified = [
        _cop("c9", "gate.py", [40, 44]),
        _cr("cr-9", "gate.py", [42, 50]),
        _cr("cr-10", "gate.py", [80, 81]),
    ]

    deferred, kept = loop_driver._detect_conflicts(classified)

    assert sorted(deferred) == ["0:c9", "1:cr-9"], (
        f"both sides of a mixed overlap must be deferred; got {deferred!r}"
    )
    assert [f["finding_id"] for f in kept] == ["cr-10"]


def test_findings_with_no_id_at_all_fall_back_to_a_positional_key():
    """A finding carrying neither id still gets an identity of its own.

    Untrusted `/code-review` output can omit `finding_id`; `normalize_codereview`
    then defaults it to `""`. Two such findings must not collapse into one key.
    """
    classified = [
        {"verdict": "structural", "file": "a.py", "line_range": [10, 20]},
        {"verdict": "structural", "file": "a.py", "line_range": [15, 18]},
        {"verdict": "structural", "file": "b.py", "line_range": [3, 3], "finding_id": ""},
    ]

    deferred, kept = loop_driver._detect_conflicts(classified)

    assert deferred == ["idx:0", "idx:1"], f"positional fallback expected; got {deferred!r}"
    assert kept == [classified[2]], f"the clean finding must survive; got {kept!r}"


def test_deferred_keys_are_reported_in_input_order():
    """The note payload is deterministic — a set's iteration order is not."""
    classified = [
        _cr("cr-b", "a.py", [10, 20]),
        _cr("cr-a", "a.py", [15, 18]),
    ]
    assert loop_driver._detect_conflicts(classified)[0] == ["0:cr-b", "1:cr-a"]


def test_a_finding_id_shared_across_angles_does_not_take_an_innocent_finding_down():
    """`finding_id` is per-angle, so it collides — the key must not.

    `/code-review` fans out over several angles and each numbers its own
    findings from 1, so two unrelated findings on two different files carrying
    `finding_id "1"` is the ordinary case, not a corner. Keying the deferral on
    the bare `finding_id` put "1" in the deferred set for the conflicting one and
    the `kept` filter then dropped the innocent namesake on `b.py` — the same
    over-filtering the `comment_id: None` bug caused, one identity down.
    """
    classified = [
        _cr("1", "a.py", [10, 20]),
        _cr("1", "b.py", [3, 4]),
        _cr("2", "a.py", [15, 18]),
    ]

    deferred, kept = loop_driver._detect_conflicts(classified)

    assert deferred == ["0:1", "2:2"], (
        f"the key must be qualified by position, not the bare id; got {deferred!r}"
    )
    assert [f["file"] for f in kept] == ["b.py"], (
        f"the innocent namesake must survive the round; got {kept!r}"
    )


def test_production_shape_findings_with_no_id_get_distinct_positional_keys():
    """Two OVERLAPPING id-less findings, built the way step 6b builds them.

    Production shape: `/code-review` output need not carry `finding_id`, and
    `normalize_codereview` then defaults it to `""` — not to None. The key shape
    is asserted, not just its distinctness, because `idx:` is what proves the
    empty-string arm ran: relaxing the guard to `is not None` keys these on
    `"0:"`/`"1:"` — an id-less finding wearing the id arm's shape.
    """
    classified = [
        review_merge.normalize_codereview(
            {"file": "a.py", "line_range": [10, 20], "summary": "a wide hunk"}
        ),
        review_merge.normalize_codereview(
            {"file": "a.py", "line_range": [15, 18], "summary": "an inner hunk"}
        ),
        review_merge.normalize_codereview(
            {"file": "b.py", "line_range": [3, 3], "summary": "elsewhere entirely"}
        ),
    ]
    assert {f["finding_id"] for f in classified} == {""}, (
        "premise broken — normalize_codereview must default finding_id to ''"
    )

    deferred, kept = loop_driver._detect_conflicts(classified)

    assert deferred == ["idx:0", "idx:1"], (
        f"id-less findings must take the positional key; got {deferred!r}"
    )
    assert [f["file"] for f in kept] == ["b.py"], (
        f"the non-overlapping finding must survive; got {kept!r}"
    )
