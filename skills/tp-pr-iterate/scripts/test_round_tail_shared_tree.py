"""Shared tree — two rounds and a degraded re-run in one dirty worktree (A1/A3).

design: iterate-convergence-budget (Task 7.2)

The round tail runs in the orchestrator's own worktree, which carries a tracked,
locally modified `decisions.md` and an untracked stray file. Every loop step but
the inline fix runs by subprocess (`round_scratch.py`, `reproduce.py`,
`run_round.py`, `converge.py`); the fix is `fix_round.run_round(paths=...)` with
mechanically derived paths, pushing to a real bare origin. Only `gh` is shimmed.
"""
from __future__ import annotations

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

NOTE = {"file": "src/feature.py", "line_range": [30, 30], "summary": "naming nit", "class": "C",
        "blocking": False}


@pytest.fixture()
def pr(tmp_path, monkeypatch):
    wt, base, head = it.make_repo(tmp_path)
    it.write(wt, it.DECISIONS, "# decisions\nlocal operator edit\n")
    it.write(wt, "notes/stray.txt", "operator scratch\n")
    extra = it.fake_gh(tmp_path)
    for k, v in extra.items():
        monkeypatch.setenv(k, v)
    monkeypatch.chdir(wt)
    return wt, base, head, it.Loop(tmp_path, extra)


def _blocking_round(loop, wt, base, head, extra=()):
    rd = loop.prepare(wt, base, head)
    it.write_replies(rd, it.reply([it.blocking_finding(), *extra]))
    rep = loop.reproduce(rd, wt, head)
    assert rep.returncode == 0, rep.stdout + rep.stderr  # dirty decisions.md + stray: accepted
    rr = loop.run_round(rd, wt, it.tail_findings(rd))
    assert rr.returncode == 0, rr.stdout + rr.stderr
    env = it.last_json(rr)
    assert env["action"] == "fix" and env["terminal"] is None
    return rd


def _committed(wt):
    return it.git(wt, "show", "--name-only", "--format=", "HEAD").split()


def test_two_rounds_and_degraded_rerun_share_the_tree(pr):
    wt, base, head, loop = pr
    decisions = wt / it.DECISIONS
    before = decisions.read_text(encoding="utf-8")

    # Round 1: blocking → inline fix of exactly the edited code file.
    rd1 = _blocking_round(loop, wt, base, head, extra=[NOTE])
    snapshot = tree_scope.untracked_snapshot(wt)
    it.write(wt, "src/a.py", "a = 2\n")
    derived = tree_scope.derive_fix_paths(wt, snapshot)
    assert derived == ["src/a.py"]
    assert tree_scope.check_fix_paths(derived, ["src/a.py"]) == tree_scope.OK
    blocking = [f for f in it.tail_findings(rd1) if f["verdict"] == "structural"]
    assert blocking and all(f["source"] == "code-review" and f["comment_id"] is None
                            for f in blocking)
    out = fix_round.run_round("d", it.PR, 1, blocking, head_ref="feat", loop_mode=True,
                              paths=derived)
    assert out["verdict"] == "applied" and len(out["fixes_applied"]) == 1
    assert _committed(wt) == ["src/a.py"]
    head2 = it.git(wt, "rev-parse", "HEAD")
    assert head2 != head and it.git(wt, "rev-parse", "origin/feat") == head2
    assert it.git(wt, "diff", "--name-only") == it.DECISIONS  # still modified, uncommitted
    assert it.git(wt, "ls-files", "--others", "--exclude-standard") == "notes/stray.txt"
    it.write_envelope(rd1, action="fix", head_reviewed=head, head_after=head2)

    # Round 2: one angle leaves no reply → degraded-only → no fix, rerun-review.
    rd2 = loop.prepare(wt, base, head2)
    it.write_replies(rd2, drop=1)
    rep = loop.reproduce(rd2, wt, head2)
    assert rep.returncode == 0, rep.stdout + rep.stderr
    assert it.last_json(rep)["tally"]["degraded"] == 1
    rr = loop.run_round(rd2, wt, it.tail_findings(rd2))
    assert rr.returncode == 0 and it.last_json(rr)["terminal"] is None
    it.write_envelope(rd2, action="rerun-review", head_reviewed=head2, head_after=head2)

    # Round 2 re-run (r2.1): clean → converge.py --round-dir finishes for real.
    rd21 = loop.prepare(wt, base, head2)
    assert rd21.name == "r2.1"
    it.write_replies(rd21)
    assert loop.reproduce(rd21, wt, head2).returncode == 0
    conv = loop.converge(rd21, wt)
    assert conv.returncode == 0, conv.stdout + conv.stderr
    assert it.last_json(conv)["converged"] is True
    assert loop.read_state()["iteration"] == 2
    assert it.git(wt, "rev-parse", "HEAD") == head2

    # No loop step wrote decisions.md; the terminal flush appends the log once.
    assert decisions.read_text(encoding="utf-8") == before
    logged = [ln for ln in loop.log.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert logged and logged[0].startswith("[tp-pr-iterate/note] round 1 C src/feature.py:30")
    assert loop.flush(wt, decisions) == {"appended": len(logged)}
    assert decisions.read_text(encoding="utf-8") == before + "\n".join(logged) + "\n"
    assert loop.log.read_text(encoding="utf-8") == ""
    assert loop.flush(wt, decisions) == {"appended": 0}
    assert decisions.read_text(encoding="utf-8") == before + "\n".join(logged) + "\n"


def test_stray_file_created_during_fix_is_a_mismatch_no_commit(pr):
    wt, base, head, loop = pr
    _blocking_round(loop, wt, base, head)
    snapshot = tree_scope.untracked_snapshot(wt)
    assert "notes/stray.txt" in snapshot
    it.write(wt, "src/a.py", "a = 2\n")
    it.write(wt, "src/debug_scratch.py", "print('x')\n")  # the fixer's stray
    derived = tree_scope.derive_fix_paths(wt, snapshot)
    assert derived == ["src/a.py", "src/debug_scratch.py"]
    verdict = tree_scope.check_fix_paths(derived, ["src/a.py"])
    assert verdict == tree_scope.MISMATCH
    # The tail commits nothing on a mismatch: HEAD and origin stay on the reviewed head.
    assert it.git(wt, "rev-parse", "HEAD") == head
    assert it.git(wt, "rev-parse", "origin/feat") == head
