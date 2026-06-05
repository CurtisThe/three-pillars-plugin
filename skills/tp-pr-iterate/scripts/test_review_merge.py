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
