"""Terminal → raise round_cap in the REAL config → re-run → exactly one fix [Q1].

design: iterate-convergence-budget (Task 7.3, R1, Q1)

A temp PR repo with a TRACKED `.three-pillars/config.json` (`round_cap: 6`). Every
round-scratch step runs by subprocess (`round_scratch.py prepare`/`flush`,
`reproduce.py --round-dir`, `run_round.py`, `converge.py --round-dir`); the inline
fix is `fix_round.run_round(paths=derive_fix_paths(...))` pushing to a bare origin.
`run_round.py` gets no `config` on stdin, so it reads the working-tree config from
its cwd — the file the operator edits. Only `gh` is shimmed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
for p in (HERE, HERE.parent.parent / "tp-pr-fix" / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import fix_round  # noqa: E402
import loop_itest as it  # noqa: E402
import tree_scope  # noqa: E402


@pytest.fixture()
def pr(tmp_path, monkeypatch):
    wt, base, head = it.make_repo(tmp_path, round_cap=6)
    extra = it.fake_gh(tmp_path)
    for k, v in extra.items():
        monkeypatch.setenv(k, v)
    monkeypatch.chdir(wt)
    return wt, base, head, it.Loop(tmp_path, extra)


def _note(n):
    return {"file": "src/feature.py", "line_range": [n, n], "summary": f"nit {n}",
            "class": "C", "blocking": False}


def _review(loop, wt, base, head, n):
    """One blocking review round (+ a non-blocking note) → the run_round envelope."""
    rd = loop.prepare(wt, base, head)
    it.write_replies(rd, it.reply([it.blocking_finding(), _note(n)]))
    rep = loop.reproduce(rd, wt, head)
    assert rep.returncode == 0, rep.stdout + rep.stderr
    rr = loop.run_round(rd, wt, it.tail_findings(rd), config=False)
    assert rr.returncode == 0, rr.stdout + rr.stderr
    return rd, it.last_json(rr)


def _inline_fix(wt, rd, n):
    snapshot = tree_scope.untracked_snapshot(wt)
    it.write(wt, "src/a.py", f"a = {n + 1}\n")
    derived = tree_scope.derive_fix_paths(wt, snapshot)
    assert derived == ["src/a.py"]  # config / decisions.md never derived
    assert tree_scope.check_fix_paths(derived, ["src/a.py"]) == tree_scope.OK
    blocking = [f for f in it.tail_findings(rd) if f["verdict"] == "structural"]
    out = fix_round.run_round("d", it.PR, n, blocking, head_ref="feat", loop_mode=True,
                              paths=derived)
    assert out["verdict"] == "applied"
    return it.git(wt, "rev-parse", "HEAD")


def _log_lines(loop):
    return [ln for ln in loop.log.read_text(encoding="utf-8").splitlines() if ln.strip()]


def test_raise_round_cap_in_real_config_then_exactly_one_fix(pr):
    wt, base, head, loop = pr
    decisions = wt / it.DECISIONS
    original = decisions.read_text(encoding="utf-8")

    # Rounds 1–5 blocking → fix; round 6 blocking → round-cap terminal.
    for n in range(1, 7):
        rd, env = _review(loop, wt, base, head, n)
        if n < 6:
            assert env["action"] == "fix" and env["terminal"] is None
            head_after = _inline_fix(wt, rd, n)
            it.write_envelope(rd, action="fix", head_reviewed=head, head_after=head_after)
            head = head_after
    assert env["terminal"] == "budget-exhausted" and env["action"] == "noop"
    assert env["budget"]["signal"] == "round-cap" and env["budget"]["iteration"] == 6
    it.write_envelope(rd, action="noop", head_reviewed=head, head_after=head,
                      terminal="budget-exhausted", budget=env["budget"])

    # Terminal flush: decisions.md modified-uncommitted; HEAD is the (pushed) PR head.
    first = _log_lines(loop)
    assert len(first) == 6
    assert loop.flush(wt, decisions) == {"appended": 6}
    after_first = decisions.read_text(encoding="utf-8")
    assert after_first == original + "\n".join(first) + "\n"
    assert it.git(wt, "diff", "--name-only") == it.DECISIONS
    assert it.git(wt, "rev-parse", "HEAD") == head == it.git(wt, "rev-parse", "origin/feat")

    # The operator raises the limit in the REAL tracked config, left uncommitted.
    cfg_path = wt / it.CONFIG
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["pdw"]["guards"]["round_cap"] = 7
    cfg_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    assert it.git(wt, "show", f"HEAD:{it.CONFIG}").count('"round_cap": 6') == 1

    # Re-run: new ordinal; reproduce accepts the tree; check 0 lifts; one fix.
    rd7, env = _review(loop, wt, base, head, 7)
    assert rd7.name == "r7" and it.manifest(rd7)["round"] == 7
    assert env["terminal"] is None and env["action"] == "fix"
    assert env["budget"]["round_cap"] == 7 and env["budget"]["iteration"] == 6
    state = loop.read_state()
    assert state["termination_reason"] is None
    assert any(t.get("note") == "[budget-lifted] round-cap" for t in state["transitions"])
    fix_head = _inline_fix(wt, rd7, 7)
    it.write_envelope(rd7, action="fix", head_reviewed=head, head_after=fix_head)
    assert it.git(wt, "rev-list", "--count", f"{head}..{fix_head}") == "1"
    assert it.git(wt, "show", "--name-only", "--format=", fix_head) == "src/a.py"
    dirty = set(it.git(wt, "diff", "--name-only").splitlines())
    assert dirty == {it.CONFIG, it.DECISIONS}  # config still modified, never committed

    # Round 7 is the fix head: clean → converge.py finishes under the raised cap.
    rd8 = loop.prepare(wt, base, fix_head)
    it.write_replies(rd8)
    assert loop.reproduce(rd8, wt, fix_head).returncode == 0
    conv = loop.converge(rd8, wt)
    assert conv.returncode == 0, conv.stdout + conv.stderr
    assert it.last_json(conv)["converged"] is True
    assert loop.read_state()["iteration"] == 7
    assert it.git(wt, "rev-list", "--count", f"{head}..HEAD") == "1"  # exactly one fix

    # A second flush appends only the new lines.
    new = _log_lines(loop)
    assert new and all(ln not in first for ln in new)
    assert loop.flush(wt, decisions) == {"appended": len(new)}
    assert decisions.read_text(encoding="utf-8") == after_first + "\n".join(new) + "\n"
