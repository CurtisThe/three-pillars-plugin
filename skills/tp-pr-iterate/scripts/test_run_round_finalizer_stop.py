"""`finalizer_stop` reaches the `run_round.py` CLI envelope and `converge.py`'s blocked JSON.

design: fable-first-stops (Task 2.2). `loop_driver.run_round` hands a newly fired
budget terminal to the finalizer as a `finalizer_stop` event; `run_round.py` passes it
through as a conditional additive envelope key (the `state_bootstrapped` pattern), and
`converge.py` forwards it in its blocked JSON, because a clean round finished through
`converge.py` can newly fire growth-lines or wall-clock.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import converge  # noqa: E402

RUN_ROUND_PY = HERE / "run_round.py"
PR = "https://github.com/o/r/pull/9"
# keep-the-pin: the growth case diffs 40 lines, below the 300 floor.
CFG = {"review": {"expects_copilot": False, "automation_identities": ["tp-bot"]},
       "ci": {"expects_github_checks": False},
       "pdw": {"guards": {"growth_floor_lines": 0}}}
BLOCKING = {"source": "code-review", "file": "a.py", "line_range": [1, 2], "summary": "bug",
            "verdict": "structural", "class": "P", "blocking": True}


def _fresh() -> str:
    return (datetime.now(tz=timezone.utc) - timedelta(hours=1)).isoformat()


def _state(**kw) -> dict:
    st = {"phase": "awaiting-review", "iteration": 0, "max_iterations": 8,
          "max_wall_clock_sec": 14400, "started_at": _fresh(), "transitions": [],
          "last_verdict": "structural-present", "budget_pr_url": PR}
    st.update(kw)
    return st


def _cli(payload: dict, cwd=None):
    proc = subprocess.run([sys.executable, str(RUN_ROUND_PY)], input=json.dumps(payload).encode(),
                          capture_output=True, cwd=cwd)
    return proc.returncode, json.loads(proc.stdout.strip())


def _payload(state_file: Path, **kw) -> dict:
    return {"state_path": str(state_file), "head_sha": "h6", "codereview_findings": [BLOCKING],
            "reviewed": None, "unresolved_actionable": 1, "ci_rollup": [], "config": CFG,
            "pr_url": PR, "round": 6, "ordinal": "r6", **kw}


# ---------- run_round.py CLI envelope ----------


def test_cli_envelope_carries_finalizer_stop_on_round_cap(tmp_path):
    state_file = tmp_path / "iterate-state.json"
    state_file.write_text(json.dumps(_state(
        iteration=5, budget_last_head="h5", budget_last_round="r5",
        budget_last_action="fix")), encoding="utf-8")
    rc, env = _cli(_payload(state_file))
    assert rc == 0, env
    assert env["terminal"] == "budget-exhausted" and env["budget"]["signal"] == "round-cap"
    assert env["finalizer_stop"] == {
        "source": "pr-iterate", "signal": "round-cap", "target": PR, "head": "h6",
        "detail": env["budget"]}


def test_cli_held_terminal_envelope_has_no_finalizer_stop(tmp_path):
    state_file = tmp_path / "iterate-state.json"
    state_file.write_text(json.dumps(_state(
        iteration=6, phase="budget-exhausted", termination_reason="round-cap")),
        encoding="utf-8")
    rc, env = _cli(_payload(state_file))
    assert rc == 0, env
    assert env["terminal"] == "budget-exhausted" and "finalizer_stop" not in env


def test_cli_non_terminal_envelope_has_no_finalizer_stop_key(tmp_path):
    state_file = tmp_path / "iterate-state.json"
    state_file.write_text(json.dumps(_state()), encoding="utf-8")
    rc, env = _cli(_payload(state_file, round=1, ordinal="r1"))
    assert rc == 0, env
    assert env["terminal"] is None and env["action"] == "fix"
    assert "finalizer_stop" not in env


# ---------- converge.py blocked envelope ----------


def _git(cwd: Path, *args: str) -> str:
    out = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True)
    return out.stdout.strip()


def _repo(tmp_path: Path) -> tuple[Path, str, str]:
    """A throwaway repo whose base...head diff adds 40 lines: `(repo, base, head)`."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "T")
    _git(repo, "config", "commit.gpgsign", "false")
    (repo / "base.txt").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "base.txt")
    _git(repo, "commit", "-q", "-m", "base")
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "a.py").write_text("x = 1\n" * 40, encoding="utf-8")
    _git(repo, "add", "a.py")
    _git(repo, "commit", "-q", "-m", "head")
    return repo, base, _git(repo, "rev-parse", "HEAD")


def test_converge_blocked_envelope_carries_finalizer_stop_on_growth(tmp_path, monkeypatch):
    repo, base, head = _repo(tmp_path)
    monkeypatch.chdir(repo)  # the real run_round.py measures base...head in this repo
    state_file = tmp_path / "iterate-state.json"
    state_file.write_text(json.dumps(_state(
        iteration=1, last_verdict="minor-only", original_diff_lines=10,
        budget_baseline_head="h0", budget_baseline_split={"test_added": 0, "code_added": 0},
        budget_last_head="h0", budget_last_round="r1", budget_last_action="noop")),
        encoding="utf-8")
    angle = tmp_path / "r1.txt"
    angle.write_text("```json\n{\"findings\": []}\n```\n", encoding="utf-8")
    posts = []

    def post_fn(url, body):
        posts.append(body)
        return True

    def run_round_fn(stdin):  # the real CLI, with the gh seams closed
        _, env = _cli({**stdin, "posted_comments": [], "self_login": "tp-bot"}, cwd=repo)
        return env

    out = io.StringIO()
    rc = converge.converge(
        base=base, head=head, pr_url=PR, config=CFG, angle_files=[str(angle)],
        proof_root=tmp_path / "proof", state_path=state_file, post_fn=post_fn,
        run_round_fn=run_round_fn,
        comments_fn=lambda _u: [{"author": "tp-bot", "body": posts[-1]}] if posts else [],
        self_login_fn=lambda: "tp-bot", out=out, err=io.StringIO())
    result = json.loads(out.getvalue().strip().splitlines()[-1])
    assert rc == 3 and result["converged"] is False, result
    assert result["terminal"] == "budget-exhausted"
    stop = result["finalizer_stop"]
    assert (stop["source"], stop["signal"], stop["target"], stop["head"]) == (
        "pr-iterate", "growth-lines", PR, head)
    assert stop["detail"]["signal"] == "growth-lines" and stop["detail"]["measured"] == 40


def test_converge_blocked_envelope_forwards_finalizer_stop_only_when_present(tmp_path):
    def blocked(envelope):
        angle = tmp_path / "r.txt"
        angle.write_text("```json\n{\"findings\": []}\n```\n", encoding="utf-8")
        out = io.StringIO()
        converge.converge(
            base="b" * 40, head="a" * 40, pr_url=PR, config=CFG, angle_files=[str(angle)],
            proof_root=tmp_path / "proof", state_path=tmp_path / "s.json",
            post_fn=lambda _u, _b: True, run_round_fn=lambda _s: envelope,
            comments_fn=lambda _u: [], self_login_fn=lambda: "tp-bot",
            run_git=lambda args: (0, "a" * 40 + "\n" if args[1] == "rev-parse" else "3\t1\tf.py\n", ""),
            out=out, err=io.StringIO())
        return json.loads(out.getvalue().strip().splitlines()[-1])

    stop = {"source": "pr-iterate", "signal": "wall-clock", "target": PR, "head": "a" * 40,
            "detail": {"signal": "wall-clock"}}
    with_stop = blocked({"converged": False, "terminal": "cap-exhausted", "finalizer_stop": stop})
    assert with_stop["finalizer_stop"] == stop
    without = blocked({"converged": False, "terminal": None})
    assert "finalizer_stop" not in without
