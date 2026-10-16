"""round_plan.plan — Behavior 6 on real diffs: the security lens of a DELTA round.

design: review-convergence (Task 4.4, detailed-design-security.md Phase 4)

Review bar: a delta round has no separate `security` angle — the lens rides inside
the one `delta-check` angle, and turns on exactly when the DELTA touches a
trust-boundary surface: `trust_boundary.surfaces(delta_text(repo, base, head))`.
An added call site and a REMOVED guard both count; a fix that touches nothing in
the table gets no brief and no `SECURITY_BAR` in its prompt. The detector is fed
the loop's own patch text, never `surfaces_for_range`, so a base sync that brings a
base author's `subprocess.run` into the range stays off. A detector failure is the
opposite: the lens goes ON (fail toward review).
Oracle: example — real commits, real diffs, real table entries (test-fragility).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parents[1] / "_shared"))

import round_plan  # noqa: E402
import trust_boundary  # noqa: E402

_GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
            "GIT_CONFIG_NOSYSTEM": "1", "HOME": "/nonexistent"}

PR_URL = "https://github.com/o/r/pull/9"

BLOCKER = {"source": "code-review", "file": "fix.py", "line_range": [1, 1],
           "summary": "wrong total", "verdict": "structural"}

# The PR commit r1 reviewed: the fix, plus a quoting guard a later fix can remove.
AT_A = "total = 1 + 1\nfixed = True\nsafe = shlex.quote(raw)\n"
# A fix that changes only the arithmetic: no table line added or removed.
PLAIN_FIX = "total = 2\nfixed = True\nsafe = shlex.quote(raw)\n"
CALL = "subprocess.run(argv)"


def _git(repo, *args):
    env = {**os.environ, **_GIT_ENV}
    out = subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                         text=True, env=env, check=True)
    return out.stdout.strip()


def _raw(repo, *args):
    """`_git` without `check` — for the sync merge that stops on a conflict."""
    env = {**os.environ, **_GIT_ENV}
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                          text=True, env=env)
    return done.returncode, done.stdout, done.stderr


def _write(repo, rel, text):
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _commit(repo, message):
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _round(rounds_dir, name, head):
    """One completed round: manifest + blocker findings + tail envelope."""
    rd = Path(rounds_dir) / name
    (rd / "tail").mkdir(parents=True, exist_ok=True)
    (rd / "angles.json").write_text(json.dumps({"head": head}), encoding="utf-8")
    (rd / "tail" / "findings.json").write_text(json.dumps([BLOCKER]), encoding="utf-8")
    (rd / "tail" / "envelope.json").write_text(
        json.dumps({"schema": "tp-pr-iterate/round-tail/v1", "round": 1,
                    "head_reviewed": head, "head_after": head,
                    "tally": {"P": 1, "X": 0, "T": 0, "C": 0, "blocking": 1,
                              "degraded": 0},
                    "downgraded": 0, "notes": 0, "action": "fix", "fix_commit": None,
                    "terminal": None, "converged": False,
                    "budget": {"iteration": 1, "round_cap": 5, "signal": None,
                               "holding": []},
                    "finalizer_stop": None, "summary": "r1"}), encoding="utf-8")
    return rd


def _pr(tmp_path, name, a_text=AT_A):
    """`pr` branch whose head `A` is what r1 reviewed, over one base commit."""
    r = tmp_path / name
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    _git(r, "config", "user.name", "t")
    _git(r, "config", "user.email", "t@t")
    _write(r, "fix.py", "total = 1 + 1\n")
    base = _commit(r, "base")
    _write(r, "fix.py", a_text)
    a = _commit(r, "A pr commit")
    _git(r, "checkout", "-q", "-b", "pr", a)
    return r, tmp_path / f"{name}-root", base, a


def _plan(r, root, base, a, head):
    """`plan` for that PR at `head`, with r1 completed at `a` under `root`."""
    _round(root / "rounds" / "9", "r1", a)
    return round_plan.plan(None, root=root, pr_url=PR_URL, pr_base=base, head=head,
                           repo=str(r))


# ---------- the lens turns ON ----------


def test_a_fix_that_adds_a_call_site_turns_the_lens_on(tmp_path):
    r, root, base, a = _pr(tmp_path, "add")
    _write(r, "fix.py", f"import subprocess\n{CALL}\ntotal = 2\nfixed = True\n")
    head = _commit(r, "B fix adds a call site")
    got = _plan(r, root, base, a, head)
    assert got["mode"] == "delta" and got["security"] is True


def test_the_lens_on_prompt_holds_the_bar_and_the_brief(tmp_path):
    r, root, base, a = _pr(tmp_path, "add2")
    _write(r, "fix.py", f"import subprocess\n{CALL}\ntotal = 2\nfixed = True\n")
    head = _commit(r, "B fix adds a call site")
    prompt = _plan(r, root, base, a, head)["angles"][0]["prompt"]
    assert trust_boundary.SECURITY_BAR in prompt
    assert str(trust_boundary.brief_path(r)) in prompt


def test_a_fix_that_removes_a_guard_turns_the_lens_on(tmp_path):
    """A removed surface line is a surface: the guard that used to be there."""
    r, root, base, a = _pr(tmp_path, "drop")
    _write(r, "fix.py", "total = 2\nfixed = True\n")
    head = _commit(r, "B fix drops the quoting guard")
    got = _plan(r, root, base, a, head)
    assert got["security"] is True
    assert trust_boundary.SECURITY_BAR in got["angles"][0]["prompt"]


def test_a_detector_failure_fails_toward_review(tmp_path, monkeypatch):
    def boom(*_a, **_kw):
        raise trust_boundary.TrustBoundaryError("git diff failed")

    monkeypatch.setattr(trust_boundary, "surfaces", boom)
    r, root, base, a = _pr(tmp_path, "boom")
    _write(r, "fix.py", PLAIN_FIX)
    head = _commit(r, "B plain fix")
    got = _plan(r, root, base, a, head)
    assert got["security"] is True
    assert trust_boundary.SECURITY_BAR in got["angles"][0]["prompt"]


# ---------- the lens stays OFF ----------


def test_a_fix_that_touches_no_surface_leaves_the_lens_off(tmp_path):
    r, root, base, a = _pr(tmp_path, "plain")
    _write(r, "fix.py", PLAIN_FIX)
    head = _commit(r, "B plain fix")
    assert _plan(r, root, base, a, head)["security"] is False


def test_the_lens_off_prompt_holds_neither_the_bar_nor_the_brief(tmp_path):
    r, root, base, a = _pr(tmp_path, "plain2")
    _write(r, "fix.py", PLAIN_FIX)
    head = _commit(r, "B plain fix")
    prompt = _plan(r, root, base, a, head)["angles"][0]["prompt"]
    assert trust_boundary.SECURITY_BAR not in prompt
    assert str(trust_boundary.brief_path(r)) not in prompt


def test_a_sync_merge_bringing_a_base_call_site_leaves_the_lens_off(tmp_path):
    """The base author's `subprocess.run` is in the range, never in the delta."""
    r, root, base, a = _pr(tmp_path, "sync")
    _git(r, "checkout", "-q", "main")
    _write(r, "base_only.py", f"import subprocess\n\n\ndef go(argv):\n    {CALL}\n")
    _commit(r, "base work adds a call site")
    _git(r, "checkout", "-q", "pr")
    _git(r, "merge", "--no-ff", "-q", "-m", "sync main", "main")
    _write(r, "fix.py", PLAIN_FIX)
    head = _commit(r, "B plain fix after the sync")
    got = _plan(r, root, base, a, head)
    assert got["mode"] == "delta" and got["security"] is False
    # The same range read as a plain diff WOULD report the base's call site.
    assert trust_boundary.surfaces_for_range(str(r), a, head) != []


def test_a_sync_the_loop_resolves_by_hand_turns_the_lens_on(tmp_path):
    """A hand resolution IS loop-authored code, so its surface counts."""
    r, root, base, a = _pr(tmp_path, "hand", a_text="total = 1 + 1\nfixed = True\n")
    _git(r, "checkout", "-q", "main")
    _write(r, "fix.py", "total = 9\n")
    _commit(r, "base work conflicts")
    _git(r, "checkout", "-q", "pr")
    _raw(r, "merge", "--no-ff", "-m", "sync main", "main")
    _write(r, "fix.py", f"total = 1 + 1\nfixed = True\n{CALL}\n")
    head = _commit(r, "sync main resolved by hand")
    got = _plan(r, root, base, a, head)
    assert got["security"] is True
    assert trust_boundary.SECURITY_BAR in got["angles"][0]["prompt"]


# ---------- the delta-check angle itself ----------


def test_delta_check_angle_adds_the_bar_and_brief_only_with_a_brief():
    findings = "/x/rounds/9/r1/tail/findings.json"
    off = round_plan.delta_check_angle(findings)
    assert trust_boundary.SECURITY_BAR not in off["prompt"]
    assert "/x/brief.md" not in off["prompt"]
    on = round_plan.delta_check_angle(findings, security_brief="/x/brief.md")
    assert trust_boundary.SECURITY_BAR in on["prompt"]
    assert "/x/brief.md" in on["prompt"]
    assert on["name"] == off["name"] == round_plan.DELTA_CHECK
