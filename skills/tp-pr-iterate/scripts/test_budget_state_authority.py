"""Cross-cwd state authority — characterization (real subprocess CLIs).

design: iterate-convergence-budget (Task 7.1, finding 1, A4)

`converge.py --round-dir` and `run_round.py` run by subprocess from TWO temp
worktrees against one round manifest. The manifest is the path authority, so the
state accumulates in one file whichever cwd a step runs from. Only `gh` is shimmed
(`loop_itest.fake_gh`); converge's finish (capture → post → seed → run_round →
oracle) runs its real code.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import loop_itest as it  # noqa: E402
import round_budget  # noqa: E402


@pytest.fixture()
def pr(tmp_path):
    wt1, base, head = it.make_repo(tmp_path)
    wt2 = tmp_path / "wt2"
    it.git(wt1, "worktree", "add", "-q", "--detach", str(wt2), "feat")
    loop = it.Loop(tmp_path, it.fake_gh(tmp_path))
    return wt1, wt2, base, head, loop


def _blocking_round(loop, cwd, base, head):
    rd = loop.prepare(cwd, base, head)
    it.write_replies(rd, it.reply([it.blocking_finding()]))
    rep = loop.reproduce(rd, cwd, head)
    assert rep.returncode == 0, rep.stdout + rep.stderr
    assert it.last_json(rep)["blocking"] == 1
    rr = loop.run_round(rd, cwd, it.tail_findings(rd))
    assert rr.returncode == 0, rr.stdout + rr.stderr
    return rd, it.last_json(rr)


def _clean_round(loop, cwd, base, head):
    rd = loop.prepare(cwd, base, head)
    it.write_replies(rd)
    rep = loop.reproduce(rd, cwd, head)
    assert rep.returncode == 0, rep.stdout + rep.stderr
    return rd


def test_converge_on_absent_state_seeds_round_one(pr):
    """converge.py --round-dir on an absent state → run_round → iteration 1, R1 baseline."""
    wt1, _wt2, base, head, loop = pr
    rd = _clean_round(loop, wt1, base, head)
    assert not loop.state.exists()
    proc = loop.converge(rd, wt1)
    out = it.last_json(proc)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert out["converged"] is True and out["proof_verified"] is True
    assert out["class_tally"]["blocking"] == 0
    state = loop.read_state()
    assert state["iteration"] == 1
    measure = round_budget.split(round_budget.git_numstat(base, head, cwd=wt1))
    assert measure["total"] == 40
    assert state["original_diff_lines"] == measure["total"]
    assert state["budget_baseline_head"] == head
    assert state["budget_baseline_split"] == {"test_added": measure["test_added"],
                                              "code_added": measure["code_added"]}
    assert loop.class_log.read_text(encoding="utf-8").count("\n") == 1


def test_iteration_accumulates_to_round_cap_across_two_cwds(pr):
    """Blocking rounds alternate cwds, a converge round counts too, round-cap fires at 6."""
    wt1, wt2, base, head, loop = pr
    cwds = [wt1, wt2]
    prev = None
    for n in range(1, 6):
        if prev is not None:
            it.write_envelope(prev, action="fix", head_reviewed=head, head_after=head)
        prev, env = _blocking_round(loop, cwds[n % 2], base, head)
        assert env["terminal"] is None and env["action"] == "fix"
        assert env["budget"]["iteration"] == n
        assert loop.read_state()["iteration"] == n
    it.write_envelope(prev, action="fix", head_reviewed=head, head_after=head)
    rd6 = _clean_round(loop, wt2, base, head)
    proc = loop.converge(rd6, wt2)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert loop.read_state()["iteration"] == 6
    it.write_envelope(rd6, action="noop", head_reviewed=head, head_after=head,
                      terminal="two-stable [code-review-only]", converged=True)
    _rd7, env = _blocking_round(loop, wt1, base, head)
    assert env["terminal"] == "budget-exhausted"
    assert env["budget"]["signal"] == "round-cap"
    assert env["budget"]["iteration"] == 6 and env["budget"]["round_cap"] == 6
    state = loop.read_state()
    assert state["termination_reason"] == "round-cap"
    assert state["budget_pr_url"] == it.PR


def test_mismatched_state_refused(pr, tmp_path):
    wt1, wt2, base, head, loop = pr
    rd = _clean_round(loop, wt1, base, head)
    proc = loop.converge(rd, wt2, "--state", str(tmp_path / "elsewhere.json"))
    assert proc.returncode == 2
    assert it.last_json(proc)["reason"] == "state-path-mismatch"
    assert not loop.state.exists() and not (tmp_path / "elsewhere.json").exists()


def test_round_two_absent_state_both_refuse_and_seed_nothing(pr):
    wt1, wt2, base, head, loop = pr
    rd1 = _clean_round(loop, wt1, base, head)
    it.write_envelope(rd1, action="fix", head_reviewed=head, head_after=head)
    rd2 = _clean_round(loop, wt2, base, head)
    assert it.manifest(rd2)["round"] == 2
    conv = loop.converge(rd2, wt2)
    assert conv.returncode == 2
    assert it.last_json(conv)["reason"] == "state-bootstrapped-mid-loop"
    rr = loop.run_round(rd2, wt1, it.tail_findings(rd2))
    assert rr.returncode == 2
    assert it.last_json(rr)["event_token"] == "state-bootstrapped-mid-loop"
    assert not loop.state.exists()
    assert not loop.state.with_name(loop.state.name + ".tmp").exists()
