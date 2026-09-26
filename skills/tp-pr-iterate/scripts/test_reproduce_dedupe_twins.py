"""A reproduced blocking twin is not lost to a non-reproducing survivor at dedupe.

design: iterate-convergence-budget (PR #158 round r1 fix)

Two angles flag the same defect (same file + range). `dedupe` keeps one record,
carrying the dropped twin's reproducer in `alt_reproducers`; `run_reproducers`
tries it before downgrading, so a demonstrated defect stays blocking.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import reproduce  # noqa: E402
from finding_class import tally  # noqa: E402
from review_merge import merge_codereview_angles  # noqa: E402

FENCE = "`" * 3


def _reply(code, summary):
    f = {"file": "src/a.py", "line_range": [10, 12], "summary": summary, "class": "P",
         "blocking": True,
         "reproducer": {"kind": "command",
                        "argv": [sys.executable, "-c", f"import sys; sys.exit({code})"],
                        "expect": {"exit": 0}}}
    return FENCE + "json\n" + json.dumps([f]) + "\n" + FENCE + "\n"


def _run(tmp_path, codes):
    replies = [_reply(codes[0], "unguarded path leaks a wrong result on empty input here"),
               _reply(codes[1], "wrong result")]
    merged = merge_codereview_angles(replies)
    assert len(merged) == 1  # the twins collapse to one finding
    findings, _ = reproduce.run_reproducers(merged, cwd=tmp_path, scratch_dir=tmp_path)
    return findings


def test_reproduced_twin_is_not_lost_to_a_non_reproducing_twin(tmp_path):
    findings = _run(tmp_path, (0, 1))
    assert tally(findings)["blocking"] == 1
    assert "downgrade" not in findings[0]


def test_neither_twin_reproduces_downgrades(tmp_path):
    findings = _run(tmp_path, (0, 0))
    assert tally(findings)["blocking"] == 0
    assert findings[0]["downgrade"]["reason"] == reproduce.NOT_REPRODUCED


def test_legacy_twin_does_not_swallow_reproduced_blocking_twin(tmp_path):
    # PR #158 r2: an untagged (legacy-shape) twin with the longer summary survives
    # dedupe; it must adopt the blocking twin's tags + reproducer, not be downgraded
    # `legacy-no-reproducer` while the demonstrated defect is dropped.
    legacy = {"file": "src/a.py", "line_range": [10, 12],
              "summary": "unguarded path leaks a wrong result on empty input here"}
    tagged = json.loads(_reply(1, "wrong result").split("\n")[1])[0]
    replies = [FENCE + "json\n" + json.dumps([f]) + "\n" + FENCE + "\n"
               for f in (legacy, tagged)]
    merged = merge_codereview_angles(replies)
    assert len(merged) == 1
    findings, _ = reproduce.run_reproducers(merged, cwd=tmp_path, scratch_dir=tmp_path)
    assert tally(findings)["blocking"] == 1
    assert "downgrade" not in findings[0]
