"""A two-stable converge clears the fix rounds' `tp:do-not-merge-yet` label as it adds the ready label."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import loop_driver  # noqa: E402
from test_loop_driver import _make_run_round_config, _minimal_state_for_run_round  # noqa: E402

PR = "https://github.com/owner/repo/pull/1"


def _round(tmp_path, *, head="head1", findings=None):
    now = datetime(2026, 10, 15, 12, 0, 0, tzinfo=timezone.utc)
    state = _minimal_state_for_run_round(now)
    state.update(seen_thread_ids=[], last_codereview_head_sha="head1", last_codereview_findings=[])
    added, removed = [], []
    result = loop_driver.run_round(
        state, head_sha=head, codereview_findings=findings or [], reviewed=None,
        unresolved_actionable=0, ci_rollup=[], config=_make_run_round_config(expects_copilot=False),
        now=now, decisions_path=tmp_path / "decisions.md", pr_url=PR,
        label_fn=lambda pr, lbl: added.append(lbl), unlabel_fn=lambda pr, lbl: removed.append(lbl),
    )
    return result, added, removed


def test_converge_removes_do_not_merge_yet_and_adds_ready(tmp_path):
    result, added, removed = _round(tmp_path)
    assert result["terminal"] in ("two-stable [code-review-only]", "two-stable")
    assert "tp:ready-for-human-merge" in added
    assert "tp:do-not-merge-yet" in removed


def test_a_round_with_real_findings_keeps_do_not_merge_yet(tmp_path):
    finding = {"file": "a.py", "verdict": "structural", "summary": "bug", "line_range": [1, 2]}
    _, added, removed = _round(tmp_path, head="head2", findings=[finding])
    assert "tp:do-not-merge-yet" not in removed
    assert "tp:ready-for-human-merge" not in added
