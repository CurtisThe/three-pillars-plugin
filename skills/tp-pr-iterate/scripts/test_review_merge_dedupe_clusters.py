"""How `dedupe` CLUSTERS findings — the walk over already-kept findings.

Split from `test_review_merge_dedupe.py` (the pairwise collapse predicate) and
`test_review_merge_dedupe_survivors.py` (which record wins a collision) to keep
all three inside the file-size cap. Scope here: the loop's behaviour once a
cluster exists — what an incoming finding is compared AGAINST, and how far a
collapse can reach.

The finding builders live in the collapse module so there is one definition each.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import review_merge  # noqa: E402
from test_review_merge_dedupe import _cop, _cr  # noqa: E402


# ---------- the fuzzy walk is bounded by the cluster's first-seen anchor ----------


def test_a_similar_summary_chain_does_not_collapse_transitively():
    """[10], [13], [16] with similar wording is two findings, not one.

    Proximity is not transitive, but the survivor RECORD can change on a
    collision — so comparing each incoming finding against the current survivor
    let the cluster's coordinates drift up the file three lines at a time and
    swallow findings that were never near the original. The comparison key is
    the first-seen member; the survivor record may still change.
    """
    a = _cr("cr-1", "g.py", [10, 10], "off by one in the loop bound")
    b = _cr("cr-2", "g.py", [13, 13], "off-by-one in the loop bound here")
    c = _cr("cr-3", "g.py", [16, 16], "off by one in the loop bound here too")
    assert review_merge._is_duplicate(a, b) and review_merge._is_duplicate(b, c), (
        "premise broken — consecutive pairs must be duplicates"
    )
    assert not review_merge._is_duplicate(a, c), (
        "premise broken — the ends of the chain must NOT be duplicates"
    )
    out = review_merge.dedupe([a, b, c])
    assert len(out) == 2, f"proximity is not transitive; got {out!r}"
    assert [f["finding_id"] for f in out] == ["cr-2", "cr-3"], (
        f"the survivor record may move; the comparison key may not; got {out!r}"
    )


def test_an_exact_twin_of_the_anchor_still_collapses_into_a_moved_cluster():
    """Bounding the walk is not a blanket exemption for later findings.

    The survivor here is `cr-2` (the longer summary), whose range is NOT `cr-3`'s
    — but `cr-3` is an exact twin of the anchor `cr-1`, so it joins the cluster
    and its provenance accumulates with the earlier drop.
    """
    a = _cr("cr-1", "g.py", [10, 10], "off by one in the loop bound")
    b = _cr("cr-2", "g.py", [11, 12], "off-by-one in the loop bound here")
    c = _cr("cr-3", "g.py", [10, 10], "an entirely unrelated way of putting it")
    out = review_merge.dedupe([a, b, c])
    assert len(out) == 1, f"an exact twin of the anchor must collapse; got {out!r}"
    assert sorted(out[0]["merged_from"]) == ["cr-1", "cr-2"], (
        f"provenance must accumulate across the cluster; got {out[0]!r}"
    )


def test_a_similar_pair_far_apart_in_one_file_stays_two():
    """`_PROXIMITY_SLACK` is a few lines, not a whole file.

    Same file, same wording, 200 lines apart: two defects. Nothing pinned the
    slack's MAGNITUDE, so widening it to a file-scoped merge passed the suite.
    """
    a = _cr("cr-1", "g.py", [10, 10], "off by one in the loop bound")
    b = _cr("cr-2", "g.py", [210, 210], "off-by-one in the loop bound here")
    assert review_merge._summary_similar(a["summary"], b["summary"]), (
        "premise broken — only the line distance may keep these apart"
    )
    out = review_merge.dedupe([a, b])
    assert len(out) == 2, f"200 lines apart is not proximate; got {out!r}"


def test_an_exact_twin_of_an_absorbed_member_joins_the_cluster():
    """Exact coordinates are one defect — including a twin of a NON-anchor member.

    Bounding the fuzzy walk to the first-seen anchor is about PROXIMITY, which
    is not transitive. Identical coordinates are not proximity: `C` names the
    exact lines `B` already named, and `B` is in the cluster, so all three are
    one defect however differently `C` words it. Comparing only against the
    anchor reported it as a second finding.
    """
    a = _cr("cr-1", "g.py", [10, 12], "off by one in the loop bound")
    b = _cr("cr-2", "g.py", [13, 15], "off-by-one in the loop bound here")
    c = _cr("cr-3", "g.py", [13, 15], "an entirely unrelated way of putting it")
    assert review_merge._is_duplicate(a, b), "premise broken — b must be absorbed"
    assert not review_merge._is_duplicate(a, c), (
        "premise broken — c must not match the ANCHOR, only the absorbed member"
    )
    out = review_merge.dedupe([a, b, c])
    assert len(out) == 1, f"an exact twin of a cluster member must collapse; got {out!r}"
    assert sorted(out[0]["merged_from"] + [out[0]["finding_id"]]) == ["cr-1", "cr-2", "cr-3"], (
        f"all three ids must be accounted for in the cluster; got {out[0]!r}"
    )


def test_a_fuzzy_joiner_cannot_add_a_second_thread_to_a_thread_less_anchor():
    """The distinct-thread guard is MEMBER-wide, not just pairwise.

    The pairwise guard inside `_is_duplicate` compares the incoming finding with
    the cluster's ANCHOR — and the anchor here is a `/code-review` finding with
    no thread at all, so it never fires: `c` is proximate to `a` and worded like
    it, and the fuzzy route admits it. What must keep `c` out is the guard that
    tests every MEMBER, because `b` — already absorbed — holds a different
    thread, and a cluster that swallowed `c` would drop one of the two
    `thread_id`s reply-and-resolve needs to close those threads.
    """
    a = _cr("cr-1", "g.py", [10, 12], "off by one in the loop bound")
    b = _cop(1, "g.py", [13, 15], "off-by-one in the loop bound here")
    c = _cop(2, "g.py", [13, 15], "off by one in the loop bound as well")
    assert review_merge._is_duplicate(a, c), (
        "premise broken — only the member-wide guard may keep c out of the cluster"
    )
    assert review_merge._distinct_threads(b, c), "premise broken — b and c must hold two threads"

    out = review_merge.dedupe([a, b, c])

    assert len(out) == 2, f"a cluster must not swallow a second thread; got {out!r}"
    assert {f["thread_id"] for f in out} == {"RT_1", "RT_2"}, (
        f"both thread_ids must survive; got {out!r}"
    )
