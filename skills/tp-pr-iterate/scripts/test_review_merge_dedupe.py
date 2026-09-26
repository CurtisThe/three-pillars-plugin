"""Tests for the dedupe family — exact-match short-circuit + fuzzy near-miss path.

Seed: review-merge-dedupe-exact-match. Two `/code-review` angles describing the
SAME defect in their own words agree byte-for-byte on `file` + `line_range` but
score below the summary-similarity threshold, so the twin used to survive and the
PR comment overstated the finding count (12 entries for 10 findings).

Exercised through `review_merge` (the re-export surface every caller uses), not
the sibling module directly, so these pin the public behaviour.

Scope: this module owns the COLLAPSE predicate — does a pair become one finding?
Which record survives a collision, and what verdict it carries, lives in
`test_review_merge_dedupe_survivors.py` (which imports the builders below).
"""

from __future__ import annotations

import ast
import sys
import types
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import review_merge  # noqa: E402
import review_merge_dedupe  # noqa: E402


def _cr(fid: str, file: str, rng, summary: str, verdict: str = "structural") -> dict:
    return review_merge.normalize_codereview(
        {
            "finding_id": fid,
            "file": file,
            "line_range": rng,
            "summary": summary,
            "verdict": verdict,
        }
    )


def _cop(cid: int, file: str, rng, body: str, verdict: str = "structural") -> dict:
    """A normalized Copilot finding; `thread_id` is derived so ids stay distinct."""
    return review_merge.normalize_copilot(
        {
            "comment_id": cid,
            "thread_id": f"RT_{cid}",
            "path": file,
            "line_range": rng,
            "body": body,
            "verdict": verdict,
        }
    )


# ---------- the seed: identical coordinates, dissimilar wording ----------


def test_dissimilar_summaries_are_not_similar_by_the_fuzzy_predicate():
    """Guard the premise: these two summaries do NOT clear the similarity bar.

    Without this the collapse test below could pass for the wrong reason (the
    fuzzy path catching them anyway) and the short-circuit would be dead code.
    """
    a = "the retry counter is never reset between rounds"
    b = "unbounded growth: nothing zeroes this accumulator on a fresh pass"
    assert not review_merge_dedupe._summary_similar(a, b), (
        "premise broken — these summaries are similar enough for the fuzzy path"
    )


def test_exact_file_and_range_collapses_despite_dissimilar_summaries():
    """The short-circuit: identical file AND identical line_range collapse."""
    angle_a = _cr(
        "cr-A", "loop_driver.py", [120, 124],
        "the retry counter is never reset between rounds",
    )
    angle_b = _cr(
        "cr-B", "loop_driver.py", [120, 124],
        "unbounded growth: nothing zeroes this accumulator on a fresh pass",
    )
    out = review_merge.dedupe([angle_a, angle_b])
    assert len(out) == 1, (
        f"identical file+line_range must collapse regardless of wording; got {out!r}"
    )


def test_exact_collision_records_merged_from_provenance():
    """Provenance bookkeeping on the exact path matches the fuzzy path."""
    specific = _cr(
        "cr-keep", "state_io.py", [42, 45],
        "the atomic rename is not fsynced, so a crash can leave a zero-length file",
    )
    other = _cr("cr-drop", "state_io.py", [42, 45], "durability hole here")
    out = review_merge.dedupe([specific, other])
    assert len(out) == 1
    assert out[0]["merged_from"] == ["cr-drop"], (
        f"dropped twin's finding_id must land in merged_from; got {out[0]!r}"
    )


# ---------- the fuzzy path is NOT bypassed ----------


def test_near_miss_range_with_dissimilar_summaries_stays_two_findings():
    """A near-miss (proximate, not identical) range still needs summary similarity."""
    a = _cr(
        "cr-1", "loop_driver.py", [120, 124],
        "the retry counter is never reset between rounds",
    )
    b = _cr(
        "cr-2", "loop_driver.py", [121, 125],
        "unbounded growth: nothing zeroes this accumulator on a fresh pass",
    )
    out = review_merge.dedupe([a, b])
    assert len(out) == 2, (
        f"near-miss ranges must go through the fuzzy path, not the short-circuit; got {out!r}"
    )


def test_near_miss_range_with_similar_summaries_still_collapses():
    """The pre-existing fuzzy behaviour is untouched by the short-circuit."""
    a = _cr("cr-1", "g.py", [10, 10], "off by one in the loop bound")
    b = _cr("cr-2", "g.py", [11, 12], "off-by-one in the loop bound here")
    out = review_merge.dedupe([a, b])
    assert len(out) == 1, f"proximate + similar must still collapse; got {out!r}"


def test_same_range_in_a_different_file_never_collapses():
    """The short-circuit is file-scoped — identical ranges elsewhere are distinct."""
    a = _cr("cr-1", "a.py", [5, 9], "missing guard")
    b = _cr("cr-2", "b.py", [5, 9], "a completely unrelated schema problem")
    out = review_merge.dedupe([a, b])
    assert len(out) == 2
    assert [f["file"] for f in out] == ["a.py", "b.py"]


def test_reversed_range_is_the_same_span():
    """`[12, 10]` and `[10, 12]` name one span — normalize before comparing."""
    a = _cr("cr-1", "x.py", [10, 12], "first phrasing of the defect")
    b = _cr("cr-2", "x.py", [12, 10], "an entirely different way of saying it")
    out = review_merge.dedupe([a, b])
    assert len(out) == 1, f"reversed range is the same span; got {out!r}"


# ---------- the anchorless (0, 0) range is NOT a coordinate ----------
#
# A missing / null / non-numeric line_range with no `line` normalizes to (0, 0).
# That is the ABSENCE of a line anchor, not a location: GitHub file-level and
# outdated review comments, and every `thread_resolver.list_review_threads` row
# (path, no line field at all), look like this. The exact-match short-circuit
# must not treat it as identical coordinates.


def test_two_anchorless_copilot_findings_stay_two_with_both_thread_ids():
    """Two file-level Copilot comments on one path are two findings, not one.

    They share `file` and normalize to the same (0, 0) range, so an exact-match
    rule that accepted the degenerate range would collapse them unconditionally
    — silently dropping one finding AND its `thread_id`, which the
    reply-and-resolve step needs to ever close that thread.
    """
    a = _cop(11, "config_loader.py", None, "the default timeout is undocumented")
    b = _cop(12, "config_loader.py", None, "no schema validation before the first read")
    out = review_merge.dedupe([a, b])
    assert len(out) == 2, (
        f"anchorless same-file findings are distinct, not exact twins; got {out!r}"
    )
    assert {f["thread_id"] for f in out} == {"RT_11", "RT_12"}, (
        f"both thread_ids must survive; got {out!r}"
    )


def test_two_anchorless_copilot_findings_stay_two_with_one_null_thread_id():
    """The same pair with only ONE thread_id — the anchorless rule does the work.

    The sibling test above is exclusion-ambiguous: two DISTINCT thread_ids are
    independently excluded from the short-circuit, so it would pass even if the
    degenerate `(0, 0)` range were treated as a coordinate. Nulling one id
    removes that second exclusion and leaves the anchorless rule operative.
    """
    a = dict(_cop(11, "config_loader.py", None, "the default timeout is undocumented"),
             thread_id=None)
    b = _cop(12, "config_loader.py", None, "no schema validation before the first read")
    assert not review_merge._distinct_threads(a, b), (
        "premise broken — a null thread_id must not be a second thread"
    )
    out = review_merge.dedupe([a, b])
    assert len(out) == 2, (
        f"the anchorless (0, 0) range is not a coordinate; got {out!r}"
    )


def test_two_anchorless_code_review_findings_stay_two():
    """Same rule for `/code-review` findings with no usable range."""
    a = _cr("cr-1", "config_loader.py", None, "the default timeout is undocumented")
    b = _cr("cr-2", "config_loader.py", [], "no schema validation before the first read")
    out = review_merge.dedupe([a, b])
    assert len(out) == 2, (
        f"anchorless same-file findings must not collapse on (0, 0); got {out!r}"
    )
    assert [f["finding_id"] for f in out] == ["cr-1", "cr-2"]


def test_an_anchorless_finding_is_not_proximate_to_the_top_of_the_file():
    """The sentinel is not line 0 — it must not be near lines 1..3 either.

    `_NO_RANGE` is `(0, 0)`, so the padded-overlap arithmetic read a file-level
    comment as sitting three lines above line 1: pair it with a real finding
    near the top of the same file and similar wording alone collapsed them,
    losing a finding at a location the file-level comment never named.
    """
    anchorless = _cr("cr-1", "config_loader.py", None,
                     "no schema validation before the first read")
    anchored = _cr("cr-2", "config_loader.py", [2, 2],
                   "there is no schema validation before the read")
    assert review_merge._summary_similar(anchorless["summary"], anchored["summary"]), (
        "premise broken — only the missing anchor may keep these apart"
    )
    assert not review_merge._line_proximity((0, 0), (2, 2)), (
        "the sentinel must not be proximate to a real range"
    )
    for order in ([anchorless, anchored], [anchored, anchorless]):
        out = review_merge.dedupe(order)
        assert len(out) == 2, f"an unanchored finding is nowhere, not at line 0; got {out!r}"


def test_anchorless_pair_still_collapses_when_the_summaries_match():
    """The exclusion is a fall-through, not a blanket exemption.

    Anchorless pairs go through the UNCHANGED fuzzy path: (0, 0) is proximate to
    (0, 0), so a similar-summary pair still collapses.
    """
    a = _cr("cr-1", "config_loader.py", None, "no schema validation before the first read")
    b = _cr("cr-2", "config_loader.py", None, "there is no schema validation before the read")
    out = review_merge.dedupe([a, b])
    assert len(out) == 1, f"anchorless + similar must still collapse via fuzzy; got {out!r}"


def test_anchorless_range_never_reaches_the_exact_short_circuit():
    """Unit-level pin on the predicate itself, independent of dedupe's plumbing."""
    a = _cr("cr-1", "p.py", None, "one thing")
    b = _cr("cr-2", "p.py", None, "another thing entirely")
    assert review_merge._norm_range(a["line_range"]) == (0, 0)
    assert not review_merge._is_exact_duplicate(a, b), (
        "the degenerate (0, 0) range must be excluded from the exact short-circuit"
    )


def test_null_file_pairs_never_collapse_on_the_exact_path():
    """`file: None` is not a file — two unanchored findings are not the same place."""
    a = dict(_cr("cr-1", "x.py", [7, 9], "one thing"), file=None)
    b = dict(_cr("cr-2", "x.py", [7, 9], "another thing entirely"), file=None)
    assert not review_merge._is_exact_duplicate(a, b)
    assert len(review_merge.dedupe([a, b])) == 2


def test_only_a_list_or_tuple_is_a_line_range():
    """`_norm_range` must agree with `_coerce_range` about what a range IS.

    Iterating a str/set/dict fabricated coordinates out of untrusted output —
    `"12"` read as the span (1, 2) — and `bool` is an `int` subclass, so
    `[True, False]` coerced to (0, 1). Both degrade to `_NO_RANGE` instead, as
    do non-numeric elements (`["a", "b"]` → ValueError, `[None, None]` →
    TypeError, `[inf, 2]` → OverflowError), which both sides swallow rather
    than raise on. `json.loads` accepts the non-standard `Infinity` literal, so
    the OverflowError arm is reachable from a raw angle reply.
    """
    for bogus in ("12", {1, 2}, {"start": 1, "end": 2}, [True, False], 7, None, [],
                  ["a", "b"], [None, None], [float("inf"), 2], [1, float("-inf")]):
        assert review_merge._norm_range(bogus) == (0, 0), f"{bogus!r} is not a range"
    assert review_merge._norm_range([10, 12]) == (10, 12)
    assert review_merge._norm_range((12, 10)) == (10, 12)
    # Arity too: `_coerce_range` requires len >= 2 and reads only [0] and [1].
    assert review_merge._norm_range([7]) == (0, 0), "a 1-element list is not a range"
    assert review_merge._norm_range([3, 9, 1]) == (3, 9), "only [0] and [1] are read"
    for r in ([7], [3, 9, 1], [10, 12], (12, 10), [True, False], [], ["a", "b"], [None, None]):
        start, end = review_merge._coerce_range(r, None)
        assert review_merge._norm_range(r) == (min(start, end), max(start, end)), (
            f"_norm_range and _coerce_range disagree about {r!r}"
        )


def test_a_string_range_never_reaches_the_exact_short_circuit():
    """End-to-end: two stray string ranges must not collapse as identical spans."""
    a = dict(_cr("cr-1", "x.py", [7, 9], "one thing"), line_range="12")
    b = dict(_cr("cr-2", "x.py", [7, 9], "another thing entirely"), line_range="21")
    assert not review_merge._is_exact_duplicate(a, b)
    assert len(review_merge.dedupe([a, b])) == 2


def test_fuzzy_branch_tolerates_a_null_or_empty_raw_range():
    """The fuzzy branch normalizes too — a RAW None/[] range must not raise.

    `_is_duplicate` is called on findings straight from `merge_*` call sites as
    well as normalized ones; handing `None` to `_line_proximity` raised
    TypeError and `[]` raised ValueError on `min()`.
    """
    a = {"file": "q.py", "line_range": None, "summary": "off by one in the loop bound"}
    b = {"file": "q.py", "line_range": [], "summary": "off-by-one in the loop bound here"}
    assert review_merge._is_duplicate(a, b) is True


# ---------- two GitHub threads are two comments, whatever they say ----------
#
# The short-circuit's rationale — "two angles word one defect differently but
# agree on the coordinates" — describes the LOCAL `/code-review` fan-out, which
# has no threads. Two distinct Copilot review threads on one real line are two
# comments by construction, and collapsing them drops a `thread_id`.


def test_two_distinct_copilot_threads_on_one_line_stay_two():
    """Distinct non-null thread_ids never take the exact-match short-circuit."""
    a = _cop(1, "x.py", [42, 42], "the retry counter is never reset between rounds")
    b = _cop(2, "x.py", [42, 42], "unbounded growth: nothing zeroes this on a fresh pass")
    assert not review_merge._is_exact_duplicate(a, b), (
        "two distinct review threads must be excluded from the short-circuit"
    )
    out = review_merge.dedupe([a, b])
    assert len(out) == 2, f"two review threads are two findings; got {out!r}"
    assert {f["thread_id"] for f in out} == {"RT_1", "RT_2"}, (
        f"both thread_ids must survive; got {out!r}"
    )


def test_copilot_and_code_review_on_one_line_still_collapse():
    """The exclusion is thread-vs-thread only — the mixed-source case is the point."""
    cop = _cop(77, "converge.py", [30, 31], "off-by-one")
    cr = _cr(
        "cr-77", "converge.py", [30, 31],
        "the loop bound excludes the final round, so the last review never runs",
    )
    for order in ([cop, cr], [cr, cop]):
        out = review_merge.dedupe(order)
        assert len(out) == 1, f"Copilot vs code-review at one line must collapse; got {out!r}"
        assert out[0]["source"] == "copilot" and out[0]["thread_id"] == "RT_77", (
            f"Copilot must survive (it owns the thread_id); got {out[0]!r}"
        )
        assert out[0]["merged_from"] == ["cr-77"]


def test_two_distinct_copilot_threads_at_proximate_lines_stay_two():
    """The exclusion holds on the FUZZY branch too, not only the short-circuit.

    Near-miss lines with similar wording are exactly how two Copilot threads on
    one hunk look, and collapsing them drops a `thread_id` reply-and-resolve
    needs — the same loss the exact-path exclusion exists to prevent.
    """
    a = _cop(3, "x.py", [42, 42], "the retry counter is never reset between rounds")
    b = _cop(4, "x.py", [43, 43], "the retry counter is never reset between the rounds")
    assert review_merge._summary_similar(a["summary"], b["summary"]), (
        "premise broken — this pair must clear the similarity bar"
    )
    assert not review_merge._is_duplicate(a, b), (
        "the fuzzy branch must exclude two distinct threads, not just the exact one"
    )
    out = review_merge.dedupe([a, b])
    assert len(out) == 2, f"two review threads are two findings; got {out!r}"
    assert {f["thread_id"] for f in out} == {"RT_3", "RT_4"}, (
        f"both thread_ids must survive the fuzzy path; got {out!r}"
    )


def test_a_cluster_never_absorbs_a_second_copilot_thread():
    """A collapsed cluster still refuses a second thread_id.

    `dedupe` compares an incoming finding against the cluster's first-seen
    anchor, and that anchor may be thread-less: here a `/code-review` finding is
    seen first and a Copilot record takes over the slot. The distinct-thread
    exclusion is therefore checked against every collapsed member, not just the
    anchor.
    """
    cr = _cr("cr-1", "x.py", [42, 42], "the gate is bypassable when the flag is unset")
    cop1 = _cop(1, "x.py", [42, 42], "gate bypass")
    cop2 = _cop(2, "x.py", [42, 42], "unbounded growth: nothing zeroes this on a fresh pass")
    out = review_merge.dedupe([cr, cop1, cop2])
    assert len(out) == 2, f"a cluster must not swallow a second thread; got {out!r}"
    assert {f["thread_id"] for f in out} == {"RT_1", "RT_2"}, (
        f"both thread_ids must survive; got {out!r}"
    )


def test_two_code_review_findings_on_one_line_still_collapse():
    """Neither side has a thread_id, so the seed case is untouched."""
    a = _cr("cr-1", "x.py", [42, 42], "the retry counter is never reset between rounds")
    b = _cr("cr-2", "x.py", [42, 42], "unbounded growth: nothing zeroes this on a fresh pass")
    assert len(review_merge.dedupe([a, b])) == 1


def test_one_sided_thread_id_does_not_block_the_short_circuit():
    """A None thread_id on either side is not a second thread — still collapses."""
    cop = _cop(9, "x.py", [42, 42], "first phrasing")
    cr = _cr("cr-9", "x.py", [42, 42], "an entirely unrelated way of putting it")
    assert review_merge._is_exact_duplicate(cop, cr)
    assert review_merge._is_exact_duplicate(cr, cop)


# ---------- fail-closed sentinels must not be swallowed ----------


def test_two_unparseable_angles_survive_the_exact_short_circuit():
    """Regression guard: N failed angles must still surface as N sentinels.

    Sentinels share `line_range == [0, 0]` and differ only by `file`
    (`<review-output:angle-N>`), so an exact-match rule that ignored `file`
    would collapse them and hide how many angles failed.
    """
    merged = review_merge.merge_codereview_angles(["junk one", "junk two"])
    assert len(merged) == 2, f"two failed angles must surface as two; got {merged!r}"


# ---------- re-export surface ----------


def _dedupe_surface() -> set[str]:
    """Every name `review_merge_dedupe` DEFINES — derived, not hand-listed.

    A hand list silently goes stale: the round-1 version predated `_NO_RANGE`,
    `_VERDICT_RANK`, `_same_file` and `_verdict_rank` and never noticed. Imports
    (`difflib`, `__future__.annotations`) are filtered by `__module__`; module
    constants have no `__module__`, so the default keeps them.
    """
    return {
        name
        for name, val in vars(review_merge_dedupe).items()
        if not name.startswith("__")
        and not isinstance(val, types.ModuleType)
        and getattr(val, "__module__", "review_merge_dedupe") == "review_merge_dedupe"
    }


def _import_block_names() -> set[str]:
    """The names `review_merge.py` actually imports from the dedupe module."""
    tree = ast.parse(Path(review_merge.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "review_merge_dedupe":
            return {alias.name for alias in node.names}
    raise AssertionError("review_merge.py no longer imports from review_merge_dedupe")


def test_review_merge_re_exports_the_whole_dedupe_family():
    """The split is invisible to callers: EVERY defined name is re-exported."""
    surface = _dedupe_surface()
    # Guard the derivation itself — an empty surface would make the loop vacuous.
    assert {"dedupe", "_is_duplicate", "_is_exact_duplicate", "_NO_RANGE", "_VERDICT_RANK",
            "_same_file", "_verdict_rank"} <= surface, f"surface derivation broke: {surface!r}"
    for name in sorted(surface):
        assert hasattr(review_merge, name), f"review_merge lost the re-export of {name!r}"
        assert getattr(review_merge, name) is getattr(review_merge_dedupe, name)


def test_the_import_block_names_the_whole_dedupe_surface():
    """`from review_merge_dedupe import (...)` is exhaustive, not a subset."""
    assert _import_block_names() == _dedupe_surface()


def test_an_infinity_line_range_in_an_angle_reply_degrades_instead_of_raising():
    """`json.loads` accepts `Infinity`; `int(inf)` raises OverflowError, which
    used to escape `normalize_codereview` and crash `merge_codereview_angles`."""
    text = '```json\n[{"file": "a.py", "line_range": [Infinity, 2], "summary": "x", "verdict": "minor"}]\n```'
    findings = review_merge.merge_codereview_angles([text])
    assert [f["line_range"] for f in findings] == [[0, 0]]
    assert review_merge._coerce_range([float("inf"), 2], None) == (0, 0)
