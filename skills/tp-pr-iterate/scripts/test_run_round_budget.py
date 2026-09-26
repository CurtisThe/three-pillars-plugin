"""Budget wiring through `loop_driver.run_round` (in-process) and `run_round.py` (CLI).

design: iterate-convergence-budget (Tasks 3.3, 3.4). `round_budget.tick` runs on
every round, before two-stable; a budget terminal labels needs-human-attention and
returns `action: "noop"` with the tick detail as `budget`.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import loop_driver  # noqa: E402
import review_merge  # noqa: E402

NOW = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)
PR = "https://github.com/o/r/pull/9"
CFG = {"review": {"expects_copilot": False}, "ci": {"expects_github_checks": False}}
K = "consecutive_codereview_structural_rounds"
BLOCKING = {"source": "code-review", "file": "a.py", "line_range": [1, 2], "summary": "bug",
            "verdict": "structural", "class": "P", "blocking": True}
MINOR = dict(BLOCKING, verdict="minor", blocking=False, **{"class": "C"})


def _state(**kw):
    st = {"phase": "awaiting-review", "iteration": 0, "max_iterations": 8,
          "max_wall_clock_sec": 14400, "started_at": NOW.isoformat(), "transitions": [],
          "last_verdict": "minor-only", "budget_pr_url": PR}
    st.update(kw)
    return st


def _round(state, findings, *, head="h1", ordinal="r1", now=NOW, labels=None, **kw):
    labels = [] if labels is None else labels
    return loop_driver.run_round(
        state, head_sha=head, codereview_findings=findings, reviewed=None,
        unresolved_actionable=0, ci_rollup=[], config=kw.pop("config", CFG), now=now,
        pr_url=PR, proof_ok=True, ordinal=ordinal,
        label_fn=lambda _u, lbl: labels.append(("+", lbl)),
        unlabel_fn=lambda _u, lbl: labels.append(("-", lbl)), **kw)


def test_run_round_budget_terminal_round_cap():
    labels = []
    st = _state(iteration=5, budget_last_head="h5", budget_last_round="r5",
                budget_last_action="fix")
    out = _round(st, [BLOCKING], head="h6", ordinal="r6", labels=labels)
    s = out["state"]
    assert out["action"] == "noop" and out["terminal"] == "budget-exhausted"
    assert s["phase"] == "budget-exhausted" and s["termination_reason"] == "round-cap"
    assert s["transitions"][-1]["phase"] == "budget-exhausted"
    assert out["budget"]["signal"] == "round-cap" and out["budget"]["iteration"] == 6
    assert ("+", "tp:needs-human-attention") in labels
    assert ("-", "tp:ready-for-human-merge") in labels
    assert (s["budget_last_head"], s["budget_last_round"], s["budget_last_action"]) == (
        "h6", "r6", "noop")


def test_run_round_budget_runs_before_two_stable():
    """A clean, convergence-eligible round over the wall clock stops, never converges."""
    labels = []
    st = _state(started_at=(NOW - timedelta(hours=5)).isoformat())
    out = _round(st, [], labels=labels)
    assert out["terminal"] == "cap-exhausted"
    assert out["state"]["termination_reason"] == "wall-clock"
    assert ("+", "tp:ready-for-human-merge") not in labels


def test_run_round_non_blocking_notes_converge():
    out = _round(_state(), [MINOR])
    assert out["action"] == "noop"
    assert out["terminal"] == "two-stable [code-review-only]"
    assert out["budget"]["signal"] is None


def test_run_round_budget_last_fields():
    out = _round(_state(), [BLOCKING])
    s = out["state"]
    assert out["action"] == "fix" and out["terminal"] is None
    assert (s["budget_last_head"], s["budget_last_round"], s["budget_last_action"]) == (
        "h1", "r1", "fix")
    assert s["iteration"] == 1 and s[K] == 1
    degraded = review_merge.merge_codereview_angles([])
    s2 = _round(s, degraded, head="h2", ordinal="r2")["state"]
    assert s2["budget_last_action"] == "degraded"
    s3 = _round(s2, [], head="h2", ordinal="r2.1")["state"]
    assert s3["budget_last_action"] == "noop"


def test_run_round_counter_owned_by_tick():
    """A same-head re-shell no longer bumps the k-counter in run_round (tick owns it)."""
    st = _state(iteration=1, budget_last_head="h1", budget_last_round="r1",
                budget_last_action="fix", **{K: 1})
    out = _round(st, [BLOCKING], head="h1", ordinal=None)
    assert out["state"][K] == 1 and out["state"]["iteration"] == 1


def test_run_round_passes_numstat_and_class_log(tmp_path):
    log = tmp_path / "iterate-log.md"
    calls = []

    def numstat(a, b):
        calls.append((a, b))
        return [("src/a.py", 40, 0)]

    out = _round(_state(), [BLOCKING], review_base="base1", numstat_fn=numstat,
                 class_log_path=log)
    assert calls == [("base1", "h1")]
    assert out["state"]["original_diff_lines"] == 40
    assert out["state"]["budget_baseline_head"] == "h1"
    assert log.read_text(encoding="utf-8").startswith("[tp-pr-iterate] round 1 head=h1 ")


# ---------- Task 3.4: run_round.py CLI (subprocess, like test_run_round_cli.py) ----------


def _cli(payload):
    proc = subprocess.run([sys.executable, str(HERE / "run_round.py")],
                          input=json.dumps(payload).encode(), capture_output=True)
    return proc.returncode, json.loads(proc.stdout.strip())


def test_cli_budget_exhausted_envelope(tmp_path):
    fresh = datetime.now(tz=timezone.utc).isoformat()
    state_file = tmp_path / "iterate-state.json"
    state_file.write_text(json.dumps(_state(
        started_at=fresh, iteration=5, last_verdict="structural-present",
        budget_last_head="h5", budget_last_round="r5", budget_last_action="fix")),
        encoding="utf-8")
    log = tmp_path / "iterate-log.md"
    rc, env = _cli({"state_path": str(state_file), "head_sha": "h6",
                    "codereview_findings": [BLOCKING], "reviewed": None,
                    "unresolved_actionable": 1, "ci_rollup": [], "config": CFG,
                    "pr_url": PR, "round": 6, "ordinal": "r6",
                    "class_log_path": str(log)})
    assert rc == 0, env
    assert env["terminal"] == "budget-exhausted" and env["action"] == "noop"
    assert env["budget"]["signal"] == "round-cap" and env["budget"]["iteration"] == 6
    saved = json.loads(state_file.read_text(encoding="utf-8"))
    assert saved["termination_reason"] == "round-cap"
    assert saved["budget_last_round"] == "r6"
    assert log.read_text(encoding="utf-8").startswith("[tp-pr-iterate] round 6 head=h6 ")


def test_cli_round2_absent_state_exits_2_no_seed(tmp_path):
    state_file = tmp_path / "iterate-state.json"
    payload = {"state_path": str(state_file), "head_sha": "h2", "codereview_findings": [],
               "reviewed": None, "unresolved_actionable": 0, "config": CFG,
               "pr_url": PR, "round": 2, "ordinal": "r2"}
    rc, env = _cli(payload)
    assert rc == 2
    assert env["event_token"] == "state-bootstrapped-mid-loop"
    assert not state_file.exists()
    state_file.write_text("", encoding="utf-8")  # zero-length counts as absent
    rc, env = _cli(payload)
    assert (rc, env["event_token"]) == (2, "state-bootstrapped-mid-loop")
    assert state_file.read_text(encoding="utf-8") == ""


def test_cli_round1_absent_state_bootstraps(tmp_path):
    state_file = tmp_path / "iterate-state.json"
    rc, env = _cli({"state_path": str(state_file), "head_sha": "h1",
                    "codereview_findings": [BLOCKING], "reviewed": None,
                    "unresolved_actionable": 1, "config": CFG, "pr_url": PR,
                    "round": 1, "ordinal": "r1"})
    assert rc == 0 and env.get("state_bootstrapped") is True
    assert env["budget"]["signal"] is None
    assert json.loads(state_file.read_text(encoding="utf-8"))["budget_last_round"] == "r1"


def test_run_loop_symbols_gone():
    """Task 4.1: the uncapped `run_loop` driver and its guard helpers are deleted;
    the helpers `run_round` still uses keep importing."""
    gone = ("run_loop", "_check_guards", "_apply_guards", "_capture_original_diff",
            "_STAT_NUMBERS_RE", "_K_CONSECUTIVE_DEFAULT",
            "_DIFF_GROWTH_MULTIPLIER_DEFAULT", "_resolve_pr_head")
    assert [s for s in gone if hasattr(loop_driver, s)] == []
    kept = ("_apply_conflicts", "_codereview_effort", "_should_review_head",
            "_cached_findings_for_head", "_poll_step", "_request_copilot_review",
            "_compute_next_wait")
    assert all(callable(getattr(loop_driver, s)) for s in kept)
