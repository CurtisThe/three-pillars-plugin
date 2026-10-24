"""Tests for review_stop — the converge-time decision stop (pure core).

design: seat-escalate-first (Task 1.2)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_shared"))

import finalizer  # noqa: E402
import review_stop  # noqa: E402

HEAD = "0123456789abcdef0123456789abcdef01234567"
HEAD2 = "fedcba9876543210fedcba9876543210fedcba98"
URL = "https://github.com/o/r/pull/9"

N1 = {"title": "Rename helper for clarity", "summary": "name is vague", "verdict": "minor"}
N2 = {"title": "Tighten docstring wording", "summary": "docstring loose", "verdict": "minor"}
BLOCK = {"title": "Crash on empty input", "verdict": "structural"}
SENTINEL = {"source": "no-angles", "title": "no angles ran", "verdict": "minor"}


def _due(state=None, findings=(N1, N2), head=HEAD):
    return review_stop.due(state or {}, list(findings), pr_url=URL, head=head)


def test_notes_keeps_non_blocking_only():
    assert review_stop.notes([N1, BLOCK, SENTINEL, N2]) == [N1, N2]


def test_notes_drops_review_output_sentinel():
    s = {"file": "<review-output:x>", "title": "t", "verdict": "minor"}
    assert review_stop.notes([s]) == []


def test_due_none_without_notes():
    assert _due(findings=[]) is None
    assert _due(findings=[BLOCK, SENTINEL]) is None


def test_due_emits_decision_question():
    stop = _due()
    assert stop["source"] == "question"
    assert stop["signal"] == "decision"
    assert stop["target"] == URL
    assert stop["head"] == HEAD
    q = stop["detail"]["question"]
    assert "stop here, or fix these notes first?" in q
    assert "Rename helper for clarity" in q and "Tighten docstring wording" in q
    assert HEAD not in q and HEAD[:12] not in q
    assert [o["id"] for o in stop["detail"]["options"]] == ["stop", "fix"]
    assert stop["detail"]["notes"] == [N1, N2]


def test_stop_record_same_head_covers():
    state = {"review_stop": {"choice": "stop", "head": HEAD, "iteration": 3}}
    assert _due(state) is None


def test_stop_record_other_head_does_not_cover():
    state = {"review_stop": {"choice": "stop", "head": HEAD2, "iteration": 3}}
    assert _due(state)["source"] == "question"


def test_fix_record_never_covers():
    same = {"review_stop": {"choice": "fix", "head": HEAD, "iteration": 3}}
    old = {"review_stop": {"choice": "fix", "head": HEAD2, "iteration": 2}}
    assert _due(same)["source"] == "question"
    assert _due(old)["source"] == "question"


def test_stop_key_stable_across_heads_and_differs_by_notes():
    k1 = finalizer.stop_key(_due(head=HEAD))
    k2 = finalizer.stop_key(_due(head=HEAD2))
    other = {"title": "Completely different gripe", "verdict": "minor"}
    k3 = finalizer.stop_key(_due(findings=[other]))
    assert k1 == k2
    assert k1 != k3
