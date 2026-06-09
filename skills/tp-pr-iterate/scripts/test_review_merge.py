"""Tests for review_merge — normalize + dedupe dual-source review findings (Enh.1)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import review_merge  # noqa: E402

_SCHEMA = json.loads(
    (HERE.parent / "schemas" / "normalized-finding.v1.json").read_text()
)


def _valid(finding: dict) -> None:
    Draft202012Validator(_SCHEMA).validate(finding)


def test_normalize_copilot_shape():
    out = review_merge.normalize_copilot(
        {
            "comment_id": 555,
            "thread_id": "RT_node1",
            "reviewer": "Copilot",
            "path": "x.py",
            "line_range": [10, 12],
            "body": "this cross-reference is stale",
            "verdict": "structural",
        }
    )
    _valid(out)
    assert out["source"] == "copilot"
    assert out["thread_id"] == "RT_node1"
    assert out["comment_id"] == 555


def test_normalize_codereview_shape():
    out = review_merge.normalize_codereview(
        {
            "file": "x.py",
            "line_range": [11, 13],
            "summary": "stale cross-reference to renamed symbol",
            "verdict": "structural",
            "confidence": "High",
        }
    )
    _valid(out)
    assert out["source"] == "code-review"
    assert out["thread_id"] is None
    assert out["comment_id"] is None


def test_dedupe_collapses_same_defect_keeps_copilot():
    cop = review_merge.normalize_copilot(
        {
            "comment_id": 1,
            "thread_id": "RT_1",
            "path": "x.py",
            "line_range": [10, 12],
            "body": "stale cross reference to the renamed helper",
            "verdict": "structural",
        }
    )
    cr = review_merge.normalize_codereview(
        {
            "finding_id": "cr-1",
            "file": "x.py",
            "line_range": [11, 13],
            "summary": "stale cross reference to the renamed helper here",
            "verdict": "structural",
        }
    )
    out = review_merge.dedupe([cr, cop])  # code-review first to prove copilot wins
    assert len(out) == 1
    assert out[0]["source"] == "copilot"
    assert out[0]["thread_id"] == "RT_1"
    assert "cr-1" in (out[0]["merged_from"] or [])


def test_dedupe_keeps_distinct():
    a = review_merge.normalize_copilot(
        {"comment_id": 1, "thread_id": "RT_1", "path": "a.py",
         "line_range": [10, 12], "body": "issue one about parsing", "verdict": "structural"}
    )
    b = review_merge.normalize_codereview(
        {"finding_id": "cr-2", "file": "b.py", "line_range": [80, 82],
         "summary": "a totally different problem with the schema", "verdict": "structural"}
    )
    out = review_merge.dedupe([a, b])
    assert len(out) == 2
    assert [f["file"] for f in out] == ["a.py", "b.py"]


def test_dedupe_records_merged_from():
    cop = review_merge.normalize_copilot(
        {"comment_id": 9, "thread_id": "RT_9", "path": "z.py", "line_range": [5, 5],
         "body": "missing guard on the empty list case", "verdict": "structural"}
    )
    cr = review_merge.normalize_codereview(
        {"finding_id": "cr-9", "file": "z.py", "line_range": [5, 6],
         "summary": "missing guard on the empty list case path", "verdict": "structural"}
    )
    out = review_merge.dedupe([cop, cr])
    assert len(out) == 1
    assert out[0]["merged_from"] == ["cr-9"]


def test_parse_codereview_response_extracts_findings():
    text = (
        "Here is my review.\n\n```json\n"
        '[{"file": "x.py", "line_range": [3, 4], "summary": "bug", "verdict": "structural"}]\n'
        "```\n"
    )
    findings = review_merge.parse_codereview_response(text)
    assert len(findings) == 1
    assert findings[0]["file"] == "x.py"


def test_parse_codereview_response_malformed_returns_empty():
    assert review_merge.parse_codereview_response("no json here") == []
    assert review_merge.parse_codereview_response("```json\n{not valid\n```") == []
    assert review_merge.parse_codereview_response("") == []


def test_normalize_codereview_coerces_confidence_casing():
    out = review_merge.normalize_codereview(
        {"file": "x.py", "line_range": [1, 2], "summary": "s",
         "verdict": "structural", "confidence": "high"}
    )
    _valid(out)
    assert out["confidence"] == "High"


def test_normalize_codereview_drops_unknown_confidence():
    out = review_merge.normalize_codereview(
        {"file": "x.py", "line_range": [1, 2], "summary": "s",
         "verdict": "structural", "confidence": "definitely"}
    )
    _valid(out)
    assert "confidence" not in out


def test_dedupe_3way_collision_preserves_all_provenance():
    """Regression (dual-source /code-review finding): in a 3+-way collision where
    code-review twins collapse first and a Copilot finding then wins via swap,
    ALL dropped ids must survive in merged_from (not just the last)."""
    cr_a = review_merge.normalize_codereview(
        {"finding_id": "cr-A", "file": "z.py", "line_range": [5, 6],
         "summary": "missing guard on the empty list case", "verdict": "structural"}
    )
    cr_b = review_merge.normalize_codereview(
        {"finding_id": "cr-B", "file": "z.py", "line_range": [5, 7],
         "summary": "missing guard on the empty list case here", "verdict": "structural"}
    )
    cop = review_merge.normalize_copilot(
        {"comment_id": 1, "thread_id": "RT_1", "path": "z.py", "line_range": [5, 6],
         "body": "missing guard on the empty list case path", "verdict": "structural"}
    )
    out = review_merge.dedupe([cr_a, cr_b, cop])  # cr's collapse first, then cop wins
    assert len(out) == 1
    assert out[0]["source"] == "copilot"
    mf = out[0]["merged_from"] or []
    assert "cr-A" in mf and "cr-B" in mf, mf


# ---------- mandatory /code-review summary comment ----------


def test_format_codereview_comment_groups_by_severity():
    findings = [
        {"file": "a.py", "line_range": [10, 12], "summary": "off-by-one", "verdict": "structural"},
        {"file": "b.py", "line_range": [4, 4], "summary": "rename for clarity", "verdict": "minor"},
    ]
    body = review_merge.format_codereview_comment(findings, head_sha="abc1234def567")
    assert "/code-review" in body
    assert "1 structural" in body and "1 minor" in body
    assert "### Structural" in body and "### Minor" in body
    assert "`a.py:10-12`" in body and "off-by-one" in body
    assert "`b.py:4`" in body          # single-line collapses to file:line
    assert "abc1234def" in body        # head sha (truncated) for traceability


def test_format_codereview_comment_clean_is_explicit_not_silent():
    body = review_merge.format_codereview_comment([])
    assert "No findings" in body, "a clean review must still render a visible body"
    assert "/code-review" in body


def test_post_codereview_comment_posts_body_and_returns_true():
    sent = {}

    def fake_post(pr_url, body):
        sent["pr_url"] = pr_url
        sent["body"] = body
        return True

    findings = [{"file": "a.py", "line_range": [1, 1], "summary": "bug", "verdict": "structural"}]
    ok = review_merge.post_codereview_comment(
        "https://github.com/o/r/pull/60", findings, head_sha="deadbeef", post_fn=fake_post
    )
    assert ok is True
    assert sent["pr_url"] == "https://github.com/o/r/pull/60"
    assert "1 structural" in sent["body"] and "bug" in sent["body"]


def test_post_codereview_comment_fires_even_on_clean_review():
    """Mandatory: a clean ([]) review STILL posts — no silent reviews."""
    calls = []
    review_merge.post_codereview_comment(
        "https://github.com/o/r/pull/60", [], post_fn=lambda u, b: calls.append(b) or True
    )
    assert len(calls) == 1, "post must fire on an empty/clean review too"
    assert "No findings" in calls[0]


def test_post_codereview_comment_is_fail_open():
    """A failed post must not raise — returns False, never crashes the loop."""
    def boom(pr_url, body):
        raise RuntimeError("gh down")

    assert review_merge.post_codereview_comment(
        "https://github.com/o/r/pull/60", [], post_fn=boom
    ) is False
    # A post_fn that returns False (non-zero gh) is also reported as False, not raised.
    assert review_merge.post_codereview_comment(
        "https://github.com/o/r/pull/60", [], post_fn=lambda u, b: False
    ) is False


def test_default_comment_post_uses_rest_not_gh_pr_comment(monkeypatch):
    """The default poster shells the REST issues/comments endpoint (never gh pr edit /
    gh pr comment), mirroring the label/reviewer REST path that dodges classic-Projects."""
    captured = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        import subprocess as _sp
        return _sp.CompletedProcess(args=argv, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(review_merge.subprocess, "run", fake_run)
    review_merge._default_comment_post("https://github.com/CurtisThe/three-pillars/pull/60", "hi")
    argv = captured["argv"]
    assert argv[:2] == ["gh", "api"]
    assert "repos/CurtisThe/three-pillars/issues/60/comments" in argv
    assert argv[:3] != ["gh", "pr", "comment"] and "edit" not in argv


# ---------- fail-closed parse + multi-angle merge (review-thoroughness) ----------


def test_parse_codereview_result_distinguishes_clean_from_unparseable():
    # genuine clean review: valid empty array → parsed_ok True
    findings, ok = review_merge.parse_codereview_result("```json\n[]\n```")
    assert findings == [] and ok is True
    # valid findings
    findings, ok = review_merge.parse_codereview_result(
        '```json\n[{"file":"a.py","verdict":"minor","summary":"x","line_range":[1,1]}]\n```'
    )
    assert ok is True and len(findings) == 1
    # UNPARSEABLE: no block / invalid JSON / non-list → parsed_ok False (NOT clean)
    for bad in ("no json here", "```json\n{not valid\n```", "", "```json\n{}\n```"):
        f, ok = review_merge.parse_codereview_result(bad)
        assert f == [] and ok is False, f"{bad!r} must be unparseable (ok=False), got ok={ok}"
    # A PARSEABLE array of only non-dict items → ([], False): it WAS a valid JSON list
    # but has no findings and is 'ambiguous' — NOT a genuine clean signal (pr-iterate-loop-
    # hardening, Hole 2 fix). Must block convergence, not silently read clean.
    f, ok = review_merge.parse_codereview_result("```json\n[1, 2, \"x\"]\n```")
    assert f == [] and ok is False


def test_parse_prefers_last_json_block_not_an_early_draft():
    """Review #61 finding: an early '[]' fence (deliberation) must NOT shadow the real
    findings in a LATER ```json block — last block wins, else findings silently drop."""
    text = (
        "First I thought it was clean:\n```json\n[]\n```\n"
        "But on closer look:\n```json\n"
        '[{"file":"x.py","line_range":[3,3],"summary":"real bug","verdict":"structural"}]\n```'
    )
    findings, ok = review_merge.parse_codereview_result(text)
    assert ok is True and len(findings) == 1 and findings[0]["summary"] == "real bug"


def test_parse_non_str_input_is_unparseable_not_crash():
    """A non-str reply (None / an object) must fail CLOSED (unparseable), never raise."""
    for bad in (None, 123, {"x": 1}, ["a"]):
        f, ok = review_merge.parse_codereview_result(bad)
        assert f == [] and ok is False


def test_normalize_tolerates_non_str_summary_and_bad_range():
    """Untrusted angle output: non-str summary / non-numeric line_range must not crash."""
    out = review_merge.normalize_codereview(
        {"file": "a.py", "summary": 123, "line_range": ["a", "b"], "verdict": "minor"}
    )
    assert isinstance(out["summary"], str) and out["line_range"] == [0, 0]


def test_parse_codereview_response_backcompat_still_collapses_to_list():
    # The back-compat wrapper still returns just the list (fail-soft) for old callers.
    assert review_merge.parse_codereview_response("no json here") == []
    assert review_merge.parse_codereview_response("```json\n[]\n```") == []


def test_findings_or_block_injects_structural_sentinel_on_unparseable():
    # clean → []
    assert review_merge.parse_codereview_findings_or_block("```json\n[]\n```") == []
    # unparseable → ONE structural sentinel (blocks convergence, never silent [])
    out = review_merge.parse_codereview_findings_or_block("garbage, no json")
    assert len(out) == 1
    assert out[0]["verdict"] == "structural"
    assert "could not be parsed" in out[0]["summary"].lower()


def test_merge_codereview_angles_dedupes_and_fails_closed():
    # two angles find the SAME defect (same file + proximate line + similar summary) → 1 after dedupe
    a1 = '```json\n[{"file":"g.py","line_range":[10,10],"summary":"off by one in loop","verdict":"structural"}]\n```'
    a2 = '```json\n[{"file":"g.py","line_range":[10,11],"summary":"off-by-one in the loop","verdict":"structural"}]\n```'
    merged = review_merge.merge_codereview_angles([a1, a2])
    assert len(merged) == 1, f"duplicate finding across angles must collapse; got {len(merged)}"

    # a clean angle + an UNPARSEABLE angle → EXACTLY one structural sentinel (the clean
    # [] must add nothing; the unparseable one blocks convergence)
    merged2 = review_merge.merge_codereview_angles(["```json\n[]\n```", "totally broken"])
    assert len(merged2) == 1, f"clean + unparseable must yield exactly 1 finding; got {len(merged2)}"
    assert merged2[0]["verdict"] == "structural"
    assert "could not be parsed" in merged2[0]["summary"].lower()

    # TWO unparseable angles → TWO DISTINCT sentinels (operator must see how many failed,
    # not have them collapse to one via dedupe)
    two_bad = review_merge.merge_codereview_angles(["junk one", "junk two"])
    assert len(two_bad) == 2, f"two failed angles must surface as two sentinels; got {len(two_bad)}"
    assert all(f["verdict"] == "structural" for f in two_bad)

    # all-clean angles → genuinely empty (the round may converge)
    assert review_merge.merge_codereview_angles(["```json\n[]\n```", "```json\n[]\n```"]) == []

    # None / empty input → ONE no-angles sentinel (fail-closed; blocks convergence).
    # (pr-iterate-loop-hardening Hole 3 fix: was [] before, now returns sentinel.)
    for empty_input in (None, []):
        result = review_merge.merge_codereview_angles(empty_input)
        assert len(result) == 1 and result[0]["verdict"] == "structural", (
            f"None/[] fan-out must yield one structural sentinel; got {result} for {empty_input!r}"
        )

    # a non-str angle reply fails closed to a sentinel, never crashes the merge
    assert len(review_merge.merge_codereview_angles([None])) == 1

    # garbage list items are filtered, the real finding survives normalization
    one_real = review_merge.merge_codereview_angles(
        ['```json\n[1, "x", {"file":"r.py","line_range":[2,2],"summary":"real","verdict":"minor"}]\n```']
    )
    assert len(one_real) == 1 and one_real[0]["summary"] == "real"

    # all-clean angles → genuinely empty (may converge)
    assert review_merge.merge_codereview_angles(["```json\n[]\n```", "```json\n[]\n```"]) == []


def test_parse_unions_all_nonempty_arrays_both_directions():
    """Audit blocker (#61): selection must UNION every findings-bearing array, not take
    only the last. Re-specs the prior 'last-wins' contract — interpreting two non-empty
    arrays as draft→refined silently dropped the earlier array, so a '## Structural'
    block followed by a '## Minor' block lost the structural finding and false-converged
    the two-stable gate. Surfacing every finding is the fail-closed direction; an empty
    `[]` still contributes nothing in either position."""
    real = '[{"file":"x.py","line_range":[3,3],"summary":"real bug","verdict":"structural"}]'
    empty = "[]"
    # early [] then real → real survives
    t1 = f"draft:\n```json\n{empty}\n```\nfinal:\n```json\n{real}\n```"
    f1, ok1 = review_merge.parse_codereview_result(t1)
    assert ok1 and len(f1) == 1 and f1[0]["summary"] == "real bug"
    # real then trailing [] ("on reflection, clean") → real STILL survives (fail-closed)
    t2 = f"found:\n```json\n{real}\n```\non reflection clean:\n```json\n{empty}\n```"
    f2, ok2 = review_merge.parse_codereview_result(t2)
    assert ok2 and len(f2) == 1 and f2[0]["summary"] == "real bug", (
        "a trailing [] must NOT suppress earlier real findings (false-convergence guard)"
    )
    # two NON-empty arrays (e.g. a structural block then a minor block) → UNION BOTH.
    # The old last-wins behavior dropped the structural finding here — the audit blocker.
    real2 = '[{"file":"y.py","line_range":[9,9],"summary":"refined","verdict":"minor"}]'
    t3 = f"```json\n{real}\n```\n```json\n{real2}\n```"
    f3, ok3 = review_merge.parse_codereview_result(t3)
    summaries3 = {d["summary"] for d in f3}
    assert ok3 and len(f3) == 2 and summaries3 == {"real bug", "refined"}, (
        "two non-empty arrays must UNION — an earlier (structural) array must NOT be "
        "shadowed by a later (minor) one"
    )
    # genuinely all-empty → clean []
    t4 = f"```json\n{empty}\n```\n```json\n{empty}\n```"
    f4, ok4 = review_merge.parse_codereview_result(t4)
    assert f4 == [] and ok4 is True


def test_parse_skips_malformed_block_for_a_valid_one():
    """A malformed json fence must not shadow a valid array fence (either order) —
    valid findings survive instead of being replaced by an unparseable sentinel."""
    real = '[{"file":"x.py","line_range":[3,3],"summary":"real","verdict":"structural"}]'
    # valid then malformed-last
    f1, ok1 = review_merge.parse_codereview_result(f"```json\n{real}\n```\n```json\n[broken\n```")
    assert ok1 and len(f1) == 1 and f1[0]["summary"] == "real"
    # malformed then valid-last
    f2, ok2 = review_merge.parse_codereview_result(f"```json\n[broken\n```\n```json\n{real}\n```")
    assert ok2 and len(f2) == 1


def test_coerce_range_rejects_bool_elements():
    """bool is an int subclass — [True, False] must NOT become (1, 0); fall through."""
    assert review_merge._coerce_range([True, False], None) == (0, 0)
    assert review_merge._coerce_range(["a", "b"], None) == (0, 0)
    assert review_merge._coerce_range([3, 5], None) == (3, 5)
    assert review_merge._coerce_range(None, True) == (0, 0)  # bool line too


def test_parse_no_cross_tag_shadow_and_ignores_stray_arrays():
    """Round-3 finding: an empty ```json fence must NOT shadow real findings in an
    untagged fence, and a stray non-dict array must not be mistaken for the answer —
    selection is last-array-WITH-FINDINGS, across all fences regardless of tag."""
    real = '[{"file":"x.py","line_range":[3,3],"summary":"real","verdict":"structural"}]'
    # empty ```json fence + real findings in an UNTAGGED fence → real survives
    cross = f"```json\n[]\n```\nand the actual findings:\n```\n{real}\n```"
    f1, ok1 = review_merge.parse_codereview_result(cross)
    assert ok1 and len(f1) == 1 and f1[0]["summary"] == "real", (
        "an empty json-tagged fence must not shadow untagged real findings"
    )
    # real findings followed by a stray non-dict array (a code example) → real survives
    stray = f"```json\n{real}\n```\nexample list:\n```json\n[1, 2, 3]\n```"
    f2, ok2 = review_merge.parse_codereview_result(stray)
    assert ok2 and len(f2) == 1 and f2[0]["summary"] == "real", (
        "a trailing stray non-dict array must not suppress the real findings"
    )


# ---------- Phase 1: parse fail-closed (Task 1.1 – 1.3) ----------


def test_array_shape_classification():
    """_array_shape classifies lists as empty / findings / ambiguous."""
    assert review_merge._array_shape([]) == "empty"
    assert review_merge._array_shape([{"x": 1}]) == "findings"
    assert review_merge._array_shape([1, 2, 3]) == "ambiguous"      # all-non-dict
    assert review_merge._array_shape([[{"x": 1}]]) == "ambiguous"   # nested list, dicts at depth 2
    # a mixed list with at least one dict at depth 1 → findings win
    assert review_merge._array_shape([1, {"x": 1}]) == "findings"


def test_parse_codereview_result_fail_closed():
    """parse_codereview_result closes the three parse holes via _array_shape."""
    # Hole 1: nested [[{...}]] — dicts at depth 2, none at depth 1 → ([], False)
    nested = '```json\n[[{"file":"a.py","verdict":"structural","summary":"s","line_range":[1,1]}]]\n```'
    f, ok = review_merge.parse_codereview_result(nested)
    assert f == [] and ok is False, f"nested array must be unparseable (blocks); got ok={ok}"

    # Hole 2: all-non-dict [1,2,3] alone → ([], False) (ambiguous → blocks)
    all_int = '```json\n[1,2,3]\n```'
    f, ok = review_merge.parse_codereview_result(all_int)
    assert f == [] and ok is False, f"all-non-dict alone must block; got ok={ok}"

    # literal [] → ([], True) — the ONLY genuine clean signal
    clean = '```json\n[]\n```'
    f, ok = review_merge.parse_codereview_result(clean)
    assert f == [] and ok is True, "empty array must be genuinely clean"

    # [1,2,3] fence AND a real findings fence in the same reply → findings win, ok=True
    mixed = (
        '```json\n[1,2,3]\n```\n'
        '```json\n[{"file":"x.py","verdict":"structural","summary":"bug","line_range":[1,1]}]\n```'
    )
    f, ok = review_merge.parse_codereview_result(mixed)
    assert ok is True and len(f) == 1, f"findings fence must win over ambiguous; got ok={ok}, f={f}"

    # two findings arrays (union case) → both dicts returned, ok=True (no regression)
    real1 = '{"file":"a.py","verdict":"structural","summary":"bug1","line_range":[1,1]}'
    real2 = '{"file":"b.py","verdict":"minor","summary":"nit","line_range":[2,2]}'
    union = f'```json\n[{real1}]\n```\n```json\n[{real2}]\n```'
    f, ok = review_merge.parse_codereview_result(union)
    assert ok is True and len(f) == 2, f"union of two findings arrays must return both; got {len(f)}"


def test_merge_codereview_angles_no_angles_blocks():
    """merge_codereview_angles([]) and (None) → ONE structural sentinel (no-angles)."""
    for responses in ([], None):
        result = review_merge.merge_codereview_angles(responses)
        assert len(result) == 1, (
            f"empty/None fan-out must yield one sentinel; got {len(result)} for {responses!r}"
        )
        sentinel = result[0]
        assert sentinel["verdict"] == "structural"
        assert sentinel.get("source") == "no-angles"
        assert "no-angles" in sentinel.get("file", "")

    # non-empty per-angle path is UNCHANGED (one clean angle → [])
    clean_angle = "```json\n[]\n```"
    result = review_merge.merge_codereview_angles([clean_angle])
    assert result == [], f"a single clean angle must return []; got {result}"


# ---------- Phase 1 Task 1.1: is_degraded_review predicate ----------


def test_is_degraded_review_empty_list_is_not_degraded():
    """Empty [] is a genuinely clean review — NOT degraded."""
    assert review_merge.is_degraded_review([]) is False


def test_is_degraded_review_no_angles_sentinel_is_degraded():
    """The no-angles sentinel produced by merge_codereview_angles([]) is degraded."""
    sentinels = review_merge.merge_codereview_angles([])
    assert review_merge.is_degraded_review(sentinels) is True


def test_is_degraded_review_unparseable_file_sentinel_is_degraded():
    """A list whose every element has file.startswith('<review-output:') is degraded."""
    degraded = [{"file": "<review-output:angle-1>", "verdict": "structural",
                 "summary": "could not be parsed", "source": "angle-1"}]
    assert review_merge.is_degraded_review(degraded) is True


def test_is_degraded_review_multiple_sentinels_is_degraded():
    """All-sentinel list (no-angles + unparseable) -> degraded."""
    sentinels = [
        {"file": "<review-output:angle-1>", "source": "angle-1", "verdict": "structural", "summary": "x"},
        {"file": "<review-output:angle-2>", "source": "angle-2", "verdict": "structural", "summary": "y"},
    ]
    assert review_merge.is_degraded_review(sentinels) is True


def test_is_degraded_review_no_angles_source_is_degraded():
    """A list whose only element has source=='no-angles' is degraded."""
    sentinel = [{"file": "<review-output:no-angles>", "source": "no-angles",
                 "verdict": "structural", "summary": "no reviewer ran"}]
    assert review_merge.is_degraded_review(sentinel) is True


def test_is_degraded_review_mixed_real_and_sentinel_is_not_degraded():
    """A list with >=1 real finding (even alongside a sentinel) is NOT degraded."""
    mixed = [
        {"file": "real_file.py", "source": "code-review", "verdict": "structural",
         "summary": "real finding", "line_range": [1, 2]},
        {"file": "<review-output:angle-1>", "source": "angle-1", "verdict": "structural", "summary": "x"},
    ]
    assert review_merge.is_degraded_review(mixed) is False


def test_is_degraded_review_real_findings_only_is_not_degraded():
    """A list of only real findings is NOT degraded."""
    real = [
        {"file": "a.py", "source": "code-review", "verdict": "structural",
         "summary": "real bug", "line_range": [5, 7]},
    ]
    assert review_merge.is_degraded_review(real) is False
