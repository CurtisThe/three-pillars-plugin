"""`round_scratch prepare` delegates the round plan to `round_plan` (review-convergence 4.6).

design: review-convergence (Task 4.6, detailed-design-pr-loop §D3)

The CLI stops deciding the round itself: `_cmd_prepare` calls `round_plan.plan` and
`prepare` merges the plan's own keys into the manifest. So the manifest of a real
round-1 prepare on a real tmp git repo carries `mode` "full", `pr_base` == the
`--base` sha (and `base` == `pr_base` — round 1 reviews the whole PR), `security`
True with the `security` angle present last, and `diff_lines` an int. `--review-weight`
reaches `plan`, which stamps it into the existing iterate-state file beside the keys
it already had. A round 2 with no qualifying prior head refuses `prepare-refused`
rather than silently widening back to the full diff — but a round 2 at the SAME head
as a round that reviewed (a fix round with no applicable fixes makes no commit)
inherits that round's `base` and findings: same-head inheritance, the `.1` rule
generalised (dispatcher ruling, Task 4.6).

Oracle: example — exact manifest keys/angles and the exact state document on a real
tmp git repo driven through the CLI (test-fragility).
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
import round_scratch as rs  # noqa: E402

SCRIPT = _HERE / "round_scratch.py"
PR = "https://github.com/o/r/pull/42"

_GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
            "GIT_CONFIG_NOSYSTEM": "1", "HOME": "/nonexistent"}

# The tail envelope `round_scratch._next_ordinal` reads to name the next round.
_ENVELOPE = {"schema": "tp-pr-iterate/round-tail/v1", "round": 1,
             "head_reviewed": "", "head_after": "",
             "tally": {"P": 0, "X": 0, "T": 0, "C": 0, "blocking": 0, "degraded": 0},
             "downgraded": 0, "notes": 0, "action": "fix", "fix_commit": None,
             "terminal": None, "converged": False,
             "budget": {"iteration": 1, "round_cap": 5, "signal": None, "holding": []},
             "finalizer_stop": None, "summary": "r1"}


def _git(repo, *args):
    env = {**os.environ, **_GIT_ENV}
    out = subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                         text=True, env=env, check=True)
    return out.stdout.strip()


def _write(repo, rel, text):
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _commit(repo, message):
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _repo(tmp_path):
    """A real PR: a base commit and one PR commit on top → (repo, pr_base, head)."""
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    _git(r, "config", "user.name", "t")
    _git(r, "config", "user.email", "t@t")
    _write(r, "keep.py", "one = 1\n")
    base = _commit(r, "base")
    _write(r, "work.py", "".join(f"v{i} = {i}\n" for i in range(40)))
    return r, base, _commit(r, "pr work")


def _prepare(repo, root, base, head, state, *extra):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "prepare", "--root", str(root), "--pr-url", PR,
         "--base", base, "--head", head, "--state", str(state),
         "--log", str(root / "log.md"), "--rulings", "rulings.md", *extra],
        cwd=str(repo), capture_output=True, text=True, timeout=120)


def _manifest(round_dir: Path) -> dict:
    return json.loads((round_dir / "angles.json").read_text(encoding="utf-8"))


def test_round_one_manifest_carries_the_plan_keys(tmp_path):
    repo, base, head = _repo(tmp_path)
    root = tmp_path / "proof"
    p = _prepare(repo, root, base, head, root / "iterate-state.42.v1.json")
    assert p.returncode == 0, p.stdout + p.stderr
    m = _manifest(Path(p.stdout.strip()))
    assert m["mode"] == "full"
    assert m["pr_base"] == base and m["base"] == base
    assert m["security"] is True
    assert isinstance(m["diff_lines"], int) and not isinstance(m["diff_lines"], bool)
    assert m["diff_lines"] >= 40  # the PR's own added lines, counted
    assert m["angles"][-1]["name"] == "security"


def test_review_weight_reaches_the_plan_and_the_state(tmp_path):
    repo, base, head = _repo(tmp_path)
    root = tmp_path / "proof"
    state = root / "iterate-state.42.v1.json"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps({"phase": "reviewing", "iteration": 0}), encoding="utf-8")
    p = _prepare(repo, root, base, head, state, "--review-weight", "light")
    assert p.returncode == 0, p.stdout + p.stderr
    doc = json.loads(state.read_text(encoding="utf-8"))
    assert doc["review_weight"] == "light"
    assert doc["phase"] == "reviewing" and doc["iteration"] == 0


def test_cmd_prepare_delegates_to_round_plan(tmp_path, monkeypatch):
    """`_cmd_prepare` calls `round_plan.plan` — not `finder_round.round_angles`."""
    repo, base, head = _repo(tmp_path)
    root = tmp_path / "proof"
    seen = {}
    real = round_plan.plan

    def fake_plan(config, **kw):
        seen["config"] = config
        seen.update(kw)
        return real(config, **kw)

    monkeypatch.setattr(round_plan, "plan", fake_plan)
    monkeypatch.chdir(repo)
    rc = rs.main(["prepare", "--root", str(root), "--pr-url", PR, "--base", base,
                  "--head", head, "--state", str(root / "s.json"),
                  "--log", str(root / "l.md"), "--rulings", "r.md",
                  "--review-weight", "light"])
    assert rc == 0
    assert seen["review_weight"] == "light"
    assert seen["pr_base"] == base and seen["pr_url"] == PR
    assert seen["head"] == head
    assert seen["state_path"] == str(root / "s.json")
    assert seen["rulings_path"] == "r.md"


def test_round_two_with_no_qualifying_prior_refuses(tmp_path):
    """A re-prepare on the same head after a round that left no findings (nothing was
    reviewed, so there is nothing to inherit): `PlanRefused` → exit 2 `prepare-refused`.
    """
    repo, base, head = _repo(tmp_path)
    root = tmp_path / "proof"
    first = _prepare(repo, root, base, head, root / "iterate-state.42.v1.json")
    assert first.returncode == 0, first.stdout + first.stderr
    r1 = Path(first.stdout.strip())
    (r1 / "tail" / "envelope.json").write_text(
        json.dumps({**_ENVELOPE, "head_reviewed": head, "head_after": head}),
        encoding="utf-8")
    second = _prepare(repo, root, base, head, root / "iterate-state.42.v1.json")
    assert second.returncode == 2, second.stdout + second.stderr
    assert json.loads(second.stdout)["reason"] == "prepare-refused"
    assert not (root / "rounds" / "42" / "r2").exists()


# One real (non-sentinel) blocker: the shape a reviewed round's tail leaves behind.
_BLOCKER = {"file": "work.py", "line_range": [1, 2], "summary": "unchecked input",
            "verdict": "structural", "blocking": True, "class": "P"}


def test_round_two_at_the_same_head_inherits_the_reviewed_base(tmp_path):
    """A fix round with no applicable fixes makes no commit, so r2 is prepared at r1's
    head. Same-head inheritance: r2 takes r1's reviewed `base` (the PR base) and r1's
    findings — one `delta-check`, never a refusal and never the full finder set.
    """
    repo, base, head = _repo(tmp_path)
    root = tmp_path / "proof"
    state = root / "iterate-state.42.v1.json"
    first = _prepare(repo, root, base, head, state)
    assert first.returncode == 0, first.stdout + first.stderr
    r1 = Path(first.stdout.strip())
    (r1 / "tail" / "findings.json").write_text(json.dumps([_BLOCKER]), encoding="utf-8")
    (r1 / "tail" / "envelope.json").write_text(
        json.dumps({**_ENVELOPE, "head_reviewed": head, "head_after": head}),
        encoding="utf-8")
    second = _prepare(repo, root, base, head, state)
    assert second.returncode == 0, second.stdout + second.stderr
    r2 = Path(second.stdout.strip())
    assert r2 == root / "rounds" / "42" / "r2"
    m = _manifest(r2)
    assert m["mode"] == "delta"
    assert m["base"] == _manifest(r1)["base"] == base
    assert m["pr_base"] == base
    assert [e["name"] for e in m["angles"]] == ["delta-check"]
    assert str(r1 / "tail" / "findings.json") in m["angles"][0]["prompt"]
