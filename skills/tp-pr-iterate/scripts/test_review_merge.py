"""Tests for review_merge — normalize + dedupe dual-source review findings (Enh.1)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import review_merge  # noqa: E402

CLEAN = '{"findings": []}'

_SCHEMA = json.loads(
    (HERE.parent / "schemas" / "normalized-finding.v1.json").read_text(encoding="utf-8")
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
        "```json\n"
        '{"findings": [{"file": "x.py", "line_range": [3, 4], "summary": "bug", "verdict": "structural"}]}\n'
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
    # genuine clean review: {"findings": []} → parsed_ok True
    findings, ok = review_merge.parse_codereview_result(CLEAN)
    assert findings == [] and ok is True
    # valid findings
    findings, ok = review_merge.parse_codereview_result(
        '```json\n{"findings": [{"file":"a.py","verdict":"minor","summary":"x","line_range":[1,1]}]}\n```'
    )
    assert ok is True and len(findings) == 1
    # UNPARSEABLE: no object / invalid JSON / no findings key / a bare list (the old
    # format) → parsed_ok False (NOT clean). The full mutation families live in
    # test_review_merge_reply_strict.py.
    for bad in ("no json here", "```json\n{not valid\n```", "", "```json\n{}\n```", "```json\n[]\n```"):
        f, ok = review_merge.parse_codereview_result(bad)
        assert f == [] and ok is False, f"{bad!r} must be unparseable (ok=False), got ok={ok}"
    # A findings list with a non-dict item → ([], False): never partially read.
    f, ok = review_merge.parse_codereview_result('{"findings": [1, 2, "x"]}')
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
    assert review_merge.parse_codereview_response(CLEAN) == []


def test_findings_or_block_injects_structural_sentinel_on_unparseable():
    # clean → []
    assert review_merge.parse_codereview_findings_or_block(CLEAN) == []
    # unparseable → ONE structural sentinel (blocks convergence, never silent [])
    out = review_merge.parse_codereview_findings_or_block("garbage, no json")
    assert len(out) == 1
    assert out[0]["verdict"] == "structural"
    assert "could not be parsed" in out[0]["summary"].lower()


def test_merge_codereview_angles_dedupes_and_fails_closed():
    # two angles find the SAME defect (same file + proximate line + similar summary) → 1 after dedupe
    a1 = '{"findings": [{"file":"g.py","line_range":[10,10],"summary":"off by one in loop","verdict":"structural"}]}'
    a2 = '{"findings": [{"file":"g.py","line_range":[10,11],"summary":"off-by-one in the loop","verdict":"structural"}]}'
    merged = review_merge.merge_codereview_angles([a1, a2])
    assert len(merged) == 1, f"duplicate finding across angles must collapse; got {len(merged)}"

    # a clean angle + an UNPARSEABLE angle → EXACTLY one structural sentinel (the clean
    # [] must add nothing; the unparseable one blocks convergence)
    merged2 = review_merge.merge_codereview_angles([CLEAN, "totally broken"])
    assert len(merged2) == 1, f"clean + unparseable must yield exactly 1 finding; got {len(merged2)}"
    assert merged2[0]["verdict"] == "structural"
    assert "could not be parsed" in merged2[0]["summary"].lower()

    # TWO unparseable angles → TWO DISTINCT sentinels (operator must see how many failed,
    # not have them collapse to one via dedupe)
    two_bad = review_merge.merge_codereview_angles(["junk one", "junk two"])
    assert len(two_bad) == 2, f"two failed angles must surface as two sentinels; got {len(two_bad)}"
    assert all(f["verdict"] == "structural" for f in two_bad)

    # all-clean angles → genuinely empty (the round may converge)
    assert review_merge.merge_codereview_angles([CLEAN, CLEAN]) == []

    # None / empty input → ONE no-angles sentinel (fail-closed; blocks convergence).
    # (pr-iterate-loop-hardening Hole 3 fix: was [] before, now returns sentinel.)
    for empty_input in (None, []):
        result = review_merge.merge_codereview_angles(empty_input)
        assert len(result) == 1 and result[0]["verdict"] == "structural", (
            f"None/[] fan-out must yield one structural sentinel; got {result} for {empty_input!r}"
        )

    # a non-str angle reply fails closed to a sentinel, never crashes the merge
    assert len(review_merge.merge_codereview_angles([None])) == 1

    # garbage list items make the whole reply unparseable (one sentinel), never a
    # partial read that drops what the angle meant to say
    garbage = review_merge.merge_codereview_angles(
        ['{"findings": [1, "x", {"file":"r.py","line_range":[2,2],"summary":"real","verdict":"minor"}]}']
    )
    assert len(garbage) == 1 and review_merge.is_degraded_review(garbage)

    # all-clean angles → genuinely empty (may converge)
    assert review_merge.merge_codereview_angles([CLEAN, CLEAN]) == []


def test_coerce_range_rejects_bool_elements():
    """bool is an int subclass — [True, False] must NOT become (1, 0); fall through."""
    assert review_merge._coerce_range([True, False], None) == (0, 0)
    assert review_merge._coerce_range(["a", "b"], None) == (0, 0)
    assert review_merge._coerce_range([3, 5], None) == (3, 5)
    assert review_merge._coerce_range(None, True) == (0, 0)  # bool line too


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
    result = review_merge.merge_codereview_angles([CLEAN])
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


# ---------- codereview-proof-of-review: Task 4.1 post_codereview_comment digest ----------


def test_post_codereview_comment_digest_appended():
    """With digest provided, body ends with the digest line."""
    posted_bodies = []

    def _capture(pr_url, body):
        posted_bodies.append(body)
        return True

    review_merge.post_codereview_comment(
        "https://github.com/o/r/pull/1",
        [],
        head_sha="abc123",
        post_fn=_capture,
        digest="<sub>proof: base `abc` · head `def` · 3 files +10 −2</sub>",
    )
    assert len(posted_bodies) == 1
    body = posted_bodies[0]
    assert body.endswith("<sub>proof: base `abc` · head `def` · 3 files +10 −2</sub>"), (
        f"body must end with the digest line; got: {body!r}"
    )
    assert "\n" in body, "body must contain a newline separator before the digest"


def test_post_codereview_comment_no_digest_byte_compat():
    """Without digest, body is byte-identical to the pre-digest form."""
    import review_merge as rm
    posted_bodies_without = []
    posted_bodies_with_none = []

    def _cap_without(pr_url, body):
        posted_bodies_without.append(body)
        return True

    def _cap_with_none(pr_url, body):
        posted_bodies_with_none.append(body)
        return True

    findings = []
    head = "abc123"

    # Old-style call (no digest kwarg)
    rm.post_codereview_comment(
        "https://github.com/o/r/pull/1", findings,
        head_sha=head, post_fn=_cap_without,
    )
    # Explicit digest=None
    rm.post_codereview_comment(
        "https://github.com/o/r/pull/1", findings,
        head_sha=head, post_fn=_cap_with_none, digest=None,
    )

    assert posted_bodies_without == posted_bodies_with_none, (
        "digest=None must be byte-identical to the no-digest call"
    )
    # Also verify the expected body matches format_codereview_comment
    expected = rm.format_codereview_comment(findings, head_sha=head)
    assert posted_bodies_without[0] == expected
