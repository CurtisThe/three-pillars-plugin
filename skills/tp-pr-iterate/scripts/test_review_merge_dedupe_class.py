"""Dedupe promotion carries the finding-class tags with the verdict.

design: iterate-convergence-budget (Task 1.5)

A Copilot `minor` can win a collision with a blocking code-review twin (thread_id
precedence). `_promote_verdict` already lifts the verdict; the survivor must also
gain the twin's `blocking`/`class`/`reproducer`, or the reproducer runner and the
class tally lose the blocking claim that the verdict still asserts.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import review_merge  # noqa: E402
from review_merge_dedupe import _promote_verdict  # noqa: E402

_REPRO = {"kind": "command", "argv": ["python3", "x.py"], "expect": {"exit": 0}}


def _blocking_cr() -> dict:
    return review_merge.normalize_codereview(
        {"finding_id": "cr1", "file": "a.py", "line_range": [10, 12],
         "summary": "off-by-one drops the last item", "class": "P",
         "blocking": True, "reproducer": _REPRO})


def _minor_cop() -> dict:
    return review_merge.normalize_copilot(
        {"comment_id": 5, "thread_id": "RT_5", "path": "a.py", "line_range": [10, 12],
         "body": "off-by-one drops the last item", "verdict": "minor"})


def test_promote_verdict_carries_blocking_class_reproducer():
    survivor, dropped = _minor_cop(), _blocking_cr()
    _promote_verdict(survivor, dropped)
    assert survivor["verdict"] == "structural"
    assert survivor["blocking"] is True
    assert survivor["class"] == "P"
    assert survivor["reproducer"] == _REPRO


def test_dedupe_survivor_keeps_thread_and_blocking_tags():
    kept = review_merge.dedupe([_minor_cop(), _blocking_cr()])
    assert len(kept) == 1
    assert kept[0]["thread_id"] == "RT_5"
    assert (kept[0]["verdict"], kept[0]["blocking"]) == ("structural", True)
    assert kept[0]["reproducer"] == _REPRO


def test_no_promotion_carries_nothing():
    survivor = _blocking_cr()
    dropped = review_merge.normalize_codereview(
        {"file": "a.py", "summary": "note", "class": "T", "blocking": False})
    _promote_verdict(survivor, dropped)
    assert (survivor["class"], survivor["blocking"]) == ("P", True)
