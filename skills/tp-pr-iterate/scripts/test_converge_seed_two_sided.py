"""Two-sided `converge._seed_state`, round/ordinal stdin, blocking-only guard.

design: iterate-convergence-budget (Task 3.5). `_seed_state` merges into an
existing state: it preserves the budget's counters and fields, overwrites the
convergence-priming fields, and leaves a budget terminal for tick to re-evaluate.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import converge  # noqa: E402
import review_merge  # noqa: E402

NOW = "2026-09-24T12:00:00+00:00"
K = "consecutive_codereview_structural_rounds"
BUDGET = {"budget_pr_url": "https://github.com/o/r/pull/1", "budget_baseline_head": "h1",
          "budget_baseline_split": {"test_added": 1, "code_added": 2},
          "budget_last_head": "h3", "budget_last_round": "r3", "budget_last_action": "fix",
          "budget_head_blocking": True}


def _prior(path: Path, **kw) -> None:
    st = {"phase": "awaiting-review", "iteration": 3, "max_iterations": 8,
          "max_wall_clock_sec": 14400, "started_at": "2026-09-24T10:00:00+00:00",
          "transitions": [], "original_diff_lines": 250, K: 2,
          "last_verdict": "structural-present", "last_codereview_head_sha": "h3",
          "last_codereview_findings": [{"file": "a.py"}], **BUDGET}
    st.update(kw)
    path.write_text(json.dumps(st), encoding="utf-8")


def _seed(path: Path, head="h4") -> dict:
    converge._seed_state(path, head, now_iso=NOW)
    return json.loads(path.read_text(encoding="utf-8"))


def test_existing_state_preserves_budget_and_overwrites_priming(tmp_path):
    path = tmp_path / "state.json"
    _prior(path)
    s = _seed(path)
    assert (s["iteration"], s["started_at"], s["original_diff_lines"], s[K]) == (
        3, "2026-09-24T10:00:00+00:00", 250, 2)
    assert {k: s[k] for k in BUDGET} == BUDGET
    assert s["last_verdict"] == "minor-only"
    assert s["last_codereview_head_sha"] == "h4" and s["last_codereview_findings"] == []
    assert s["phase"] == "awaiting-copilot" and s.get("termination_reason") is None


def test_budget_terminal_phase_survives(tmp_path):
    path = tmp_path / "state.json"
    _prior(path, phase="budget-exhausted", termination_reason="round-cap", iteration=6)
    s = _seed(path)
    assert (s["phase"], s["termination_reason"], s["iteration"]) == (
        "budget-exhausted", "round-cap", 6)


def test_non_budget_terminal_phase_is_overwritten(tmp_path):
    path = tmp_path / "state.json"
    _prior(path, phase="blocked-no-independent-review", termination_reason=None)
    assert _seed(path)["phase"] == "awaiting-copilot"


def test_absent_state_seeds_round_zero(tmp_path):
    s = _seed(tmp_path / "state.json")
    assert s["iteration"] == 0 and s["original_diff_lines"] is None
    assert s["started_at"] == NOW and s["last_verdict"] == "minor-only"


def test_stdin_carries_round_and_ordinal(tmp_path):
    payload = converge.build_run_round_stdin(
        state_path=tmp_path / "s.json", head_sha="h", codereview_findings=[],
        review_proof_root=tmp_path, review_base="b", config=None, pr_url="u",
        round=3, ordinal="r3.1")
    assert (payload["round"], payload["ordinal"]) == (3, "r3.1")
    json.dumps(payload)


def test_guard_refusal_only_on_blocking():
    note = {"source": "code-review", "file": "a.py", "line_range": [1, 1],
            "summary": "nit", "verdict": "minor"}
    assert converge.guard_refusal([note]) is None
    assert converge.guard_refusal([dict(note, verdict="structural")]) is not None
    assert "DEGRADED" in converge.guard_refusal(review_merge.merge_codereview_angles([]))
    assert converge.guard_refusal([]) is None
